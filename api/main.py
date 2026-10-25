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

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import Depends  # noqa: E402

from profitlab import exposures, metrics, regime, iv as ivmod, market  # noqa: E402
from profitlab import data as pdata  # noqa: E402
from profitlab.data import gexbot as gexbotmod  # noqa: E402  — GexBot Classic API
from profitlab import dataquality  # noqa: E402
from profitlab import volume_profile as vpmod  # noqa: E402

from .aula import require_access  # noqa: E402  — access via the Aula Virtual


def _use_vendor_greeks() -> bool:
    """Use the vendor's own greeks (Polygon's gamma/delta) instead of our
    Black-Scholes recompute. Toggle with PROFITLAB_USE_VENDOR_GREEKS=1."""
    return os.environ.get("PROFITLAB_USE_VENDOR_GREEKS", "").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _ctx(spot: float, asof=None) -> "exposures.ChainContext":
    return exposures.ChainContext(
        spot=spot,
        asof=asof or pd.Timestamp.now("UTC").tz_localize(None).normalize(),
        use_vendor_greeks=_use_vendor_greeks(),
    )

app = FastAPI(title="ProfitLab Quant API", version="1.0")

# CORS: allow any origin by default. This is safe here because every data
# endpoint is protected by the Aula Bearer token (no cookies, so no CSRF
# surface), and it removes a whole class of "No Access-Control-Allow-Origin"
# failures from www/non-www or env typos. Lock it down by setting
# ALLOWED_ORIGINS to a comma-separated list if you ever want to.
_allowed = os.environ.get("ALLOWED_ORIGINS", "*").strip()
if _allowed in ("", "*"):
    _cors = dict(allow_origins=["*"])
else:
    _cors = dict(allow_origins=[o.strip() for o in _allowed.split(",") if o.strip()],
                 allow_origin_regex=os.environ.get("ALLOWED_ORIGIN_REGEX"))
app.add_middleware(
    CORSMiddleware,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    **_cors,
)


# Every market-data endpoint requires a valid Aula session with active quant
# access (granted by a coupon or a payment — enforced by the Aula API).
GATED = [Depends(require_access)]


# ── tiny in-memory TTL cache (keeps Polygon calls light) ─────────────────────
_CACHE: dict[str, tuple[float, object]] = {}
# Short TTL so prices/levels stay close to live (auto-refresh in the frontend
# re-fetches on this cadence). It's a SHARED server cache — one vendor call per
# window per (view·ticker) no matter how many viewers. Raise PROFITLAB_CACHE_TTL
# in Render if you ever need to spare API calls.
_TTL = float(os.environ.get("PROFITLAB_CACHE_TTL", "30"))  # seconds


def _cached(key: str, producer):
    now = time.time()
    hit = _CACHE.get(key)
    if hit and now - hit[0] < _TTL:
        return hit[1]
    value = producer()
    _CACHE[key] = (now, value)
    return value


# Separate long-lived cache for the GexBot hist/eod download (a ~30MB ZIP that
# only changes once per day). Keyed by ticker:category.
_EOD_CACHE: dict[str, tuple[float, object]] = {}
_EOD_TTL = 6 * 3600.0  # 6h


def _cached_eod(key: str, producer):
    now = time.time()
    hit = _EOD_CACHE.get(key)
    if hit and now - hit[0] < _EOD_TTL:
        return hit[1]
    value = producer()
    _EOD_CACHE[key] = (now, value)
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
def health(probe: str = Query(None, description="optional ticker to probe the live feed")):
    """Liveness + optional data-feed probe. `?probe=QQQ` fetches a real chain
    and reports whether the vendor/plan returns usable options data (contracts,
    IV & OI coverage), so you can tell at a glance if the source is healthy and
    whether it looks real-time or delayed."""
    out = {
        "ok": True,
        "vendor": pdata.vendor_name(),
        "greeks_source": "vendor" if _use_vendor_greeks() else "black_scholes",
        "ts": time.time(),
    }
    if probe:
        t = probe.upper().strip()
        try:
            chain = pdata.option_chain(t, max_expiries=2)
            spot = pdata.spot(t)
            rep = dataquality.assess_chain(chain, spot=spot)
            # crude freshness read: does the chain carry live quotes?
            has_quotes = bool(
                chain is not None and len(chain)
                and (("bid" in chain.columns and chain["bid"].notna().any())
                     or ("last" in chain.columns and chain["last"].notna().any()))
            )
            out["probe"] = {
                "ticker": t, "spot": _clean(spot),
                "feed": "ok" if rep["ok"] else "degraded",
                "has_live_quotes": has_quotes,
                **rep,
            }
        except Exception as e:
            out["probe"] = {"ticker": t, "feed": "error", "error": str(e)}
    return out


def _strike_step(strikes) -> float:
    s = pd.Series(pd.unique(pd.Series(strikes).sort_values()))
    d = s.diff().dropna()
    return float(d.median()) if len(d) else 1.0


def _gamma_payload(ticker: str, window: int) -> dict:
    """Core Gamma & Flow computation shared by /analyze and /chart."""
    chain = pdata.option_chain(ticker)
    spot = pdata.spot(ticker)
    ctx = _ctx(spot)
    health = dataquality.assess_chain(chain, spot=spot, asof=ctx.asof)
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
        "greeks_source": "vendor" if ctx.use_vendor_greeks else "black_scholes",
        "health": health,
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


@app.get("/api/flow/{ticker}", dependencies=GATED)
def flow(ticker: str, top: int = Query(15, ge=5, le=40)):
    """Big-trade flow by strike: today's traded $ notional (volume × price ×
    100) per level, call vs put, ranked. vol_oi > 1 flags new, aggressive
    positioning (volume above existing open interest)."""
    ticker = ticker.upper().strip()

    def _compute():
        chain = pdata.option_chain(ticker)
        spot = pdata.spot(ticker)
        df = chain.copy()
        # best per-contract price: quote mid, else day close/last
        bid = pd.to_numeric(df.get("bid"), errors="coerce")
        ask = pd.to_numeric(df.get("ask"), errors="coerce")
        mid = (bid + ask) / 2.0
        price = mid.where(mid > 0).fillna(pd.to_numeric(df.get("last"), errors="coerce"))
        df["price"] = price.fillna(0.0)
        df["vol"] = pd.to_numeric(df.get("volume", 0.0), errors="coerce").fillna(0.0)
        df["notional"] = df["vol"] * df["price"] * 100.0
        is_call = df["type"].str.lower() == "call"
        agg = (df.assign(
                    call_vol=np.where(is_call, df["vol"], 0.0),
                    put_vol=np.where(~is_call, df["vol"], 0.0),
                    call_notional=np.where(is_call, df["notional"], 0.0),
                    put_notional=np.where(~is_call, df["notional"], 0.0),
               ).groupby("strike", as_index=False)
                .agg(call_vol=("call_vol", "sum"), put_vol=("put_vol", "sum"),
                     call_notional=("call_notional", "sum"), put_notional=("put_notional", "sum"),
                     oi=("oi", "sum")))
        agg["total_notional"] = agg["call_notional"] + agg["put_notional"]
        agg["total_vol"] = agg["call_vol"] + agg["put_vol"]
        agg["vol_oi"] = agg["total_vol"] / agg["oi"].replace(0, np.nan)
        ranked = agg.sort_values("total_notional", ascending=False).head(top)
        rows = [{
            "strike": float(r.strike),
            "call_vol": _clean(r.call_vol), "put_vol": _clean(r.put_vol),
            "call_notional": _clean(r.call_notional), "put_notional": _clean(r.put_notional),
            "total_notional": _clean(r.total_notional),
            "oi": _clean(r.oi), "vol_oi": _clean(r.vol_oi),
            "bias": "call" if r.call_notional >= r.put_notional else "put",
        } for r in ranked.itertuples(index=False)]
        return {
            "ticker": ticker, "spot": _clean(spot), "rows": rows,
            "totals": {
                "call_notional": _clean(agg["call_notional"].sum()),
                "put_notional": _clean(agg["put_notional"].sum()),
                "call_vol": _clean(agg["call_vol"].sum()),
                "put_vol": _clean(agg["put_vol"].sum()),
                "total_notional": _clean(agg["total_notional"].sum()),
                "top_strike": float(ranked.iloc[0]["strike"]) if len(ranked) else None,
            },
        }

    try:
        return _cached(f"flow:{ticker}:{top}", _compute)
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
def gex_heatmap(ticker: str, window: int = Query(18, ge=5, le=60),
                exp: int = Query(4, ge=1, le=12)):
    """GEX **and** DEX on a strike × days-to-expiry grid — the exposure heat
    map table. Returns dense matrices `z_gex`/`z_dex` (indexed
    [strike_index][col_index]) plus the strike and DTE-column axes, so the
    frontend can toggle GEX↔DEX without a refetch. `exp` sets how many
    expiries deep the grid goes (the Espectro 3D view asks for more)."""
    ticker = ticker.upper().strip()

    def _compute():
        chain = pdata.option_chain(ticker, max_expiries=exp)
        spot = pdata.spot(ticker)
        asof = pd.Timestamp.now("UTC").tz_localize(None).normalize()
        ctx = _ctx(spot, asof)

        gex_grid = exposures.gex_by_strike_expiry(chain, ctx)
        dex_grid = exposures.dex_by_strike_expiry(chain, ctx)
        step = _strike_step(gex_grid["strike"])
        lo, hi = spot - window * step, spot + window * step

        def _pivot(grid, col):
            g = grid[(grid["strike"] >= lo) & (grid["strike"] <= hi)]
            wide = g.pivot(index="strike", columns="expiry", values=col).sort_index()
            return wide.reindex(sorted(wide.columns), axis=1)

        wide_g = _pivot(gex_grid, "gex")
        wide_d = _pivot(dex_grid, "dex")
        # align both matrices on the same strike/expiry axes
        strikes_idx = wide_g.index.union(wide_d.index).sort_values()
        cols_idx = wide_g.columns.union(wide_d.columns).sort_values()
        wide_g = wide_g.reindex(index=strikes_idx, columns=cols_idx)
        wide_d = wide_d.reindex(index=strikes_idx, columns=cols_idx)

        strikes = [float(s) for s in strikes_idx]
        expiries = [pd.Timestamp(c).strftime("%Y-%m-%d") for c in cols_idx]
        dte = [int(max((pd.Timestamp(c) - asof).days, 0)) for c in cols_idx]
        z_gex = [[_clean(v) for v in row] for row in wide_g.to_numpy()]
        z_dex = [[_clean(v) for v in row] for row in wide_d.to_numpy()]
        return {
            "ticker": ticker, "spot": _clean(spot),
            "strikes": strikes, "expiries": expiries, "dte": dte,
            "z_gex": z_gex, "z_dex": z_dex,
            "z": z_gex,  # back-compat alias
        }

    try:
        return _cached(f"gexheat:{ticker}:{window}:{exp}", _compute)
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


def _intraday_bars_fallback(ticker: str, interval: str = "1m", period: str = "1d"):
    """Best-effort intraday bars: try the live vendor, then yfinance (free,
    delayed) for symbols an options-only plan can't price."""
    loaders = [lambda: pdata.intraday_bars(ticker, interval=interval, period=period)]
    if pdata.vendor_name() not in ("yf", "yfinance"):
        from profitlab.data import yfinance as _yf
        loaders.append(lambda: _yf.intraday_bars(ticker, interval=interval, period=period))
    for loader in loaders:
        try:
            df = loader()
            if df is not None and len(df):
                return df
        except Exception:
            continue
    return None


def _session_bars(ticker: str, start_min: int = 8 * 60, end_min: int = 15 * 60,
                  interval: str = "1m", period: str = "1d"):
    """Latest trading session's intraday bars, restricted to the regular
    window (default 08:00–15:00). Both the Net Drift and Volatility Drift views
    are intraday, so this keeps them to one clean session (no overnight /
    extended-hours tail, no multi-day zig-zag). `interval` lets the Replay view
    pick a coarser bar (e.g. 5m) while the drift views keep the 1m default."""
    bars = _intraday_bars_fallback(ticker, interval=interval, period=period)
    if bars is None or not len(bars):
        return None
    bars = bars.dropna(subset=["close"]).copy()
    ts = pd.to_datetime(bars["ts"])
    bars = bars[ts.dt.normalize() == ts.dt.normalize().max()]   # latest day only
    ts = pd.to_datetime(bars["ts"])
    mins = ts.dt.hour * 60 + ts.dt.minute
    bars = bars[(mins >= start_min) & (mins <= end_min)]
    return bars.sort_values("ts").reset_index(drop=True)


# Minutes per bar, for sizing the history window of _history_bars.
_IV_MIN = {"1m": 1, "2m": 2, "3m": 3, "5m": 5, "15m": 15, "30m": 30,
           "60m": 60, "1h": 60}


def _history_bars(ticker: str, interval: str = "5m", min_bars: int = 1000,
                  start_min: int = 8 * 60, end_min: int = 15 * 60):
    """Multi-day intraday bars for the GexBot chart: at least `min_bars`
    regular-hours candles. Unlike `_session_bars` (latest day only, for the
    intraday drift views), this reaches back enough calendar days to gather the
    requested count, keeps the same regular-hours window so sessions stay clean,
    and returns the most recent `min_bars` bars. Lightweight Charts spaces bars
    by index, so the overnight gaps between sessions render seamlessly."""
    im = _IV_MIN.get(interval, 5)
    per_day = max(1, (end_min - start_min) // im)             # ~84 bars/day @5m
    trading_days = -(-min_bars // per_day)                    # ceil division
    cal_days = int(trading_days / 5 * 7) + 7                  # weekends + holidays
    # Smallest recognised period string covering the calendar span we need.
    period = next((p for p, d in (("5d", 7), ("1mo", 35), ("3mo", 95),
                                   ("6mo", 185), ("1y", 400), ("2y", 760))
                   if d >= cal_days), "5y")
    bars = _intraday_bars_fallback(ticker, interval=interval, period=period)
    if bars is None or not len(bars):
        return None
    bars = bars.dropna(subset=["close"]).copy()
    ts = pd.to_datetime(bars["ts"])
    mins = ts.dt.hour * 60 + ts.dt.minute
    bars = bars[(mins >= start_min) & (mins <= end_min)]
    bars = bars.sort_values("ts").reset_index(drop=True)
    if len(bars) > min_bars:
        bars = bars.iloc[-min_bars:].reset_index(drop=True)
    return bars


@app.get("/api/net_drift/{ticker}", dependencies=GATED)
def net_drift(ticker: str):
    """Intraday cumulative premium drift. Two series accrue across the
    session — traded call premium (converging on the day's total call $
    notional) and put premium (converging on the put $ notional, drawn
    negative) — with the underlying price overlaid on a second axis. Call
    premium accrues on up / high-volume bars, put premium on down bars, so
    the curves track where money actually moved during the day."""
    ticker = ticker.upper().strip()

    def _compute():
        chain = pdata.option_chain(ticker)
        spot = pdata.spot(ticker)

        # Day call / put $ notional from the chain (traded vol × price × 100).
        df = chain.copy()
        bid = pd.to_numeric(df.get("bid"), errors="coerce")
        ask = pd.to_numeric(df.get("ask"), errors="coerce")
        mid = (bid + ask) / 2.0
        price = mid.where(mid > 0).fillna(pd.to_numeric(df.get("last"), errors="coerce"))
        vol = pd.to_numeric(df.get("volume", 0.0), errors="coerce").fillna(0.0)
        notional = vol * price.fillna(0.0) * 100.0
        is_call = df["type"].str.lower() == "call"
        call_tot = float(notional[is_call].sum())
        put_tot = float(notional[~is_call].sum())

        bars = _session_bars(ticker)   # latest session, 08:00–15:00 only
        if bars is None or not len(bars):
            raise RuntimeError("Sin barras intradía para este símbolo/plan.")
        close = bars["close"].to_numpy(dtype=float)
        volb = pd.to_numeric(bars.get("volume", 1.0), errors="coerce").fillna(0.0).to_numpy(dtype=float)
        n = len(close)

        rets = np.diff(close, prepend=close[0])
        sd = float(np.std(rets)) or 1.0
        up = 0.5 + 0.5 * np.tanh(rets / (sd * 1.2))   # ≈1 on up bars, ≈0 on down
        dn = 1.0 - up
        wv = volb if volb.sum() > 0 else np.ones(n)
        cw, pw = wv * up, wv * dn
        cw = cw / cw.sum() if cw.sum() > 0 else np.ones(n) / n
        pw = pw / pw.sum() if pw.sum() > 0 else np.ones(n) / n
        call_drift = call_tot * np.cumsum(cw)
        put_drift = -put_tot * np.cumsum(pw)

        t = [pd.Timestamp(x).strftime("%H:%M") for x in bars["ts"]]
        return {
            "ticker": ticker, "spot": _clean(spot), "t": t,
            "call_drift": [_clean(v) for v in call_drift],
            "put_drift": [_clean(v) for v in put_drift],
            "price": [_clean(v) for v in close],
            "totals": {
                "call_drift": _clean(call_tot),
                "put_drift": _clean(-put_tot),
                "last": _clean(close[-1]),
            },
        }

    try:
        return _cached(f"drift:{ticker}", _compute)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/api/volume_profile/{ticker}", dependencies=GATED)
def volume_profile(ticker: str, bins: int = Query(48, ge=10, le=160)):
    """Volume Profile (volumen por precio) de la última sesión intradía
    (08:00–15:00). Reparte el volumen de cada barra entre los niveles de precio
    que abarcó y devuelve el histograma + POC / VAH / VAL, junto con las velas
    para dibujar precio y perfil en el mismo gráfico (TradingView)."""
    ticker = ticker.upper().strip()

    def _compute():
        bars = _session_bars(ticker)
        if bars is None or not len(bars):
            raise RuntimeError("Sin barras intradía para este símbolo/plan.")
        vol = pd.to_numeric(bars.get("volume", 0.0), errors="coerce").fillna(0.0)
        vp = vpmod.compute(
            bars["high"].to_numpy(dtype=float),
            bars["low"].to_numpy(dtype=float),
            bars["close"].to_numpy(dtype=float),
            vol.to_numpy(dtype=float),
            bins=bins,
        )
        vp["ticker"] = ticker
        vp["spot"] = _clean(pdata.spot(ticker))
        # Velas con timestamp UNIX (segundos) — lo que Lightweight Charts espera
        # para intradía.
        vp["candles"] = [
            {
                "time": int(pd.Timestamp(r.ts).timestamp()),
                "open": _clean(r.open), "high": _clean(r.high),
                "low": _clean(r.low), "close": _clean(r.close),
            }
            for r in bars.itertuples()
        ]
        return vp

    try:
        return _cached(f"vp:{ticker}:{bins}", _compute)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/api/levels_chart/{ticker}", dependencies=GATED)
def levels_chart(ticker: str, window: int = Query(24, ge=5, le=60)):
    """Velas intradía (08:00–15:00) + niveles gamma/delta (call wall, put wall,
    gamma flip, delta wall, major neg delta, max pain) para dibujarlos como
    líneas horizontales sobre el gráfico (TradingView). Se refresca con el
    auto-refresh del dashboard → niveles "en vivo"."""
    ticker = ticker.upper().strip()

    def _compute():
        payload = _gamma_payload(ticker, window)
        bars = _session_bars(ticker)
        candles = []
        if bars is not None and len(bars):
            candles = [
                {
                    "time": int(pd.Timestamp(r.ts).timestamp()),
                    "open": _clean(r.open), "high": _clean(r.high),
                    "low": _clean(r.low), "close": _clean(r.close),
                }
                for r in bars.itertuples()
            ]
        return {
            "ticker": ticker,
            "spot": payload.get("spot"),
            "levels": payload.get("levels", {}),
            "regime": payload.get("regime", {}),
            "candles": candles,
        }

    try:
        return _cached(f"levels_chart:{ticker}:{window}", _compute)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


# ── GexBot Classic integration ───────────────────────────────────────────────
@app.get("/api/gexbot/whoami", dependencies=GATED)
def gexbot_whoami():
    """Verify the GexBot API key and show the account/plan it belongs to."""
    out = {"configured": gexbotmod.is_configured()}
    if not out["configured"]:
        out["ok"] = False
        out["detail"] = "GEXBOT_API_KEY no configurada en el backend."
        return out
    try:
        out["ok"] = True
        out["whoami"] = gexbotmod.whoami()
    except Exception as e:
        out["ok"] = False
        out["detail"] = str(e)
    return out


def _gexbot_mc_rows(mcd):
    """Normalize the maxchange payload into [{window, strike, value}] for the
    1/5/10/15/30-minute lookbacks (plus 'ahora')."""
    if not isinstance(mcd, dict):
        return []
    order = [("current", "ahora"), ("one", "1m"), ("five", "5m"),
             ("ten", "10m"), ("fifteen", "15m"), ("thirty", "30m")]
    rows = []
    for key, label in order:
        pair = mcd.get(key)
        if isinstance(pair, (list, tuple)) and len(pair) >= 2:
            rows.append({"window": label, "strike": _clean(pair[0]),
                         "value": _clean(pair[1])})
    return rows


@app.get("/api/gexbot/{ticker}", dependencies=GATED)
def gexbot_chart(ticker: str, category: str = Query("full"),
                 interval: str = Query("5m"),
                 bars: int = Query(1000, ge=100, le=5000)):
    """GexBot Classic data for the Chart view (candles + A + C).

    Candles — real intraday price bars from our price feed (latest session),
    so the chart shows price with GexBot's levels overlaid (GexBot classic
    layout). GexBot's API serves no OHLC, only `spot`.
    A — per-strike net GEX profile (OI and Vol) + key levels (zero gamma,
    major +/-), spot, net GEX and the max-change table.
    C — the per-strike `priors` matrix (1/5/10/15/30-minute lookback GEX,
    vol-based) for the build/drain column."""
    ticker = ticker.upper().strip()

    def _compute():
        snap = gexbotmod.classic(ticker, category)
        try:
            mc = gexbotmod.maxchange(ticker, category)
        except Exception:
            mc = None

        # Real price candles from our feed — GexBot serves no OHLC. We pull a
        # multi-day history (≥ `bars` candles) so the chart has depth, not just
        # today's session.
        candles = []
        try:
            px = _history_bars(ticker, interval=interval, min_bars=bars)
            if px is not None and len(px):
                candles = [
                    {
                        "time": int(pd.Timestamp(r.ts).timestamp()),
                        "open": _clean(r.open), "high": _clean(r.high),
                        "low": _clean(r.low), "close": _clean(r.close),
                    }
                    for r in px.itertuples()
                ]
        except Exception:
            candles = []

        rows = snap["strikes"]
        strikes = [float(r["strike"]) for r in rows]
        gex_oi = [_clean(r["gex_oi"]) for r in rows]
        gex_vol = [_clean(r["gex_vol"]) for r in rows]
        # priors aligned with strikes; pad/truncate to 5 windows (1/5/10/15/30m)
        priors = []
        for r in rows:
            p = list(r.get("priors") or [])
            p = (p + [0.0] * 5)[:5]
            priors.append([_clean(v) for v in p])

        return {
            "ticker": ticker,
            "source": "gexbot",
            "category": snap.get("category"),
            "interval": interval,
            "candles": candles,
            "timestamp": snap.get("timestamp"),
            "spot": _clean(snap.get("spot")),
            "min_dte": snap.get("min_dte"),
            "sec_min_dte": snap.get("sec_min_dte"),
            "zero_gamma": _clean(snap.get("zero_gamma")),
            "major_pos_oi": _clean(snap.get("major_pos_oi")),
            "major_pos_vol": _clean(snap.get("major_pos_vol")),
            "major_neg_oi": _clean(snap.get("major_neg_oi")),
            "major_neg_vol": _clean(snap.get("major_neg_vol")),
            "net_gex_oi": _clean(snap.get("net_gex_oi")),
            "net_gex_vol": _clean(snap.get("net_gex_vol")),
            "delta_risk_reversal": _clean(snap.get("delta_risk_reversal")),
            "strikes": strikes,
            "gex_oi": gex_oi,
            "gex_vol": gex_vol,
            "priors": priors,                   # [[1m,5m,10m,15m,30m], …] vol-based
            "prior_windows": list(gexbotmod.PRIOR_WINDOWS),
            "maxchange_rows": _gexbot_mc_rows(mc),
        }

    try:
        return _cached(f"gexbot:{ticker}:{category}:{interval}:{bars}", _compute)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/api/gexbot/replay/{ticker}", dependencies=GATED)
def gexbot_replay(ticker: str,
                  category: str = Query("full"),
                  points: int = Query(600, ge=50, le=2000)):
    """Replay/backtest series (B) for the latest end-of-day recording.

    GexBot's hist/eod gives the full intraday series of classic snapshots for
    the last trading day. We downsample to ~`points` and return spot + the
    real evolving levels (zero gamma, major +/-, net GEX) over the session, so
    the Replay page can play the day back with price against GexBot's own
    levels. Cached ~6h (the EOD day changes only once per day)."""
    ticker = ticker.upper().strip()

    def _compute():
        ser = gexbotmod.hist_eod_series(ticker, category, target_points=points)
        pts = [
            {
                "t": p.get("t"),
                "spot": _clean(p.get("spot")),
                "zero_gamma": _clean(p.get("zero_gamma")),
                "major_pos_oi": _clean(p.get("major_pos_oi")),
                "major_neg_oi": _clean(p.get("major_neg_oi")),
                "major_pos_vol": _clean(p.get("major_pos_vol")),
                "major_neg_vol": _clean(p.get("major_neg_vol")),
                "net_gex_oi": _clean(p.get("net_gex_oi")),
                "net_gex_vol": _clean(p.get("net_gex_vol")),
            }
            for p in ser.get("points", [])
        ]
        return {
            "ticker": ticker,
            "source": "gexbot",
            "category": ser.get("category"),
            "date": ser.get("date"),
            "count_raw": ser.get("count_raw"),
            "points": pts,
        }

    try:
        return _cached_eod(f"gexbot_eod:{ticker}:{category}:{points}", _compute)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/api/volatility_drift/{ticker}", dependencies=GATED)
def volatility_drift(ticker: str, window: int = Query(20, ge=5, le=60)):
    """Volatility Drift (INTRADAY, 08:00–15:00 session): realized vol (ARV =
    annualized rolling realized volatility from minute returns), the current
    ATM implied-vol level, and the underlying price on one time axis. Shows
    whether the stock is actually moving more/less than options price in."""
    ticker = ticker.upper().strip()

    def _compute():
        bars = _session_bars(ticker)   # latest session, 08:00–15:00
        if bars is None or len(bars) < window + 2:
            raise RuntimeError("Sin barras intradía suficientes para la volatilidad.")
        close = bars["close"].to_numpy(dtype=float)
        s = pd.Series(close)
        logret = np.log(s / s.shift(1))
        # annualize minute-bar vol: 252 trading days × 390 regular-session mins
        ann = np.sqrt(252 * 390)
        arv = (logret.rolling(window).std(ddof=1) * ann * 100.0).to_numpy()

        iv_atm = None
        try:
            chain = pdata.option_chain(ticker)
            spot = pdata.spot(ticker)
            iv_atm = _atm_iv(chain, spot) * 100.0
        except Exception:
            iv_atm = None

        t = [pd.Timestamp(x).strftime("%H:%M") for x in bars["ts"]]
        return {
            "ticker": ticker,
            "window": window,
            "t": t,
            "price": [_clean(v) for v in close],
            "arv": [_clean(v) for v in arv],
            "iv": _clean(iv_atm),
        }

    try:
        return _cached(f"voldrift_ts:{ticker}:{window}", _compute)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/api/vol_drift/{ticker}", dependencies=GATED)
def vol_drift(ticker: str):
    """ATM / call / put implied-vol term structure by expiry (DTE) plus the
    put-call skew — the Volatility (term structure) view."""
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
