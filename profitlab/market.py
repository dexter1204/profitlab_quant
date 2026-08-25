"""Market universe + daily-move loader for the Market Heat Map.

The heat-map expects a DataFrame with these columns:

    ticker : str        symbol
    sector : str        parent group in the treemap
    price  : float      last close
    pct    : float      day's percent change (e.g. -0.028 for -2.8%)
    weight : float      cell size (market cap in $B, or a proxy)

`demo_heatmap()` returns a deterministic mock universe matching the
reference screenshot. `live_heatmap()` batches yfinance calls with the
same sector mapping to avoid a per-ticker round trip.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


# ── sector map ─────────────────────────────────────────────────────────────
UNIVERSE: list[tuple[str, str, float]] = [
    # (ticker, sector, weight_hint_in_$B)
    # Technology
    ("AAPL", "Technology", 3400.0),
    ("MSFT", "Technology", 3100.0),
    ("NVDA", "Technology", 3300.0),
    ("AMD",  "Technology",  260.0),
    ("PLTR", "Technology",  180.0),
    ("MSTR", "Technology",   90.0),
    # Communication Services
    ("META", "Communication Services", 1400.0),
    ("GOOG", "Communication Services", 2000.0),
    ("GOOGL","Communication Services", 2000.0),
    ("NFLX", "Communication Services",  310.0),
    # Consumer Cyclical
    ("AMZN", "Consumer Cyclical", 2100.0),
    ("TSLA", "Consumer Cyclical",  820.0),
    # Broad Market ETFs
    ("SPY",  "Broad Market ETFs",  600.0),
    ("QQQ",  "Broad Market ETFs",  350.0),
    ("IWM",  "Broad Market ETFs",   80.0),
    # Indexes
    ("SPX",  "Indexes",             500.0),
    ("NDX",  "Indexes",             250.0),
    ("RUT",  "Indexes",              80.0),
    ("VIX",  "Indexes",              40.0),
    # Macro & Sector ETFs
    ("GLD",  "Macro & Sector ETFs", 100.0),
    ("SLV",  "Macro & Sector ETFs",  15.0),
    ("XLE",  "Macro & Sector ETFs",  40.0),
    ("XLF",  "Macro & Sector ETFs",  45.0),
    ("TLT",  "Macro & Sector ETFs",  55.0),
    # Financial Services
    ("COIN", "Financial Services",  80.0),
    ("HOOD", "Financial Services",  40.0),
    ("SOFI", "Financial Services",  15.0),
]

TICKERS = [t for t, _, _ in UNIVERSE]


# Deterministic reference prices for the demo view.
_DEMO_PRICES = {
    "AAPL": 218.0, "MSFT": 485.0, "NVDA": 140.0, "AMD": 175.0,
    "PLTR": 145.0, "MSTR": 380.0,
    "META": 638.0, "GOOG": 196.0, "GOOGL": 195.0, "NFLX": 1040.0,
    "AMZN": 225.0, "TSLA": 350.0,
    "SPY":  585.0, "QQQ": 748.0, "IWM": 238.0,
    "SPX":  5850.0, "NDX": 21000.0, "RUT": 2250.0, "VIX": 18.0,
    "GLD":  310.0, "SLV": 32.0, "XLE": 92.0, "XLF": 52.0, "TLT": 98.0,
    "COIN": 318.0, "HOOD": 44.0, "SOFI": 12.5,
}


def demo_heatmap(seed: int = 20260823) -> pd.DataFrame:
    """A deterministic universe with plausible day-changes for offline demos."""
    rng = np.random.default_rng(seed)
    rows = []
    for tk, sector, cap in UNIVERSE:
        # Modest daily moves; a bit of sector correlation so it doesn't look random.
        base = rng.normal(0, 0.022)
        sector_bias = {"Indexes": 0.005, "Financial Services": -0.010,
                       "Macro & Sector ETFs": -0.008}.get(sector, 0.0)
        pct = float(np.clip(base + sector_bias, -0.06, 0.06))
        rows.append({
            "ticker": tk,
            "sector": sector,
            "price": _DEMO_PRICES.get(tk, 100.0),
            "pct": pct,
            "weight": cap,
        })
    return pd.DataFrame(rows)


def live_heatmap(
    tickers: list[str] | None = None,
    period: str = "5d",
) -> pd.DataFrame:
    """Fetch last close + previous close per ticker via whatever vendor
    the dispatcher picks (yfinance or polygon). Builds the heat-map frame."""
    from . import data as pdata  # dispatcher

    ticks = tickers or TICKERS
    sectors = {t: s for t, s, _ in UNIVERSE}
    weights = {t: w for t, _, w in UNIVERSE}
    rows = []
    for tk in ticks:
        try:
            hist = pdata.price_history(tk, period=period, interval="1d").dropna()
            if len(hist) < 2:
                continue
            last, prev = float(hist.iloc[-1]), float(hist.iloc[-2])
            pct = (last / prev) - 1.0
        except Exception:
            continue
        rows.append({
            "ticker": tk,
            "sector": sectors.get(tk, "Other"),
            "price": last,
            "pct": pct,
            "weight": weights.get(tk, last),
        })
    return pd.DataFrame(rows)


@dataclass
class HeatmapSummary:
    n_symbols: int
    n_up: int
    n_down: int
    breadth_pct: float   # pct of names green
    best: tuple[str, float]
    worst: tuple[str, float]


def summarize(df: pd.DataFrame) -> HeatmapSummary:
    if df.empty:
        return HeatmapSummary(0, 0, 0, 0.0, ("—", 0.0), ("—", 0.0))
    up = int((df["pct"] > 0).sum())
    down = int((df["pct"] < 0).sum())
    best_row = df.loc[df["pct"].idxmax()]
    worst_row = df.loc[df["pct"].idxmin()]
    return HeatmapSummary(
        n_symbols=len(df),
        n_up=up,
        n_down=down,
        breadth_pct=up / len(df) if len(df) else 0.0,
        best=(str(best_row["ticker"]), float(best_row["pct"])),
        worst=(str(worst_row["ticker"]), float(worst_row["pct"])),
    )
