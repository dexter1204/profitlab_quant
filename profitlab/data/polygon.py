"""Polygon.io-backed market-data loader.

Works with:
  1. polygon.io direct       → default base URL https://api.polygon.io
  2. api.market gateway      → set POLYGON_BASE_URL to the marketplace URL

Auth is sent both as `apiKey` query param and `Authorization: Bearer <key>`
header. polygon.io accepts either; api.market's gateway keeps whichever
form its listing requires — one of the two always works and the other
is ignored.

Env vars:
    POLYGON_API_KEY       your key (required)
    POLYGON_BASE_URL      override base URL; default https://api.polygon.io
    POLYGON_MAX_STRIKES   cap on returned option contracts per chain
                          (default 500 — Polygon paginates at 250)

Response schema is normalized to match `profitlab.data.__init__`.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd
import requests


DEFAULT_BASE_URL = "https://api.polygon.io"


def _base_url() -> str:
    return os.environ.get("POLYGON_BASE_URL", DEFAULT_BASE_URL).rstrip("/")


def _api_key() -> str:
    key = os.environ.get("POLYGON_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "POLYGON_API_KEY is not set. Set it before launching Streamlit — "
            "e.g. `setx POLYGON_API_KEY <your key>` on Windows, then reopen the shell."
        )
    return key


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "Authorization": f"Bearer {_api_key()}",
        "Accept": "application/json",
        "User-Agent": "profitlab-quant/0.1",
    })
    return s


def _get(path: str, params: Optional[dict] = None) -> dict:
    """GET wrapper: prepends base URL if `path` is relative; always
    sends the API key as `apiKey` param too (some proxies strip
    Authorization). Raises RuntimeError on non-2xx with the vendor's
    error text so it surfaces cleanly in Streamlit."""
    if path.startswith("http"):
        url = path
    else:
        url = f"{_base_url()}{path if path.startswith('/') else '/' + path}"
    params = dict(params or {})
    params.setdefault("apiKey", _api_key())
    r = _session().get(url, params=params, timeout=15)
    if not r.ok:
        raise RuntimeError(f"Polygon {r.status_code} @ {path}: {r.text[:200]}")
    return r.json()


# ── endpoints ──────────────────────────────────────────────────────────────
def spot(ticker: str) -> float:
    """Prev-close snapshot ≈ current spot when market is closed; use the
    unified snapshot when it's open. We try snapshot first, fall back to
    prev-close."""
    ticker = ticker.upper()
    try:
        data = _get(f"/v2/snapshot/locale/us/markets/stocks/tickers/{ticker}")
        t = data.get("ticker", {})
        # Prefer today's minute-level close if we have it, otherwise the day's close.
        px = t.get("min", {}).get("c") or t.get("day", {}).get("c") \
             or t.get("prevDay", {}).get("c")
        if px:
            return float(px)
    except RuntimeError:
        pass
    data = _get(f"/v2/aggs/ticker/{ticker}/prev")
    results = data.get("results") or []
    if not results:
        raise RuntimeError(f"Polygon: no spot for {ticker!r}")
    return float(results[-1]["c"])


def price_history(ticker: str, period: str = "1y", interval: str = "1d") -> pd.Series:
    ticker = ticker.upper()
    span, unit = _parse_period(period)
    end = datetime.utcnow().date()
    start = end - timedelta(days=span)
    mult, timespan = _interval_to_polygon(interval)
    path = (f"/v2/aggs/ticker/{ticker}/range/{mult}/{timespan}/"
            f"{start.isoformat()}/{end.isoformat()}")
    data = _get(path, {"adjusted": "true", "sort": "asc", "limit": 50_000})
    rows = data.get("results") or []
    if not rows:
        raise RuntimeError(f"Polygon: empty history for {ticker!r}")
    ser = pd.Series(
        [float(r["c"]) for r in rows],
        index=pd.to_datetime([r["t"] for r in rows], unit="ms"),
        name=ticker,
    )
    return ser


def intraday_bars(ticker: str, interval: str = "1m", period: str = "1d") -> pd.DataFrame:
    ticker = ticker.upper()
    span, _ = _parse_period(period)
    end = datetime.utcnow().date()
    start = end - timedelta(days=max(span, 1))
    mult, timespan = _interval_to_polygon(interval)
    path = (f"/v2/aggs/ticker/{ticker}/range/{mult}/{timespan}/"
            f"{start.isoformat()}/{end.isoformat()}")
    data = _get(path, {"adjusted": "true", "sort": "asc", "limit": 50_000})
    rows = data.get("results") or []
    if not rows:
        raise RuntimeError(f"Polygon: no intraday bars for {ticker!r}")
    df = pd.DataFrame({
        "ts":     pd.to_datetime([r["t"] for r in rows], unit="ms"),
        "open":   [float(r["o"]) for r in rows],
        "high":   [float(r["h"]) for r in rows],
        "low":    [float(r["l"]) for r in rows],
        "close":  [float(r["c"]) for r in rows],
        "volume": [float(r.get("v", 0)) for r in rows],
    })
    return df


def option_chain(
    ticker: str,
    expiries: Optional[list[str]] = None,
    max_expiries: int = 4,
) -> pd.DataFrame:
    """Fetch the current options snapshot; paginated via `next_url`."""
    ticker = ticker.upper()
    max_contracts = int(os.environ.get("POLYGON_MAX_STRIKES", "500"))
    rows: list[dict] = []
    path = f"/v3/snapshot/options/{ticker}"
    params: dict = {"limit": 250}
    if expiries:
        # Filter server-side to reduce pagination hops.
        params["expiration_date"] = ",".join(expiries)

    seen_urls: set[str] = set()
    while True:
        data = _get(path, params if not path.startswith("http") else None)
        for opt in data.get("results", []):
            det = opt.get("details", {})
            greeks = opt.get("greeks") or {}
            last_q = opt.get("last_quote") or {}
            day = opt.get("day") or {}
            strike = det.get("strike_price")
            exp = det.get("expiration_date")
            kind = det.get("contract_type")
            if strike is None or exp is None or kind not in ("call", "put"):
                continue
            rows.append({
                "strike": float(strike),
                "expiry": pd.Timestamp(exp),
                "type": kind,
                "oi": float(opt.get("open_interest") or 0.0),
                "iv": float(opt.get("implied_volatility") or np.nan),
                "delta": float(greeks.get("delta") or np.nan),
                "gamma": float(greeks.get("gamma") or np.nan),
                "bid": float(last_q.get("bid") or np.nan),
                "ask": float(last_q.get("ask") or np.nan),
                "last": float(day.get("close") or np.nan),
            })
        if len(rows) >= max_contracts:
            break
        nxt = data.get("next_url")
        if not nxt or nxt in seen_urls:
            break
        seen_urls.add(nxt)
        path = nxt
        params = None

    if not rows:
        raise RuntimeError(f"Polygon: empty options snapshot for {ticker!r}")

    df = pd.DataFrame(rows)

    # If caller asked for a specific number of expiries, trim to the nearest N.
    if not expiries and max_expiries:
        keep = (
            df[["expiry"]].drop_duplicates().sort_values("expiry")
              .head(max_expiries)["expiry"].tolist()
        )
        df = df[df["expiry"].isin(keep)]

    # Cleanup: clip nonsense IVs and forward-fill from median (same as yfinance path).
    df.loc[(df["iv"] <= 0.01) | (df["iv"] > 5.0), "iv"] = np.nan
    if df["iv"].isna().all():
        df["iv"] = 0.22
    else:
        df["iv"] = df["iv"].fillna(df["iv"].median())
    return df.reset_index(drop=True)


# ── helpers ────────────────────────────────────────────────────────────────
_INTERVAL_MAP = {
    "1m": (1, "minute"), "2m": (2, "minute"), "3m": (3, "minute"),
    "5m": (5, "minute"), "15m": (15, "minute"), "30m": (30, "minute"),
    "60m": (60, "minute"), "1h": (1, "hour"), "1d": (1, "day"), "1wk": (1, "week"),
}


def _interval_to_polygon(interval: str) -> tuple[int, str]:
    if interval not in _INTERVAL_MAP:
        raise ValueError(f"Unsupported interval: {interval!r}")
    return _INTERVAL_MAP[interval]


def _parse_period(period: str) -> tuple[int, str]:
    """Convert yfinance-style period strings to (days, unit) roughly."""
    m = {
        "1d": (2, "d"), "5d": (7, "d"), "1mo": (35, "d"),
        "3mo": (95, "d"), "6mo": (185, "d"), "1y": (400, "d"),
        "2y": (760, "d"), "5y": (1830, "d"), "10y": (3650, "d"),
        "ytd": (400, "d"), "max": (7300, "d"),
    }
    return m.get(period, (400, "d"))
