"""Market-data loaders backed by yfinance.

Replace this module with your own vendor adapter for production — the rest
of the library only depends on the schema documented in `exposures`.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd


def _yf():
    import yfinance as yf  # imported lazily so the library works without it
    return yf


def price_history(ticker: str, period: str = "1y", interval: str = "1d") -> pd.Series:
    yf = _yf()
    df = yf.Ticker(ticker).history(period=period, interval=interval, auto_adjust=True)
    if df.empty:
        raise RuntimeError(f"No price history for {ticker!r}")
    return df["Close"].rename(ticker)


def spot(ticker: str) -> float:
    return float(price_history(ticker, period="5d").iloc[-1])


def intraday_bars(ticker: str, interval: str = "1m", period: str = "1d") -> pd.DataFrame:
    """Fetch OHLCV bars via yfinance. Returns [ts, open, high, low, close, volume]."""
    yf = _yf()
    df = yf.Ticker(ticker).history(period=period, interval=interval, auto_adjust=True)
    if df.empty:
        raise RuntimeError(f"No intraday bars for {ticker!r}")
    out = pd.DataFrame({
        "ts": pd.to_datetime(df.index).tz_localize(None) if df.index.tz else pd.to_datetime(df.index),
        "open": df["Open"].astype(float).values,
        "high": df["High"].astype(float).values,
        "low": df["Low"].astype(float).values,
        "close": df["Close"].astype(float).values,
        "volume": df["Volume"].astype(float).values,
    })
    return out


def option_chain(
    ticker: str,
    expiries: Optional[list[str]] = None,
    max_expiries: int = 4,
) -> pd.DataFrame:
    """Return a normalized chain DataFrame across `max_expiries` nearest expiries."""
    yf = _yf()
    tk = yf.Ticker(ticker)
    available = list(tk.options)
    if not available:
        raise RuntimeError(f"No options listed for {ticker!r}")
    chosen = expiries or available[:max_expiries]
    frames = []
    for exp in chosen:
        try:
            c = tk.option_chain(exp)
        except Exception:  # pragma: no cover - vendor flakiness
            continue
        for kind, part in (("call", c.calls), ("put", c.puts)):
            df = part.copy()
            df["type"] = kind
            df["expiry"] = pd.Timestamp(exp)
            frames.append(df)
    if not frames:
        raise RuntimeError(f"Empty option chain for {ticker!r}")
    raw = pd.concat(frames, ignore_index=True)
    out = pd.DataFrame(
        {
            "strike": raw["strike"].astype(float),
            "expiry": pd.to_datetime(raw["expiry"]),
            "type": raw["type"].astype(str),
            "oi": raw.get("openInterest", 0).fillna(0).astype(float),
            "iv": raw.get("impliedVolatility", np.nan).astype(float),
            "bid": raw.get("bid", np.nan).astype(float),
            "ask": raw.get("ask", np.nan).astype(float),
            "last": raw.get("lastPrice", np.nan).astype(float),
        }
    )
    # IVs from yfinance can be zero or absurd; clip to a reasonable band.
    out.loc[(out["iv"] <= 0.01) | (out["iv"] > 5.0), "iv"] = np.nan
    out["iv"] = out["iv"].fillna(out["iv"].median())
    return out
