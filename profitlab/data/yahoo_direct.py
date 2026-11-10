"""Direct Yahoo Finance intraday loader (no yfinance dependency).

Calls Yahoo's public v8 chart endpoint with browser-like headers. This is a
resilient fallback for hosts where the ``yfinance`` *library* returns empty
DataFrames — Yahoo periodically drifts its API (breaking the pinned yfinance
version) or rate-limits datacenter IPs, which is why intraday bars can vanish
in production (Render) while they still load from a laptop.

It returns the same schema as the other loaders in ``profitlab.data``:
    DataFrame [ts, open, high, low, close, volume]
``ts`` is the exchange-local wall-clock time (naive), matching the yfinance
loader, so downstream ``%H:%M`` formatting shows market time.
"""

from __future__ import annotations

import pandas as pd
import requests

from .yfinance import _sym  # reuse the display-ticker → Yahoo-symbol map

_HOSTS = ("https://query1.finance.yahoo.com", "https://query2.finance.yahoo.com")

# A real browser UA is the single most important thing: Yahoo serves the chart
# JSON to browsers but 429/403s bare clients (which is how yfinance looks once
# its UA handling breaks).
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,text/plain,*/*",
}


def intraday_bars(ticker: str, interval: str = "1m", period: str = "1d") -> pd.DataFrame:
    sym = _sym(ticker)
    params = {
        "interval": interval,
        "range": period,
        "includePrePost": "false",
    }
    last_err: Exception | None = None
    for host in _HOSTS:
        url = f"{host}/v8/finance/chart/{sym}"
        try:
            resp = requests.get(url, params=params, headers=_HEADERS, timeout=15)
        except requests.RequestException as e:  # network / timeout
            last_err = e
            continue
        if resp.status_code != 200:
            last_err = RuntimeError(f"Yahoo HTTP {resp.status_code} for {sym!r}")
            continue
        try:
            payload = resp.json()
        except ValueError as e:
            last_err = e
            continue
        chart = (payload or {}).get("chart") or {}
        if chart.get("error"):
            last_err = RuntimeError(f"Yahoo error for {sym!r}: {chart['error']}")
            continue
        results = chart.get("result") or []
        if not results:
            last_err = RuntimeError(f"Yahoo: empty result for {sym!r}")
            continue
        res = results[0]
        ts = res.get("timestamp") or []
        quote = (((res.get("indicators") or {}).get("quote") or [{}])[0])
        if not ts or not quote:
            last_err = RuntimeError(f"Yahoo: no bars for {sym!r}")
            continue

        # Yahoo timestamps are epoch-UTC; shift by the exchange offset so the
        # bars read in market wall-clock time (naive), like the yfinance path.
        gmtoffset = int((res.get("meta") or {}).get("gmtoffset") or 0)
        df = pd.DataFrame({
            "ts": pd.to_datetime([int(t) + gmtoffset for t in ts], unit="s"),
            "open": quote.get("open"),
            "high": quote.get("high"),
            "low": quote.get("low"),
            "close": quote.get("close"),
            "volume": quote.get("volume"),
        })
        # Drop the trailing/forming rows Yahoo pads with nulls.
        df = df.dropna(subset=["close"]).reset_index(drop=True)
        if not len(df):
            last_err = RuntimeError(f"Yahoo: all-null bars for {sym!r}")
            continue
        for col in ("open", "high", "low", "close", "volume"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df["volume"] = df["volume"].fillna(0.0)
        return df

    raise RuntimeError(f"No intraday bars for {ticker!r} (Yahoo direct): {last_err}")
