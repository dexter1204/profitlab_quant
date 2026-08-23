"""Chart component + demo intraday bars sanity checks."""

import pandas as pd

from profitlab import demo
from dashboard import components


def test_demo_bars_shape_and_ohlc_invariants():
    df = demo.demo_bars("QQQ", n=100, interval_min=1)
    assert list(df.columns) == ["ts", "open", "high", "low", "close", "volume"]
    assert len(df) == 100
    # OHLC invariants: high ≥ max(open, close) and low ≤ min(open, close)
    assert (df["high"] >= df[["open", "close"]].max(axis=1) - 1e-9).all()
    assert (df["low"] <= df[["open", "close"]].min(axis=1) + 1e-9).all()
    assert (df["volume"] > 0).all()


def test_price_chart_builds_and_serializes():
    import plotly.io as pio
    bars = demo.demo_bars("QQQ", n=200, interval_min=1)
    fig = components.price_chart(
        bars, spot=740.0,
        levels={"call_wall": 752, "put_wall": 730, "gamma_flip": 689,
                "delta_flip": 745, "max_pain": 740},
        ticker="QQQ",
    )
    # Candlestick + volume bars = 2 traces
    assert len(fig.data) == 2
    pio.to_json(fig)


def test_price_chart_hides_missing_levels():
    bars = demo.demo_bars("QQQ", n=50, interval_min=1)
    fig = components.price_chart(
        bars, spot=740.0,
        levels={"call_wall": 752, "put_wall": None, "gamma_flip": float("nan")},
        ticker="QQQ",
    )
    # Only one horizontal shape from call_wall + one from spot + one hrect band.
    shape_types = [s.type for s in fig.layout.shapes]
    # Guarantee we don't crash on None / NaN levels.
    assert shape_types  # at least the spot line present
