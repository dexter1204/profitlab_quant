"""ProfitLab Quant — FastAPI backend.

Serves the gamma/beta analytics from `profitlab/` as JSON so a static
frontend (hosted on SiteGround at /quantsistem) can render it. The
Polygon/Massive API key lives here, server-side, never in the browser.

Run locally:
    uvicorn api.main:app --reload --port 8000

Deploy (Render): start command
    uvicorn api.main:app --host 0.0.0.0 --port $PORT

Env vars the server reads (set these in Render → Environment):
    PROFITLAB_VENDOR   polygon | yfinance | polygon_mcp   (default yfinance)
    POLYGON_API_KEY    your Massive/Polygon REST key
    POLYGON_BASE_URL   https://api.massive.com  (default)
    ALLOWED_ORIGINS    comma-separated, e.g. https://profitlab-academy.com
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import Depends  # noqa: E402

from profitlab import exposures, metrics, regime, iv as ivmod, market  # noqa: E402
from profitlab import data as pdata  # noqa: E402

from . import auth as auth_mod, db as db_mod  # noqa: E402
from .auth import require_access  # noqa: E402

app = FastAPI(title="ProfitLab Quant API", version="1.0")

_origins = [
    o.strip() for o in os.environ.get(
        "ALLOWED_ORIGINS",
        "https://profitlab-academy.com,http://localhost:8000,http://localhost:5500",
    ).split(",") if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# accounts / coupons / admin
app.include_router(auth_mod.auth_router)
app.include_router(auth_mod.coupon_router)
app.include_router(auth_mod.admin_router)


@app.on_event("startup")
def _startup():
    db_mod.init_db()
    auth_mod.ensure_admin()


# Every market-data endpoint requires an active (non-expired) account.
GATED = [Depends(require_access)]


# ── tiny in-memory TTL cache (keeps Polygon calls light) ─────────────────────
_CACHE: dict[str, tuple[float, object]] = {}
_TTL = float(os.environ.get("PROFITLAB_CACHE_TTL", "300"))  # seconds


def _cached(key: str, producer):
    now = time.time()
    hit = _CACHE.get(key)
    if hit and now - hit[0] < _TTL:
        return hit[1]
    value = producer()
    _CACHE[key] = (now, value)
    return value


def _clean(x):
    """JSON-safe: NaN/inf → None, numpy scalars → python."""
    try:
        import math
        if x is None:
            return None
        xf = float(x)
        return xf if math.isfinite(xf) else None
    except (TypeError, ValueError):
        return x


# ── endpoints ────────────────────────────────────────────────────────────────
@app.get("/")
def root():
    return {"service": "profitlab-quant", "status": "ok",
            "vendor": pdata.vendor_name()}


@app.get("/api/health")
def health():
    return {"ok": True, "vendor": pdata.vendor_name(), "ts": time.time()}


def _strike_step(strikes) -> float:
    s = pd.Series(pd.unique(pd.Series(strikes).sort_values()))
    d = s.diff().dropna()
    return float(d.median()) if len(d) else 1.0


def _gamma_payload(ticker: str, window: int) -> dict:
    """Core Gamma & Flow computation shared by /analyze and /chart."""
    chain = pdata.option_chain(ticker)
    spot = pdata.spot(ticker)
    ctx = exposures.ChainContext(
        spot=spot,
        asof=pd.Timestamp.now("UTC").tz_localize(None).normalize(),
    )
    gex = exposures.gex_by_strike(chain, ctx)
    dex = exposures.dex_by_strike(chain, ctx)
    totals = exposures.totals(chain, ctx)
    levels = metrics.key_levels(chain, gex, dex, spot).as_dict()
    reg = regime.classify(spot, levels.get("gamma_flip"),
                          total_gex=totals.get("gex"))

    step = _strike_step(gex["strike"])
    lo, hi = spot - window * step, spot + window * step
    g = gex[(gex["strike"] >= lo) & (gex["strike"] <= hi)].sort_values("strike")
    d = dex[(dex["strike"] >= lo) & (dex["strike"] <= hi)].sort_values("strike")

    return {
        "ticker": ticker,
        "vendor": pdata.vendor_name(),
        "spot": _clean(spot),
        "asof": ctx.asof.isoformat(),
        "levels": {k: _clean(v) for k, v in levels.items()},
        "totals": {k: _clean(v) for k, v in totals.items()},
        "regime": {
            "label": reg.label,
            "reading": reg.reading,
            "g_flip": _clean(reg.g_flip),
            "gap_pct": _clean(reg.gap_pct),
        },
        "strikes": [float(s) for s in g["strike"]],
        "gex": [_clean(v) for v in g["gex"]],
        "dex_strikes": [float(s) for s in d["strike"]],
        "dex": [_clean(v) for v in d["dex"]],
    }


@app.get("/api/analyze/{ticker}", dependencies=GATED)
def analyze(ticker: str, window: int = Query(20, ge=5, le=60)):
    """Everything the Gamma & Flow view needs for one ticker, as JSON."""
    ticker = ticker.upper().strip()
    try:
        return _cached(f"analyze:{ticker}:{window}",
                       lambda: _gamma_payload(ticker, window))
    except Exception as e:  # surface vendor errors cleanly to the frontend
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/api/chart/{ticker}", dependencies=GATED)
def chart(ticker: str,
          interval: str = Query("1m"),
          period: str = Query("1d"),
          window: int = Query(24, ge=5, le=60)):
    """Intraday OHLC candles + the GEX-by-strike profile and key levels so
    the frontend can draw a pro-style chart with the gamma profile at the
    side. Bars are best-effort (some vendors/plans don't serve intraday
    stock bars); the gamma profile always comes back."""
    ticker = ticker.upper().strip()

    def _bars_from(df):
        df = df.dropna(subset=["open", "high", "low", "close"])
        return [
            {
                "t": pd.Timestamp(r.ts).isoformat(),
                "o": _clean(r.open), "h": _clean(r.high),
                "l": _clean(r.low), "c": _clean(r.close),
                "v": _clean(getattr(r, "volume", None)),
            }
            for r in df.itertuples(index=False)
        ]

    def _yf_bars():
        # yfinance serves free (delayed) intraday bars for stocks AND indices
        # (^SPX, ^NDX); used as a fallback so the chart has candles even on an
        # options-only Polygon plan that can't price stock aggregates.
        from profitlab.data import yfinance as _yf
        return _yf.intraday_bars(ticker, interval=interval, period=period)

    def _compute():
        payload = _gamma_payload(ticker, window)
        bars, source = [], None
        loaders = [("vendor", lambda: pdata.intraday_bars(ticker, interval=interval, period=period))]
        if pdata.vendor_name() not in ("yf", "yfinance"):
            loaders.append(("yfinance", _yf_bars))
        for name, loader in loaders:
            try:
                df = loader()
                if df is not None and len(df):
                    bars = _bars_from(df)
                    if bars:
                        source = name
                        break
            except Exception:
                continue
        payload["bars"] = bars
        payload["bars_source"] = source
        payload["interval"] = interval
        payload["period"] = period
        return payload

    try:
        return _cached(f"chart:{ticker}:{interval}:{period}:{window}", _compute)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/api/oi/{ticker}", dependencies=GATED)
def oi(ticker: str, window: int = Query(20, ge=5, le=60)):
    """Call/put open interest per strike (and each as a share of total OI)
    — powers the OI and % OI view."""
    ticker = ticker.upper().strip()

    def _compute():
        chain = pdata.option_chain(ticker)
        spot = pdata.spot(ticker)
        tbl = (chain.groupby(["strike", "type"], as_index=False)["oi"].sum()
               .pivot(index="strike", columns="type", values="oi").fillna(0.0))
        if "call" not in tbl:
            tbl["call"] = 0.0
        if "put" not in tbl:
            tbl["put"] = 0.0
        total = float(tbl["call"].sum() + tbl["put"].sum()) or 1.0
        step = _strike_step(tbl.index.to_numpy())
        lo, hi = spot - window * step, spot + window * step
        view = tbl[(tbl.index >= lo) & (tbl.index <= hi)].sort_index()
        return {
            "ticker": ticker, "spot": _clean(spot),
            "strikes": [float(s) for s in view.index],
            "call_oi": [float(v) for v in view["call"]],
            "put_oi": [float(v) for v in view["put"]],
            "call_pct": [float(v) / total for v in view["call"]],
            "put_pct": [float(v) / total for v in view["put"]],
        }

    try:
        return _cached(f"oi:{ticker}:{window}", _compute)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/api/gex_heatmap/{ticker}", dependencies=GATED)
def gex_heatmap(ticker: str, window: int = Query(18, ge=5, le=60)):
    """GEX on a strike × expiry grid — the GEX heat map. Returns a dense
    matrix `z[strike_index][expiry_index]` plus the axes."""
    ticker = ticker.upper().strip()

    def _compute():
        chain = pdata.option_chain(ticker)
        spot = pdata.spot(ticker)
        ctx = exposures.ChainContext(
            spot=spot,
            asof=pd.Timestamp.now("UTC").tz_localize(None).normalize(),
        )
        grid = exposures.gex_by_strike_expiry(chain, ctx)
        step = _strike_step(grid["strike"])
        lo, hi = spot - window * step, spot + window * step
        grid = grid[(grid["strike"] >= lo) & (grid["strike"] <= hi)]
        wide = (grid.pivot(index="strike", columns="expiry", values="gex")
                .sort_index())
        wide = wide.reindex(sorted(wide.columns), axis=1)
        strikes = [float(s) for s in wide.index]
        expiries = [pd.Timestamp(c).strftime("%Y-%m-%d") for c in wide.columns]
        z = [[_clean(v) for v in row] for row in wide.to_numpy()]
        return {
            "ticker": ticker, "spot": _clean(spot),
            "strikes": strikes, "expiries": expiries, "z": z,
        }

    try:
        return _cached(f"gexheat:{ticker}:{window}", _compute)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/api/iv/{ticker}", dependencies=GATED)
def iv_premium(ticker: str):
    """ATM IV vs realized vol (HV10/30/60), premium and term structure."""
    ticker = ticker.upper().strip()

    def _compute():
        chain = pdata.option_chain(ticker)
        spot = pdata.spot(ticker)
        by_exp = exposures.iv_by_expiry(chain, spot)
        iv_atm = float(by_exp["atm_iv"].iloc[0]) if len(by_exp) else float("nan")
        front = iv_atm
        back = float(by_exp["atm_iv"].iloc[-1]) if len(by_exp) else None
        closes = pdata.price_history(ticker, period="6mo", interval="1d")
        snap = ivmod.snapshot(iv_atm, closes, front_iv=front, back_iv=back)
        return {"ticker": ticker, "spot": _clean(spot),
                **{k: _clean(v) if isinstance(v, (int, float)) else v
                   for k, v in snap.as_dict().items()}}

    try:
        return _cached(f"iv:{ticker}", _compute)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/api/market", dependencies=GATED)
def market_heatmap():
    """Day-change treemap data for the market universe. Falls back to the
    deterministic demo universe if the live vendor returns nothing (e.g. an
    options-only plan can't price the stock universe)."""

    def _compute():
        try:
            df = market.live_heatmap()
        except Exception:
            df = None
        source = "live"
        if df is None or len(df) < 3:
            df = market.demo_heatmap()
            source = "demo"
        s = market.summarize(df)
        rows = [
            {"ticker": r.ticker, "sector": r.sector,
             "price": _clean(r.price), "pct": _clean(r.pct),
             "weight": _clean(r.weight)}
            for r in df.itertuples(index=False)
        ]
        return {
            "source": source,
            "rows": rows,
            "summary": {
                "n_symbols": s.n_symbols, "n_up": s.n_up, "n_down": s.n_down,
                "breadth_pct": _clean(s.breadth_pct),
                "best": {"ticker": s.best[0], "pct": _clean(s.best[1])},
                "worst": {"ticker": s.worst[0], "pct": _clean(s.worst[1])},
            },
        }

    try:
        return _cached("market", _compute)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


def _atm_iv(chain, spot) -> float:
    """Front-expiry ATM implied vol, with a sane fallback."""
    try:
        by_exp = exposures.iv_by_expiry(chain, spot)
        if len(by_exp):
            v = float(by_exp["atm_iv"].iloc[0])
            if v and v == v and v > 0:  # finite & positive
                return v
    except Exception:
        pass
    return 0.20


@app.get("/api/delta_surface/{ticker}", dependencies=GATED)
def delta_surface(ticker: str,
                  kind: str = Query("call"),
                  days: int = Query(60, ge=7, le=180)):
    """Black-Scholes delta over a (spot × time-to-expiry) grid at the ATM
    strike — the Delta Surface 3-D view."""
    ticker = ticker.upper().strip()
    kind = kind.lower().strip()
    if kind not in ("call", "put"):
        kind = "call"

    def _compute():
        chain = pdata.option_chain(ticker)
        spot = pdata.spot(ticker)
        ctx = exposures.ChainContext(
            spot=spot,
            asof=pd.Timestamp.now("UTC").tz_localize(None).normalize(),
        )
        iv = _atm_iv(chain, spot)
        spot_axis, days_axis, grid = exposures.delta_surface(
            ctx, strike=spot, iv=iv, days_max=days, kind=kind,
        )
        z = [[_clean(v) for v in row] for row in grid]  # (n_time, n_spot)
        return {
            "ticker": ticker, "spot": _clean(spot), "kind": kind,
            "iv": _clean(iv),
            "spot_axis": [float(s) for s in spot_axis],
            "days_axis": [float(d) for d in days_axis],
            "z": z,
        }

    try:
        return _cached(f"dsurf:{ticker}:{kind}:{days}", _compute)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/api/net_drift/{ticker}", dependencies=GATED)
def net_drift(ticker: str, spot_pct: float = Query(0.05, ge=0.01, le=0.20)):
    """Dealer net-delta drift profile across a ±spot_pct spot range. Slope
    sign shows where hedging amplifies (short gamma) or dampens moves."""
    ticker = ticker.upper().strip()

    def _compute():
        chain = pdata.option_chain(ticker)
        spot = pdata.spot(ticker)
        ctx = exposures.ChainContext(
            spot=spot,
            asof=pd.Timestamp.now("UTC").tz_localize(None).normalize(),
        )
        df = exposures.net_drift(chain, ctx, spot_pct=spot_pct)
        gex = exposures.gex_by_strike(chain, ctx)
        dex = exposures.dex_by_strike(chain, ctx)
        levels = metrics.key_levels(chain, gex, dex, spot).as_dict()
        return {
            "ticker": ticker, "spot": _clean(spot),
            "gamma_flip": _clean(levels.get("gamma_flip")),
            "delta_flip": _clean(levels.get("delta_flip")),
            "spot_grid": [float(s) for s in df["spot"]],
            "net_delta": [_clean(v) for v in df["net_delta"]],
        }

    try:
        return _cached(f"drift:{ticker}:{spot_pct}", _compute)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/api/vol_drift/{ticker}", dependencies=GATED)
def vol_drift(ticker: str):
    """ATM / call / put implied-vol term structure by expiry (DTE) plus the
    put-call skew — the Volatility Drift view."""
    ticker = ticker.upper().strip()

    def _compute():
        chain = pdata.option_chain(ticker)
        spot = pdata.spot(ticker)
        df = exposures.iv_by_expiry(chain, spot)
        return {
            "ticker": ticker, "spot": _clean(spot),
            "dte": [int(x) for x in df["dte"]],
            "expiries": [pd.Timestamp(e).strftime("%Y-%m-%d") for e in df["expiry"]],
            "atm_iv": [_clean(v) for v in df["atm_iv"]],
            "call_iv": [_clean(v) for v in df["call_iv"]],
            "put_iv": [_clean(v) for v in df["put_iv"]],
            "skew": [_clean(v) for v in df["skew"]],
        }

    try:
        return _cached(f"voldrift:{ticker}", _compute)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/api/vol_surface/{ticker}", dependencies=GATED)
def vol_surface(ticker: str, window: int = Query(18, ge=5, le=60)):
    """Implied vol on a strike × expiry grid — the Volatility Surface view."""
    ticker = ticker.upper().strip()

    def _compute():
        chain = pdata.option_chain(ticker)
        spot = pdata.spot(ticker)
        grid = exposures.iv_surface(chain, spot, strike_window=window)
        wide = (grid.pivot(index="strike", columns="expiry", values="iv")
                .sort_index())
        wide = wide.reindex(sorted(wide.columns), axis=1)
        strikes = [float(s) for s in wide.index]
        expiries = [pd.Timestamp(c).strftime("%Y-%m-%d") for c in wide.columns]
        dte0 = pd.Timestamp(wide.columns.min()) if len(wide.columns) else None
        dte = [int((pd.Timestamp(c) - dte0).days) for c in wide.columns] if dte0 is not None else []
        z = [[_clean(v) for v in row] for row in wide.to_numpy()]
        return {
            "ticker": ticker, "spot": _clean(spot),
            "strikes": strikes, "expiries": expiries, "dte": dte, "z": z,
        }

    try:
        return _cached(f"volsurf:{ticker}:{window}", _compute)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
