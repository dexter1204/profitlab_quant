"""Deterministic demo chain — matches the layout in the reference screenshot.

Lets the dashboard render end-to-end without network access.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


DEMO_SPOTS = {
    "QQQ": 740.00,
    "SPY": 615.00,
    "GLD": 245.00,
    "SLV": 34.20,
    "NQ":  20940.0,
    "AAPL": 232.5,
    "TSLA": 268.0,
    "NVDA": 138.5,
}


def _bell(x: np.ndarray, mu: float, sigma: float) -> np.ndarray:
    return np.exp(-0.5 * ((x - mu) / sigma) ** 2)


def demo_chain(ticker: str = "QQQ", asof: pd.Timestamp | None = None) -> pd.DataFrame:
    """A synthetic single-expiry chain with plausible OI and IV skew."""
    spot = DEMO_SPOTS.get(ticker, 100.0)
    step = max(round(spot * 0.003 * 2) / 2, 0.5)
    strikes = np.arange(spot - 30 * step, spot + 30 * step + step, step)
    asof = asof or pd.Timestamp.now("UTC").tz_localize(None).normalize()
    # Daily front-month like a real index-ETF chain (0DTE through 8DTE),
    # weekly further out, then monthlies — gives the strike × expiry grid the
    # column density you see on real vendor dashboards.
    day_offsets = list(range(0, 9)) + [14, 21, 30, 45, 60]
    expiries = [asof + pd.Timedelta(days=d) for d in day_offsets]

    rng = np.random.default_rng(hash(ticker) & 0xFFFFFFFF)
    rows = []
    for exp in expiries:
        t = max((exp - asof).days, 1) / 365.0
        atm_iv = 0.22 + 0.03 * (0.03 / max(t, 0.03))
        for k in strikes:
            skew = 0.08 * max(spot - k, 0) / spot + 0.02 * max(k - spot, 0) / spot
            iv = atm_iv + skew + rng.normal(0, 0.005)
            call_oi = float(1500 * _bell(k, spot + 4 * step, 6 * step) + 200 * rng.random())
            put_oi = float(1800 * _bell(k, spot - 4 * step, 6 * step) + 200 * rng.random())
            rows.append({"strike": float(k), "expiry": exp, "type": "call", "oi": call_oi, "iv": iv})
            rows.append({"strike": float(k), "expiry": exp, "type": "put", "oi": put_oi, "iv": iv})
    df = pd.DataFrame(rows)
    df["bid"] = np.nan
    df["ask"] = np.nan
    df["last"] = np.nan
    return df


def demo_prices() -> dict[str, pd.Series]:
    """Deterministic 1y daily closes for the demo tickers plus SPY benchmark."""
    rng = np.random.default_rng(20250823)
    dates = pd.bdate_range(end=pd.Timestamp.now("UTC").tz_localize(None).normalize(), periods=260)
    market_shocks = rng.normal(0, 0.009, size=len(dates))
    out = {}
    tickers = list(DEMO_SPOTS.keys()) + ["SPY"]
    for tk in tickers:
        beta_factor = {
            "QQQ": 1.10, "SPY": 1.00, "GLD": 0.15, "SLV": 0.30,
            "NQ": 1.10, "AAPL": 1.20, "TSLA": 1.85, "NVDA": 1.60,
        }.get(tk, 1.0)
        idio = rng.normal(0, 0.012, size=len(dates))
        rets = beta_factor * market_shocks + idio
        base = {"QQQ": 660.0, "SPY": 555.0, "GLD": 235.0, "SLV": 30.0, "NQ": 19000,
                "AAPL": 205.0, "TSLA": 220.0, "NVDA": 120.0}.get(tk, 100.0)
        prices = base * np.exp(np.cumsum(rets))
        out[tk] = pd.Series(prices, index=dates, name=tk)
    return out
