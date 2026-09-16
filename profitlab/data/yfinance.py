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


# Display ticker → yfinance symbol. Indices carry a caret; index futures
# use the =F suffix. yfinance only serves options for the ETF proxies,
# not the index symbols themselves — SPX/NDX price loads but their option
# chains come back empty (handled gracefully upstream).
_SYMBOL_MAP = {
    "SPX": "^SPX",
    "NDX": "^NDX",
    "VIX": "^VIX",
    "RUT": "^RUT",
    "NQ":  "NQ=F",
    "ES":  "ES=F",
}

# For index tickers with no listed options on yfinance, fall back to the
# tradable ETF proxy so the options-driven views still work.
_OPTIONS_PROXY = {
    "SPX": "SPY",
    "NDX": "QQQ",
    "NQ":  "QQQ",
    "RUT": "IWM",
}


def _sym(ticker: str) -> str:
    return _SYMBOL_MAP.get(ticker.upper(), ticker)


def price_history(ticker: str, period: str = "1y", interval: str = "1d") -> pd.Series:
    yf = _yf()
    df = yf.Ticker(_sym(ticker)).history(period=period, interval=interval, auto_adjust=True)
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
    # Map display tickers to yfinance symbols, keeping a reverse lookup.
    sym_for = {tk: _sym(tk) for tk in tickers}
    syms = list(sym_for.values())
    df = yf.download(
        " ".join(syms), period=period, interval="1d",
        group_by="ticker", auto_adjust=True, progress=False, threads=True,
    )
    out: dict[str, pd.Series] = {}
    for tk in tickers:
        sym = sym_for[tk]
        try:
            if len(syms) == 1:
                series = df["Close"].dropna()
            else:
                series = df[sym]["Close"].dropna()
            if not series.empty:
                out[tk] = series.rename(tk)
        except (KeyError, TypeError):
            continue
    return out


def spot(ticker: str) -> float:
    return float(price_history(ticker, period="5d").iloc[-1])


def intraday_bars(ticker: str, interval: str = "1m", period: str = "1d") -> pd.DataFrame:
    yf = _yf()
    df = yf.Ticker(_sym(ticker)).history(period=period, interval=interval, auto_adjust=True)
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
    max_expiries: int = 8,
) -> pd.DataFrame:
    yf = _yf()
    # Index tickers (SPX/NDX) have no options on yfinance — use the ETF
    # proxy (SPY/QQQ) and scale its strikes to the index level by the
    # live index/proxy price ratio (SPX ≈ 10×SPY, NDX ≈ 41×QQQ), so the
    # chain lines up with the index spot the rest of the app shows.
    proxy = _OPTIONS_PROXY.get(ticker.upper())
    strike_scale = 1.0
    if proxy:
        opt_ticker = proxy
        try:
            strike_scale = spot(ticker) / spot(proxy)
        except Exception:
            strike_scale = 1.0
    else:
        opt_ticker = _sym(ticker)

    tk = yf.Ticker(opt_ticker)
    available = list(tk.options)
    if not available:
        raise RuntimeError(
            f"No options listed for {ticker!r} (tried {opt_ticker!r})"
        )
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
        "strike": raw["strike"].astype(float) * strike_scale,
        "expiry": pd.to_datetime(raw["expiry"]),
        "type": raw["type"].astype(str),
        "oi": raw.get("openInterest", 0).fillna(0).astype(float),
        "iv": raw.get("impliedVolatility", np.nan).astype(float),
        "bid": raw.get("bid", np.nan).astype(float),
        "ask": raw.get("ask", np.nan).astype(float),
        "last": raw.get("lastPrice", np.nan).astype(float),
    })
    # Tighter IV clip: yfinance frequently emits IVs near zero at deep-OTM
    # strikes (data holes) which blow up gamma / second-order greeks.
    out.loc[(out["iv"] < 0.05) | (out["iv"] > 3.0), "iv"] = np.nan
    out["iv"] = out["iv"].fillna(out["iv"].median() if out["iv"].notna().any() else 0.22)
    # Drop rows with zero OI — they contribute nothing but noise to sums.
    out = out[out["oi"] > 0].reset_index(drop=True)
    return out
