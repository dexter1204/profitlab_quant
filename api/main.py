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

import contextvars
import os
import sys
import time
from dataclasses import dataclass, field
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
from profitlab import instruments  # noqa: E402

from .aula import require_access  # noqa: E402  — access via the Aula Virtual

# Versión de la metodología de cálculo. Se devuelve en `meta` de cada respuesta
# para que web/iOS/Android puedan verificar que usan el mismo motor.
CALC_VERSION = "2026.11.26-pro15b"
MARKET_TZ = "America/New_York"
RTH_START, RTH_END = 9 * 60 + 30, 16 * 60   # sesión regular NYSE/Nasdaq (min. del día, hora NY)


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


# ── Metadatos por respuesta ──────────────────────────────────────────────────
# Cada cálculo registra aquí qué datos usó (instrumento, subyacente, spot y su
# origen, barras y su frescura, calidad de la cadena, partes estimadas).
# `_cached` lo adjunta como `meta` a la respuesta: así ningún indicador puede
# devolver un gráfico sin decir de dónde salió y cuándo.
_META: contextvars.ContextVar = contextvars.ContextVar("pl_meta", default=None)


def _meta() -> dict:
    m = _META.get()
    return m if m is not None else {}


def _meta_warn(msg: str) -> None:
    m = _META.get()
    if m is not None and msg not in m.setdefault("warnings", []):
        m["warnings"].append(msg)


def _meta_estimated(what: str, method: str) -> None:
    m = _META.get()
    if m is not None:
        m.setdefault("estimated", {})[what] = method


def _cached(key: str, producer):
    now = time.time()
    hit = _CACHE.get(key)
    if hit and now - hit[0] < _TTL:
        value = hit[1]
        if isinstance(value, dict) and isinstance(value.get("meta"), dict):
            value["meta"]["cache_age_s"] = round(now - hit[0], 1)
        return value
    token = _META.set({
        "calc_version": CALC_VERSION,
        "vendor": pdata.vendor_name(),
        "generated_at": pd.Timestamp.now(tz="UTC").isoformat(),
        "timezone": MARKET_TZ,
        # Plan Options Starter de Massive: cotizaciones con 15 min de retraso.
        "data_delay_min": int(os.environ.get("PROFITLAB_DATA_DELAY_MIN", "15")),
        "warnings": [],
        "estimated": {},
    })
    try:
        value = producer()
        if isinstance(value, dict):
            meta = dict(_META.get() or {})
            meta["cache_age_s"] = 0.0
            # El estado de datos se resume en una sola palabra para la UI.
            meta["status"] = ("degraded" if meta.get("warnings") else "ok")
            value["meta"] = meta
    finally:
        _META.reset(token)
    _CACHE[key] = (now, value)
    return value


# ── Carga de opciones común a todas las vistas ───────────────────────────────
@dataclass
class OptCtx:
    inst: "instruments.Instrument"
    underlying: str          # subyacente cuya cadena se usó de verdad
    chain: pd.DataFrame
    spot: float
    spot_source: str
    quality: dict = field(default_factory=dict)


def _options(symbol: str, max_expiries: int = 4, strike_pct: float | None = None) -> OptCtx:
    """Resuelve el instrumento y carga una cadena VÁLIDA (vencimientos vigentes,
    strikes alrededor del spot, IV presente). Si la del subyacente principal no
    sirve (p. ej. índice sin datos en el plan), prueba el sustituto y lo
    declara en `meta`. Nunca devuelve una cadena vieja o sin IV."""
    inst = instruments.resolve(symbol)
    candidates = [inst.options] + ([inst.fallback] if inst.fallback else [])
    errors = []
    for i, und in enumerate(candidates):
        try:
            si = pdata.spot_info(und)
            spot = float(si["price"])
            chain = pdata.option_chain(und, max_expiries=max_expiries,
                                       spot=spot, strike_pct=strike_pct)
            asof = pd.Timestamp.now("UTC").tz_localize(None).normalize()
            # Spot burdo (strike con más OI o cierre de ayer) → se refina por
            # paridad put-call con la propia cadena cerca del dinero. Así la IV
            # calculada y las griegas no heredan un spot desviado.
            if si.get("source") in ("options_max_oi", "prev_close"):
                ps = ivmod.parity_spot(chain, spot, asof)
                if ps and abs(ps / spot - 1) < 0.15:
                    si = {"price": ps, "source": "options_parity_chain", "estimated": True}
                    spot = ps
            # IV que el proveedor no trae → calculada desde el precio del contrato.
            chain, iv_stats = ivmod.fill_from_quotes(chain, spot, asof)
            q = dataquality.assess_chain(chain, spot=spot)
            if chain.attrs.get("iv_missing"):
                q["ok"] = False
                q["issues"] = q.get("issues", []) + ["La fuente no entrega volatilidad implícita."]
            if not q["ok"]:
                raise RuntimeError("; ".join(q.get("issues") or ["cadena no válida"]))
            m = _META.get()
            if m is not None:
                exps = sorted(pd.to_datetime(chain["expiry"]).dt.strftime("%Y-%m-%d").unique())
                m["instrument"] = inst.to_dict()
                m["options_underlying"] = und
                m["options_fallback_used"] = i > 0
                m["spot"] = _clean(spot)
                m["spot_source"] = si.get("source")
                m["spot_estimated"] = bool(si.get("estimated"))
                m["chain"] = {
                    "contracts": int(len(chain)),
                    "expiries": exps,
                    "iv_coverage": q.get("iv_coverage"),
                    "oi_coverage": q.get("oi_coverage"),
                    "iv_imputed_pct": iv_stats.get("median_pct"),
                    "iv_sources": iv_stats,
                    "severity": q.get("severity"),
                }
                for w in q.get("warnings", []):
                    _meta_warn(w)
                if i > 0:
                    _meta_warn(f"{inst.options} sin datos válidos ({errors[-1]}); se usa {und}.")
                if si.get("estimated"):
                    _meta_warn(f"Spot de {und} estimado desde opciones ({si.get('source')}), "
                               "no es el precio negociado.")
                if inst.proxy:
                    _meta_warn(inst.note)
            return OptCtx(inst, und, chain, spot, si.get("source", ""), q)
        except Exception as e:  # noqa: BLE001 — se reintenta con el sustituto
            errors.append(f"{und}: {e}")
            continue
    raise RuntimeError("Sin datos de opciones válidos para "
                       f"{inst.symbol}: " + " | ".join(errors))


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
        # Diagnóstico sin datos sensibles: qué subyacente se usó, por qué se
        # descartó el principal, origen del spot, fuentes de IV y barras.
        token = _META.set({"warnings": [], "estimated": {}})
        try:
            try:
                bars = _session_bars(t)
                bm = _META.get()
                out["bars"] = {"symbol": bm.get("bars_symbol"), "source": bm.get("bars_source"),
                               "n": 0 if bars is None else int(len(bars)),
                               "session": bm.get("bars_session"), "last": bm.get("bars_last_ts"),
                               "errors": bm.get("bars_errors", [])}
            except Exception as e:  # noqa: BLE001
                out["bars"] = {"error": str(e)[:200]}
            try:
                oc = _options(t, max_expiries=2)
                mm = _META.get()
                out["options"] = {k: mm.get(k) for k in ("options_underlying", "options_fallback_used",
                                                          "spot", "spot_source", "spot_estimated", "chain")}
                out["warnings"] = mm.get("warnings", [])
            except Exception as e:  # noqa: BLE001
                out["options"] = {"error": str(e)[:300]}
        finally:
            _META.reset(token)
        try:
            oc = _options(t, max_expiries=2)
            chain, spot = oc.chain, oc.spot
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
    oc = _options(ticker)
    chain, spot = oc.chain, oc.spot
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
        # options-only Polygon/Massive plan that can't price stock aggregates.
        from profitlab.data import yfinance as _yf
        return _yf.intraday_bars(ticker, interval=interval, period=period)

    def _yd_bars():
        # Last-resort: Yahoo's v8 endpoint directly (no yfinance dependency), so
        # a broken library build doesn't blank the chart. Best-effort.
        from profitlab.data import yahoo_direct as _yd
        return _yd.intraday_bars(ticker, interval=interval, period=period)

    def _compute():
        payload = _gamma_payload(ticker, window)
        bars, source = [], None
        # Velas del MISMO subyacente que los niveles, desde la caché compartida
        # (mejor fuente disponible: Massive si da las de hoy, si no Yahoo).
        und = _meta().get("options_underlying") or ticker
        df = _intraday_bars_fallback(und, interval=interval, period=period)
        if df is not None and len(df):
            bars = _bars_from(_clean_bars(df))
            source = _meta().get("bars_source")
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
        oc = _options(ticker)
        chain, spot = oc.chain, oc.spot
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
        oc = _options(ticker)
        chain, spot = oc.chain, oc.spot
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
        oc = _options(ticker, max_expiries=exp)
        chain, spot = oc.chain, oc.spot
        asof = pd.Timestamp.now("UTC").tz_localize(None).normalize()
        ctx = _ctx(spot, asof)

        gex_grid = exposures.gex_by_strike_expiry(chain, ctx)
        dex_grid = exposures.dex_by_strike_expiry(chain, ctx)
        step = _strike_step(gex_grid["strike"])
        lo, hi = spot - window * step, spot + window * step

        in_win = gex_grid[(gex_grid["strike"] >= lo) & (gex_grid["strike"] <= hi)]
        width = _bucket_width(in_win["strike"])
        if width:
            _meta()["strike_bucket"] = width

        def _pivot(grid, col):
            g = grid[(grid["strike"] >= lo) & (grid["strike"] <= hi)]
            g = _bucket(g, col, width)
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
        oc = _options(ticker)
        chain, spot = oc.chain, oc.spot
        by_exp = exposures.iv_by_expiry(chain, spot)
        iv_atm = float(by_exp["atm_iv"].iloc[0]) if len(by_exp) else float("nan")
        front = iv_atm
        back = float(by_exp["atm_iv"].iloc[-1]) if len(by_exp) else None
        closes = _price_history_fallback(ticker, period="6mo", interval="1d")
        if closes is None or not len(closes):
            raise RuntimeError("Sin histórico diario para este símbolo/plan.")
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


def _atm_iv(chain, spot) -> float | None:
    """IV ATM del primer vencimiento. Si no hay IV real devuelve None (antes
    devolvía un 20 % fijo que se mostraba como si fuera dato)."""
    try:
        by_exp = exposures.iv_by_expiry(chain, spot)
        if len(by_exp):
            v = float(by_exp["atm_iv"].iloc[0])
            if v and v == v and v > 0:  # finite & positive
                return v
    except Exception:
        pass
    return None


def _bucket_width(strikes, max_rows: int = 40) -> float | None:
    """Ancho de tramo "redondo" para que la rejilla tenga ≤ max_rows strikes.
    En índices (SPX, NDX) el open interest se concentra en strikes redondos y
    los intermedios casi no tienen contratos: sin agrupar, la superficie sale
    en dientes de sierra. Agrupar SUMA la exposición de cada tramo (no inventa
    ni suaviza datos). None = no hace falta agrupar."""
    ks = np.sort(np.unique(np.asarray(strikes, dtype=float)))
    if len(ks) <= max_rows:
        return None
    base = _strike_step(ks)
    raw = (ks[-1] - ks[0]) / max_rows
    for m in (1, 2, 2.5, 5, 10, 20, 25, 50, 100, 200, 250, 500):
        w = base * m
        if w >= raw:
            return float(w)
    return float(raw)


def _bucket(grid: pd.DataFrame, col: str, width: float | None) -> pd.DataFrame:
    if not width:
        return grid
    g = grid.copy()
    g["strike"] = np.round(g["strike"] / width) * width
    return g.groupby(["strike", "expiry"], as_index=False)[col].sum()


def _delta_surface_legacy(ticker: str, kind: str):
    """Formato v1 (OBSOLETO): delta teórico Black-Scholes de una opción ATM
    sobre una rejilla spot × días, con la IV ATM real del activo. Solo para
    clientes antiguos; no es exposición."""
    def _compute():
        oc = _options(ticker)
        iv = _atm_iv(oc.chain, oc.spot)
        if iv is None:
            raise RuntimeError("Sin IV ATM real para la superficie teórica.")
        ctx = exposures.ChainContext(spot=oc.spot,
                                     asof=pd.Timestamp.now("UTC").tz_localize(None).normalize())
        spot_axis, days_axis, grid = exposures.delta_surface(ctx, strike=oc.spot, iv=iv,
                                                             days_max=60, kind=kind)
        _meta_warn("Formato obsoleto (delta teórico). Actualiza la app para ver la exposición real.")
        return {
            "ticker": ticker, "spot": _clean(oc.spot), "kind": kind, "iv": _clean(iv),
            "spot_axis": [float(x) for x in spot_axis],
            "days_axis": [float(d) for d in days_axis],
            "z": [[_clean(x) for x in row] for row in grid],
            "deprecated": True,
        }
    try:
        return _cached(f"dsurf_v1:{ticker}:{kind}", _compute)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/api/delta_surface/{ticker}", dependencies=GATED)
def delta_surface(ticker: str,
                  kind: str = Query("net"),
                  exp: int = Query(8, ge=2, le=12),
                  window: int = Query(24, ge=5, le=60),
                  v: int = Query(1, ge=1, le=2)):
    """Delta Surface = EXPOSICIÓN DELTA REAL de los dealers (DEX) por
    strike × vencimiento, construida con el open interest de la cadena.

    Metodología (v2026.11): para cada contrato
        DEX = signo_dealer × delta_BS(spot, K, T, r, IV_contrato) × OI × 100 × spot
    con signo_dealer = −1 en calls (dealer corto call) y +1 en puts (dealer
    largo put), y se suma por (strike, vencimiento). Unidades: USD de delta
    (variación del valor de la cobertura por $1 del subyacente × spot).
    `kind`: net (calls + puts) | call | put.

    Sustituye a la versión anterior, que dibujaba el delta TEÓRICO de una
    opción hipotética ATM sobre una rejilla de precio: por construcción era
    casi idéntica en todos los activos y no usaba open interest."""
    ticker = ticker.upper().strip()
    kind = kind.lower().strip()
    if v < 2:
        # COMPATIBILIDAD: apps ya instaladas (≤ 1.3) piden sin `v` y esperan el
        # formato antiguo (spot_axis/days_axis). Se les sigue sirviendo, marcado
        # como obsoleto, hasta que actualicen. La app nueva pide v=2.
        return _delta_surface_legacy(ticker, kind if kind in ("call", "put") else "call")
    if kind not in ("net", "call", "put"):
        kind = "net"

    def _compute():
        oc = _options(ticker, max_expiries=exp)
        chain, spot = oc.chain, oc.spot
        if kind != "net":
            chain = chain[chain["type"].str.lower() == kind]
        if chain["oi"].fillna(0).sum() <= 0:
            raise RuntimeError("La cadena no trae open interest: no se puede calcular exposición.")
        asof = pd.Timestamp.now("UTC").tz_localize(None).normalize()
        grid = exposures.dex_by_strike_expiry(chain, _ctx(spot, asof))
        step = _strike_step(grid["strike"])
        lo, hi = spot - window * step, spot + window * step
        g = grid[(grid["strike"] >= lo) & (grid["strike"] <= hi)]
        width = _bucket_width(g["strike"])
        g = _bucket(g, "dex", width)
        if width:
            _meta()["strike_bucket"] = width
        wide = g.pivot(index="strike", columns="expiry", values="dex").sort_index()
        wide = wide.reindex(sorted(wide.columns), axis=1)
        if wide.shape[0] < 3 or wide.shape[1] < 1:
            raise RuntimeError("Datos insuficientes para la superficie (pocos strikes/vencimientos).")
        _meta()["method"] = "dealer_dex_by_strike_expiry"
        return {
            "ticker": ticker, "spot": _clean(spot), "kind": kind,
            "unit": "USD delta",
            "strikes": [float(s) for s in wide.index],
            "expiries": [pd.Timestamp(c).strftime("%Y-%m-%d") for c in wide.columns],
            "dte": [int(max((pd.Timestamp(c) - asof).days, 0)) for c in wide.columns],
            "z": [[_clean(v) for v in row] for row in wide.to_numpy()],  # [strike][vencimiento]
            "total_dex": _clean(float(np.nansum(wide.to_numpy()))),
        }

    try:
        return _cached(f"dsurf:{ticker}:{kind}:{exp}:{window}", _compute)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


import threading  # noqa: E402

# ── Barras intradía: caché compartida + mejor fuente + último dato bueno ─────
# Antes cada vista (Volume Profile, drifts, niveles, chart) descargaba sus
# propias barras de Yahoo en cada actualización y por cada usuario: muchas
# peticiones desde la IP de Render → Yahoo la bloqueaba. Ahora una sola
# descarga por (símbolo, intervalo, periodo) cada PROFITLAB_BARS_TTL segundos,
# compartida por todas las vistas y usuarios, con un solo hilo descargando.
_BARS_CACHE: dict = {}          # key -> (time, df, source)
_BARS_GOOD: dict = {}           # key -> (time, df, source)   último dato válido
_BARS_LOCKS: dict = {}
_BARS_GLOBAL = threading.Lock()


def _bars_ttl() -> float:
    return float(os.environ.get("PROFITLAB_BARS_TTL", "60"))


def _expected_session_date():
    """Fecha de la sesión que debería existir ya (hora NY): hoy si es día
    hábil y ya abrió; si no, el día hábil anterior (sin calendario de feriados:
    si no hay datos se usa la fuente más reciente disponible)."""
    now = pd.Timestamp.now(tz=MARKET_TZ).tz_localize(None)
    d = now.normalize()
    if now.weekday() < 5 and now.hour * 60 + now.minute >= RTH_START:
        return d.date()
    d -= pd.Timedelta(days=1)
    while d.weekday() >= 5:
        d -= pd.Timedelta(days=1)
    return d.date()


def _bars_loaders(ticker: str, interval: str, period: str):
    loaders = [("vendor", lambda: pdata.intraday_bars(ticker, interval=interval, period=period))]
    # yfinance library: the maintained free source. It handles Yahoo's
    # cookie/crumb handshake, so it's the right fallback for ETFs / indices an
    # options-only plan can't price (QQQ, SPY, ^SPX…). Keep it pinned recent in
    # requirements.txt — an outdated build (Yahoo API drift) is the usual cause
    # of "Sin barras intradía" in production.
    if pdata.vendor_name() not in ("yf", "yfinance"):
        from profitlab.data import yfinance as _yf
        loaders.append(("yfinance", lambda: _yf.intraday_bars(ticker, interval=interval, period=period)))
    # Last-resort: Yahoo's v8 endpoint directly (no yfinance dependency).
    from profitlab.data import yahoo_direct as _yd
    loaders.append(("yahoo", lambda: _yd.intraday_bars(ticker, interval=interval, period=period)))
    return loaders


def _fetch_best_bars(ticker: str, interval: str, period: str):
    """Prueba las fuentes en orden y se queda con la PRIMERA que tenga la
    sesión esperada; si ninguna la tiene, con la más reciente. Así un plan
    Basic de Massive (velas solo hasta ayer) no tapa a Yahoo con las de hoy."""
    want = _expected_session_date()
    best, best_src, best_last, errors = None, None, None, []
    for name, loader in _bars_loaders(ticker, interval, period):
        try:
            df = loader()
            if df is None or not len(df):
                errors.append(f"{name}: vacío")
                continue
            last = pd.Timestamp(pd.to_datetime(df["ts"]).max())
            if best_last is None or last > best_last:
                best, best_src, best_last = df, name, last
            if last.date() >= want:
                break
            errors.append(f"{name}: última barra {last.date()} (atrasada)")
        except Exception as e:  # noqa: BLE001
            errors.append(f"{name}: {str(e)[:80]}")
    return best, best_src, errors


def _intraday_bars_fallback(ticker: str, interval: str = "1m", period: str = "1d"):
    """Barras intradía (ts en hora de Nueva York) desde la caché compartida.
    Registra en `meta` la fuente, la edad de la caché y si es un dato de
    respaldo (último válido) porque todas las fuentes fallaron."""
    key = (ticker.upper(), interval, period)
    with _BARS_GLOBAL:
        lock = _BARS_LOCKS.setdefault(key, threading.Lock())
    with lock:
        now = time.time()
        hit = _BARS_CACHE.get(key)
        if hit and now - hit[0] < _bars_ttl():
            ts0, df, src, errors = hit[0], hit[1], hit[2], []
        else:
            df, src, errors = _fetch_best_bars(ticker, interval, period)
            ts0 = now
            if df is not None:
                _BARS_CACHE[key] = (now, df, src)
                _BARS_GOOD[key] = (now, df, src)
            elif key in _BARS_GOOD:
                ts0, df, src = _BARS_GOOD[key]
                _meta_warn(f"Todas las fuentes de barras fallaron; se usa el último dato válido "
                           f"de hace {int((now - ts0) / 60)} min.")
    m = _META.get()
    if m is not None:
        if errors:
            m["bars_errors"] = errors
        if df is not None:
            m["bars_source"] = src if src != "vendor" else pdata.vendor_name()
            m["bars_cache_age_s"] = round(time.time() - ts0, 1)
    if df is not None and src in ("yfinance", "yahoo"):
        _meta_warn(f"Barras de {ticker} desde Yahoo ({src}): el plan de Massive no entrega "
                   "las velas de hoy para este instrumento.")
    return None if df is None else df.copy()


def _price_history_fallback(ticker: str, period: str = "6mo", interval: str = "1d"):
    """Best-effort daily closes: the live vendor (Massive) first, then yfinance.
    Massive's options-only plan can't price stock/ETF aggregates, so views that
    need realized-vol history (IV premium) would otherwise 502. yfinance serves
    free daily closes and is the right fallback here."""
    loaders = [lambda: pdata.price_history(ticker, period=period, interval=interval)]
    if pdata.vendor_name() not in ("yf", "yfinance"):
        from profitlab.data import yfinance as _yf
        loaders.append(lambda: _yf.price_history(ticker, period=period, interval=interval))
    for loader in loaders:
        try:
            ser = loader()
            if ser is not None and len(ser):
                return ser
        except Exception:
            continue
    return None


def _clean_bars(bars: pd.DataFrame) -> pd.DataFrame:
    """Validación de barras: sin cierres nulos, sin timestamps duplicados,
    en orden cronológico y sin OHLC incoherente (high < low)."""
    b = bars.dropna(subset=["close"]).copy()
    b["ts"] = pd.to_datetime(b["ts"])
    n0 = len(b)
    b = b.drop_duplicates(subset="ts", keep="last").sort_values("ts")
    if len(b) < n0:
        _meta_warn(f"Se descartaron {n0 - len(b)} barras duplicadas.")
    bad = (b["high"] < b["low"])
    if bad.any():
        _meta_warn(f"Se descartaron {int(bad.sum())} barras con high < low.")
        b = b[~bad]
    return b.reset_index(drop=True)


def _rth(bars: pd.DataFrame, start_min: int = RTH_START, end_min: int = RTH_END) -> pd.DataFrame:
    ts = pd.to_datetime(bars["ts"])
    mins = ts.dt.hour * 60 + ts.dt.minute
    return bars[(mins >= start_min) & (mins < end_min)]


def _check_fresh(bars: pd.DataFrame) -> None:
    """Marca datos congelados: con el mercado abierto, la última barra no debe
    tener más de 20 min de antigüedad."""
    if not len(bars):
        return
    now = pd.Timestamp.now(tz=MARKET_TZ).tz_localize(None)
    last = pd.Timestamp(bars["ts"].iloc[-1])
    m = _META.get()
    if m is not None:
        m["bars_last_ts"] = last.isoformat()
        m["bars_session"] = last.strftime("%Y-%m-%d")
    open_now = now.weekday() < 5 and RTH_START <= now.hour * 60 + now.minute < RTH_END
    if open_now and last.date() == now.date():
        age = (now - last).total_seconds() / 60
        if age > 20:
            _meta_warn(f"Datos desactualizados: la última barra tiene {age:.0f} min con el mercado abierto.")
    elif open_now:
        _meta_warn("Mercado abierto pero sin barras de hoy: se muestra la sesión anterior.")


def _session_bars(ticker: str, start_min: int = RTH_START, end_min: int = RTH_END,
                  interval: str = "1m", period: str = "5d"):
    """Barras de la ÚLTIMA SESIÓN REGULAR (09:30–16:00 hora de Nueva York) del
    símbolo de barras del instrumento (los índices y CFD usan su ETF, que sí
    tiene volumen). Antes la ventana era 08:00–15:00 sobre timestamps en UTC
    (Massive) o en hora local (Yahoo): con Massive se quedaba con el
    premercado y desde las 19:00 de NY la ventana salía vacía."""
    inst = instruments.resolve(ticker)
    sym = inst.bars
    if not sym:
        raise RuntimeError(f"{inst.symbol} no tiene un subyacente con barras/volumen.")
    m = _META.get()
    if m is not None:
        m["instrument"] = m.get("instrument") or inst.to_dict()
        m["bars_symbol"] = sym
        m["bars_interval"] = interval
    if sym != inst.symbol and inst.proxy:
        _meta_warn(inst.note)
    raw = _intraday_bars_fallback(sym, interval=interval, period=period)
    if raw is None or not len(raw):
        return None
    bars = _rth(_clean_bars(raw), start_min, end_min)
    if not len(bars):
        return None
    days = pd.to_datetime(bars["ts"]).dt.normalize()
    bars = bars[days == days.max()].reset_index(drop=True)   # última sesión con datos
    _check_fresh(bars)
    return bars


# Minutes per bar, for sizing the history window of _history_bars.
_IV_MIN = {"1m": 1, "2m": 2, "3m": 3, "5m": 5, "15m": 15, "30m": 30,
           "60m": 60, "1h": 60}


def _history_bars(ticker: str, interval: str = "5m", min_bars: int = 1000,
                  start_min: int = RTH_START, end_min: int = RTH_END):
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
def net_drift(ticker: str, exp: int = Query(12, ge=1, le=20)):
    """Net Drift (metodología ProfitLab, conservada):
      · TOTALES REALES: prima negociada hoy en calls y en puts
            notional = volumen_día × precio_contrato (mid, o último) × 100
        sumada sobre los `exp` vencimientos más cercanos y strikes ±25 % del spot
        (antes: 4 vencimientos y tope de 500 contratos → total infravalorado).
      · CURVA INTRADÍA ESTIMADA: el proveedor no da operaciones de opciones con
        hora, así que el total se reparte por minuto con
            w_call(t) ∝ volumen_barra(t) × (0.5 + 0.5·tanh(r_t / (1.2·σ_r)))
            w_put(t)  ∝ volumen_barra(t) × (1 − ...)
        y se acumula. La forma de la curva es un modelo, no flujo observado;
        el punto final sí es el total real. `meta.estimated` lo declara."""
    ticker = ticker.upper().strip()

    def _compute():
        oc = _options(ticker, max_expiries=exp, strike_pct=0.25)
        chain, spot = oc.chain, oc.spot
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
        if call_tot + put_tot <= 0:
            raise RuntimeError("La cadena no trae volumen negociado hoy (mercado cerrado o "
                               "plan sin volumen de opciones): no hay prima que acumular.")

        bars = _session_bars(ticker)
        if bars is None or not len(bars):
            raise RuntimeError("Sin barras intradía de la sesión regular para este instrumento.")
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
        _meta_estimated("curve", "reparto del total diario por volumen×dirección de cada barra")
        _meta()["method"] = "net_drift_v1_totales_reales_curva_estimada"

        t = [pd.Timestamp(x).strftime("%H:%M") for x in bars["ts"]]
        return {
            "ticker": ticker, "spot": _clean(spot), "t": t,
            "call_drift": [_clean(v) for v in call_drift],
            "put_drift": [_clean(v) for v in put_drift],
            "price": [_clean(v) for v in close],
            "price_symbol": instruments.resolve(ticker).bars,
            "totals": {
                "call_drift": _clean(call_tot),
                "put_drift": _clean(-put_tot),
                "net": _clean(call_tot - put_tot),
                "last": _clean(close[-1]),
            },
        }

    try:
        return _cached(f"drift:{ticker}:{exp}", _compute)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


def _multi_session_bars(ticker: str, sessions: int):
    """Últimas `sessions` sesiones regulares (barras de 1m para 1 sesión, 5m
    para varias) del símbolo con volumen del instrumento."""
    if sessions <= 1:
        return _session_bars(ticker)
    inst = instruments.resolve(ticker)
    if not inst.bars:
        raise RuntimeError(f"{inst.symbol} no tiene un subyacente con volumen.")
    m = _META.get()
    if m is not None:
        m["instrument"] = m.get("instrument") or inst.to_dict()
        m["bars_symbol"] = inst.bars
        m["bars_interval"] = "5m"
    if inst.proxy:
        _meta_warn(inst.note)
    period = "1mo" if sessions <= 15 else "3mo"
    raw = _intraday_bars_fallback(inst.bars, interval="5m", period=period)
    if raw is None or not len(raw):
        return None
    bars = _rth(_clean_bars(raw))
    days = pd.to_datetime(bars["ts"]).dt.normalize()
    keep = sorted(days.unique())[-sessions:]
    bars = bars[days.isin(keep)].reset_index(drop=True)
    _check_fresh(bars)
    return bars


@app.get("/api/volume_profile/{ticker}", dependencies=GATED)
def volume_profile(ticker: str, bins: int = Query(48, ge=10, le=160),
                   sessions: int = Query(1, ge=1, le=30),
                   value_area: float = Query(0.70, ge=0.5, le=0.95)):
    """Volume Profile de las últimas `sessions` sesiones regulares
    (1 = sesión/día, 5 = semana, N = rango personalizado en sesiones).

    Es una ESTIMACIÓN DESDE VELAS OHLCV: el volumen de cada vela se reparte de
    forma uniforme entre los niveles de precio de su rango [low, high]. El
    proveedor no entrega volumen negociado en cada precio (tick a tick), y la
    respuesta lo declara en `meta.estimated`. Devuelve POC, VAH, VAL y nodos
    de alto (HVN) y bajo volumen (LVN). Índices y CFD usan su ETF (los
    índices no tienen volumen)."""
    ticker = ticker.upper().strip()

    def _compute():
        bars = _multi_session_bars(ticker, sessions)
        if bars is None or not len(bars):
            raise RuntimeError("Sin barras intradía de la sesión regular para este instrumento.")
        vol = pd.to_numeric(bars.get("volume", 0.0), errors="coerce").fillna(0.0)
        if float(vol.sum()) <= 0:
            raise RuntimeError("Las barras no traen volumen: no se puede construir el perfil.")
        vp = vpmod.compute(
            bars["high"].to_numpy(dtype=float),
            bars["low"].to_numpy(dtype=float),
            bars["close"].to_numpy(dtype=float),
            vol.to_numpy(dtype=float),
            bins=bins, value_area=value_area,
        )
        vp.update(vpmod.nodes(vp["price"], vp["volume"]))
        vp["ticker"] = ticker
        vp["symbol"] = instruments.resolve(ticker).bars
        vp["sessions"] = sessions
        vp["spot"] = _clean(float(bars["close"].iloc[-1]))
        vp["range_start"] = pd.Timestamp(bars["ts"].iloc[0]).isoformat()
        vp["range_end"] = pd.Timestamp(bars["ts"].iloc[-1]).isoformat()
        _meta_estimated("volume_by_price", "reparto uniforme del volumen de cada vela OHLCV en su rango")
        _meta()["method"] = "volume_profile_ohlcv_v1"
        # Velas con timestamp UNIX: el ts es hora de NY sin zona; Lightweight
        # Charts muestra UTC, así que el eje enseña el reloj del mercado.
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
        return _cached(f"vp:{ticker}:{bins}:{sessions}:{value_area}", _compute)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/api/levels_chart/{ticker}", dependencies=GATED)
def levels_chart(ticker: str, window: int = Query(24, ge=5, le=60)):
    """Velas de la sesión regular + niveles gamma/delta (call wall, put wall,
    gamma flip, delta wall, major neg delta, max pain) como líneas. Las velas
    son del MISMO subyacente cuyas opciones dan los niveles (antes, en índices,
    niveles del índice sobre velas del ETF quedaban fuera de escala)."""
    ticker = ticker.upper().strip()

    def _compute():
        payload = _gamma_payload(ticker, window)
        und = _meta().get("options_underlying") or ticker
        raw = _intraday_bars_fallback(und, interval="1m", period="5d")
        candles = []
        if raw is not None and len(raw):
            bars = _rth(_clean_bars(raw))
            if len(bars):
                days = pd.to_datetime(bars["ts"]).dt.normalize()
                bars = bars[days == days.max()]
                _check_fresh(bars)
                candles = [
                    {
                        "time": int(pd.Timestamp(r.ts).timestamp()),
                        "open": _clean(r.open), "high": _clean(r.high),
                        "low": _clean(r.low), "close": _clean(r.close),
                    }
                    for r in bars.itertuples()
                ]
        if not candles:
            _meta_warn(f"Sin velas intradía de {und}: se muestran solo los niveles.")
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
    """Volatility Drift (metodología ProfitLab, conservada), sesión regular:
        r_t   = ln(C_t / C_{t-1})                      (velas de 1 minuto)
        ARV_t = std_muestral(r_{t-window+1..t}) × √(252 × 390) × 100   [% anual]
    frente a la IV ATM del primer vencimiento (en %). Mide si el subyacente se
    mueve más (ARV > IV) o menos de lo que descuentan las opciones.
    Añadido (no cambia la fórmula): dirección y magnitud del drift = cambio
    del ARV en la última ventana, y diferencia ARV − IV.
    Sin IV real, `iv` = null (antes: 20 % fijo presentado como dato)."""
    ticker = ticker.upper().strip()

    def _compute():
        bars = _session_bars(ticker)
        if bars is None or len(bars) < window + 2:
            n = 0 if bars is None else len(bars)
            raise RuntimeError(f"Datos insuficientes: {n} barras en la sesión y la ventana "
                               f"necesita al menos {window + 2}.")
        close = bars["close"].to_numpy(dtype=float)
        s_ = pd.Series(close)
        logret = np.log(s_ / s_.shift(1))
        ann = np.sqrt(252 * 390)
        arv = (logret.rolling(window).std(ddof=1) * ann * 100.0).to_numpy()
        valid = arv[np.isfinite(arv)]
        if len(valid) < 2 or np.nanmax(valid) == 0:
            raise RuntimeError("El precio no se movió en la sesión: la volatilidad realizada es cero.")

        iv_atm = None
        try:
            oc = _options(ticker)
            v = _atm_iv(oc.chain, oc.spot)
            iv_atm = v * 100.0 if v is not None else None
        except Exception as e:  # noqa: BLE001
            _meta_warn(f"Sin IV implícita: {str(e)[:120]}")
        if iv_atm is None:
            _meta_warn("IV ATM no disponible: solo se muestra la volatilidad realizada.")

        last = float(valid[-1])
        prev = float(valid[-window]) if len(valid) > window else float(valid[0])
        change = last - prev
        direction = "up" if change > 0.5 else ("down" if change < -0.5 else "flat")
        _meta()["method"] = "arv_rolling_1m_v1"

        t = [pd.Timestamp(x).strftime("%H:%M") for x in bars["ts"]]
        return {
            "ticker": ticker,
            "window": window,
            "t": t,
            "price": [_clean(v) for v in close],
            "price_symbol": instruments.resolve(ticker).bars,
            "arv": [_clean(v) for v in arv],
            "iv": _clean(iv_atm),
            "summary": {
                "arv_last": _clean(last),
                "drift_change": _clean(change),       # puntos de vol en la última ventana
                "direction": direction,
                "spread_vs_iv": _clean(last - iv_atm) if iv_atm is not None else None,
                "window_minutes": window,
            },
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
        oc = _options(ticker)
        chain, spot = oc.chain, oc.spot
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
        oc = _options(ticker)
        chain, spot = oc.chain, oc.spot
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
