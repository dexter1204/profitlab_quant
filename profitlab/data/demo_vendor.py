"""Deterministic offline "demo" vendor.

Selected with `PROFITLAB_VENDOR=demo`. Serves the synthetic chain / bars /
prices from `profitlab.demo` so the API and dashboard render end-to-end with
no network, no API key and no auth — ideal for local review.
"""

from __future__ import annotations

import pandas as pd

from .. import demo as _demo


def spot(ticker: str) -> float:
    return float(_demo.DEMO_SPOTS.get(ticker.upper(), 100.0))


def option_chain(ticker, expiries=None, max_expiries=4):
    chain = _demo.demo_chain(ticker.upper())
    if max_expiries:
        keep = sorted(chain["expiry"].unique())[: int(max_expiries)]
        chain = chain[chain["expiry"].isin(keep)].reset_index(drop=True)
    return chain


def intraday_bars(ticker, interval="1m", period="1d"):
    minutes = {"1m": 1, "2m": 2, "3m": 3, "5m": 5, "15m": 15,
               "30m": 30, "60m": 60, "1h": 60, "1d": 60 * 24}.get(interval, 5)
    n = 390 if (interval.endswith("m") and minutes <= 15) else 78
    return _demo.demo_bars(ticker.upper(), n=n, interval_min=minutes)


def price_history(ticker, period="1y", interval="1d"):
    prices = _demo.demo_prices()
    s = prices.get(ticker.upper())
    if s is None:
        # synthesize a flat-ish series around the demo spot so callers that
        # need HV history don't crash on an unknown ticker
        dates = pd.bdate_range(
            end=pd.Timestamp.now("UTC").tz_localize(None).normalize(), periods=260
        )
        s = pd.Series(float(_demo.DEMO_SPOTS.get(ticker.upper(), 100.0)),
                      index=dates, name=ticker.upper())
    return s


def price_history_batch(tickers, period="1y"):
    prices = _demo.demo_prices()
    out = {}
    for t in tickers:
        key = t.upper()
        out[t] = prices.get(key, price_history(key, period=period))
    return out
