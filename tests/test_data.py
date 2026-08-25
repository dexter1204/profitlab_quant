"""Vendor dispatcher + polygon adapter sanity checks (no network)."""

import os
from unittest.mock import patch

import pandas as pd
import pytest

from profitlab import data


def test_dispatcher_default_is_yfinance():
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("PROFITLAB_VENDOR", None)
        assert data.vendor_name() == "yfinance"


def test_dispatcher_selects_polygon_when_env_set():
    with patch.dict(os.environ, {"PROFITLAB_VENDOR": "polygon"}):
        assert data.vendor_name() == "polygon"


def test_dispatcher_rejects_unknown_vendor():
    with patch.dict(os.environ, {"PROFITLAB_VENDOR": "bogus"}):
        with pytest.raises(ValueError, match="Unknown PROFITLAB_VENDOR"):
            data.spot("QQQ")


def test_polygon_requires_api_key():
    from profitlab.data import polygon as polygon_mod
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("POLYGON_API_KEY", None)
        with pytest.raises(RuntimeError, match="POLYGON_API_KEY"):
            polygon_mod.spot("QQQ")


def test_polygon_normalizes_option_chain_snapshot():
    """The chain builder must convert Polygon's snapshot response into
    the [strike, expiry, type, oi, iv, bid, ask, last] schema used by
    the rest of the library."""
    from profitlab.data import polygon as polygon_mod

    fake_response = {
        "results": [
            {
                "details": {"strike_price": 740.0, "expiration_date": "2026-09-05",
                            "contract_type": "call"},
                "open_interest": 1200,
                "implied_volatility": 0.245,
                "greeks": {"delta": 0.55, "gamma": 0.012},
                "last_quote": {"bid": 3.10, "ask": 3.30},
                "day": {"close": 3.20},
            },
            {
                "details": {"strike_price": 740.0, "expiration_date": "2026-09-05",
                            "contract_type": "put"},
                "open_interest": 900,
                "implied_volatility": 0.28,
                "greeks": {"delta": -0.44, "gamma": 0.011},
                "last_quote": {"bid": 3.55, "ask": 3.70},
                "day": {"close": 3.62},
            },
        ],
        "next_url": None,
    }
    with patch.dict(os.environ, {"POLYGON_API_KEY": "test_key"}):
        with patch.object(polygon_mod, "_get", return_value=fake_response):
            df = polygon_mod.option_chain("QQQ", max_expiries=1)

    assert {"strike", "expiry", "type", "oi", "iv", "bid", "ask", "last"}.issubset(df.columns)
    assert len(df) == 2
    assert set(df["type"]) == {"call", "put"}
    assert df["strike"].iloc[0] == 740.0
    assert df["iv"].between(0.2, 0.3).all()


def test_polygon_intraday_bars_normalizes_aggs():
    from profitlab.data import polygon as polygon_mod

    fake = {
        "results": [
            {"t": 1_700_000_000_000, "o": 740.1, "h": 740.5, "l": 739.9, "c": 740.2, "v": 12000},
            {"t": 1_700_000_060_000, "o": 740.2, "h": 740.7, "l": 740.0, "c": 740.6, "v": 15000},
        ]
    }
    with patch.dict(os.environ, {"POLYGON_API_KEY": "test_key"}):
        with patch.object(polygon_mod, "_get", return_value=fake):
            df = polygon_mod.intraday_bars("QQQ", interval="1m", period="1d")
    assert list(df.columns) == ["ts", "open", "high", "low", "close", "volume"]
    assert len(df) == 2
    assert df["close"].iloc[-1] == 740.6
