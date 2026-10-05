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

from profitlab import exposures, metrics, regime  # noqa: E402
from profitlab import data as pdata  # noqa: E402

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
    allow_methods=["GET"],
    allow_headers=["*"],
)


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


@app.get("/api/analyze/{ticker}")
def analyze(ticker: str, window: int = Query(20, ge=5, le=60)):
    """Everything the Gamma & Flow view needs for one ticker, as JSON."""
    ticker = ticker.upper().strip()

    def _compute():
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

        # window around spot for the chart
        step = float(gex["strike"].diff().dropna().median()) if len(gex) > 1 else 1.0
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

    try:
        return _cached(f"analyze:{ticker}:{window}", _compute)
    except Exception as e:  # surface vendor errors cleanly to the frontend
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/api/oi/{ticker}")
def oi(ticker: str, window: int = Query(20, ge=5, le=60)):
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
        strikes = tbl.index.to_numpy()
        step = float(pd.Series(strikes).diff().dropna().median()) if len(strikes) > 1 else 1.0
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
