"""Portfolio beta exposure against a market benchmark.

`beta` is the OLS slope of asset log-returns on benchmark log-returns over a
rolling window (default 63 sessions ≈ 3 months). Beta exposure combines that
with position size:

    beta_dollars_i     = beta_i * price_i * shares_i
    beta_adj_delta_i   = beta_i * delta_shares_i         # for option positions
    portfolio_beta     = sum(beta_dollars_i) / sum(price_i * shares_i)

`positions` is a list of dicts: {ticker, shares, delta_shares?}. `delta_shares`
defaults to `shares` (spot exposure) and lets you pass in option net-delta in
share terms — 100 * contracts * option_delta.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Optional

import numpy as np
import pandas as pd


def rolling_beta(asset: pd.Series, benchmark: pd.Series, window: int = 63) -> pd.Series:
    a = np.log(asset.astype(float)).diff()
    b = np.log(benchmark.astype(float)).diff()
    aligned = pd.concat([a, b], axis=1, keys=["a", "b"]).dropna()
    cov = aligned["a"].rolling(window).cov(aligned["b"])
    var = aligned["b"].rolling(window).var()
    return (cov / var).rename("beta")


def beta_point(asset: pd.Series, benchmark: pd.Series, window: int = 63) -> float:
    b = rolling_beta(asset, benchmark, window).dropna()
    if b.empty:
        return float("nan")
    return float(b.iloc[-1])


@dataclass
class PositionExposure:
    ticker: str
    shares: float
    delta_shares: float
    price: float
    beta: float
    notional: float
    beta_dollars: float
    beta_adj_delta_dollars: float


@dataclass
class PortfolioExposure:
    positions: list[PositionExposure]
    gross_notional: float
    net_notional: float
    beta_dollars: float
    beta_adj_delta_dollars: float
    portfolio_beta: float

    def as_frame(self) -> pd.DataFrame:
        return pd.DataFrame([p.__dict__ for p in self.positions])


def portfolio_beta_exposure(
    positions: Iterable[Mapping],
    prices: Mapping[str, pd.Series],
    benchmark: str = "SPY",
    window: int = 63,
) -> PortfolioExposure:
    """Compute per-position and aggregate beta exposure.

    `prices` maps ticker → close-price series. It must include the benchmark
    and every position's ticker. Beta is the trailing `window`-session OLS
    slope of each asset on the benchmark; a benchmark row has beta=1 by
    construction.
    """
    if benchmark not in prices:
        raise KeyError(f"Missing benchmark price series: {benchmark!r}")
    bench = prices[benchmark]
    rows: list[PositionExposure] = []
    for p in positions:
        ticker = p["ticker"]
        if ticker not in prices:
            raise KeyError(f"Missing price series for position: {ticker!r}")
        s = prices[ticker]
        price = float(s.iloc[-1])
        shares = float(p["shares"])
        delta_shares = float(p.get("delta_shares", shares))
        b = 1.0 if ticker == benchmark else beta_point(s, bench, window)
        notional = price * shares
        rows.append(
            PositionExposure(
                ticker=ticker,
                shares=shares,
                delta_shares=delta_shares,
                price=price,
                beta=b,
                notional=notional,
                beta_dollars=b * notional,
                beta_adj_delta_dollars=b * price * delta_shares,
            )
        )
    gross = sum(abs(r.notional) for r in rows)
    net = sum(r.notional for r in rows)
    beta_dollars = sum(r.beta_dollars for r in rows)
    beta_delta = sum(r.beta_adj_delta_dollars for r in rows)
    port_beta = beta_dollars / net if net else float("nan")
    return PortfolioExposure(
        positions=rows,
        gross_notional=gross,
        net_notional=net,
        beta_dollars=beta_dollars,
        beta_adj_delta_dollars=beta_delta,
        portfolio_beta=port_beta,
    )
