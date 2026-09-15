"""yfinance-backed market-data loader.

Free and retail-delayed. Fine for prototyping; not for production. Every
function returns the schema documented in `profitlab.data.__init__`.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd


def _yf():
    import yfinance as yf
    return yf


def price_history(ticker: str, period: str = "1y", interval: str = "1d") -> pd.Series:
    yf = _yf()
    df = yf.Ticker(ticker).history(period=period, interval=interval, auto_adjust=True)
    if df.empty:
        raise RuntimeError(f"No price history for {ticker!r}")
    return df["Close"].rename(ticker)


def price_history_batch(tickers: list[str], period: str = "1y") -> dict[str, pd.Series]:
    """Fetch many tickers in one request. ~5-10× faster than looping
    price_history when we need N series (portfolio beta, market
    heatmap). Silently drops tickers yfinance can't serve (e.g. NQ)."""
    yf = _yf()
    if not tickers:
        return {}
    df = yf.download(
        " ".join(tickers), period=period, interval="1d",
        group_by="ticker", auto_adjust=True, progress=False, threads=True,
    )
    out: dict[str, pd.Series] = {}
    for tk in tickers:
        try:
            if len(tickers) == 1:
                series = df["Close"].dropna()
            else:
                series = df[tk]["Close"].dropna()
            if not series.empty:
                out[tk] = series.rename(tk)
        except (KeyError, TypeError):
            continue
    return out


def spot(ticker: str) -> float:
    return float(price_history(ticker, period="5d").iloc[-1])


def intraday_bars(ticker: str, interval: str = "1m", period: str = "1d") -> pd.DataFrame:
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
        except Exception:
            continue
        for kind, part in (("call", c.calls), ("put", c.puts)):
            df = part.copy()
            df["type"] = kind
            df["expiry"] = pd.Timestamp(exp)
            frames.append(df)
    if not frames:
        raise RuntimeError(f"Empty option chain for {ticker!r}")
    raw = pd.concat(frames, ignore_index=True)
    out = pd.DataFrame({
        "strike": raw["strike"].astype(float),
        "expiry": pd.to_datetime(raw["expiry"]),
        "type": raw["type"].astype(str),
        "oi": raw.get("openInterest", 0).fillna(0).astype(float),
        "iv": raw.get("impliedVolatility", np.nan).astype(float),
        "bid": raw.get("bid", np.nan).astype(float),
        "ask": raw.get("ask", np.nan).astype(float),
        "last": raw.get("lastPrice", np.nan).astype(float),
    })
    out.loc[(out["iv"] <= 0.01) | (out["iv"] > 5.0), "iv"] = np.nan
    out["iv"] = out["iv"].fillna(out["iv"].median())
    return out
