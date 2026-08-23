"""Beta exposure math — construct a synthetic asset that is exactly 2x a benchmark."""

import numpy as np
import pandas as pd

from profitlab import beta as beta_mod


def _synthetic_prices() -> dict[str, pd.Series]:
    rng = np.random.default_rng(0)
    dates = pd.bdate_range(end="2026-01-01", periods=260)
    market = rng.normal(0, 0.01, len(dates))
    spy = pd.Series(100 * np.exp(np.cumsum(market)), index=dates, name="SPY")
    # HIGHB = 2 * market + small idio → beta ≈ 2.0
    hb = pd.Series(50 * np.exp(np.cumsum(2 * market + rng.normal(0, 0.001, len(dates)))),
                   index=dates, name="HIGHB")
    return {"SPY": spy, "HIGHB": hb}


def test_beta_of_synthetic_2x_asset_near_two():
    prices = _synthetic_prices()
    b = beta_mod.beta_point(prices["HIGHB"], prices["SPY"], window=100)
    assert 1.7 < b < 2.3


def test_portfolio_beta_aggregates():
    prices = _synthetic_prices()
    positions = [
        {"ticker": "SPY", "shares": 100},
        {"ticker": "HIGHB", "shares": 100},
    ]
    port = beta_mod.portfolio_beta_exposure(positions, prices, benchmark="SPY", window=100)
    assert port.gross_notional > 0
    # Portfolio beta should sit between 1 (SPY) and ~2 (HIGHB), weighted by notional.
    assert 1.0 < port.portfolio_beta < 2.2
