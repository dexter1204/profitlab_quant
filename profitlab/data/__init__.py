"""Market-data dispatcher.

Chooses the vendor implementation based on the `PROFITLAB_VENDOR` env
var (default `yfinance`). Every backend exports the same four
functions with the same normalized schema:

    spot(ticker)                          -> float
    price_history(ticker, period, ...)    -> pd.Series (indexed by date)
    intraday_bars(ticker, interval, ...)  -> pd.DataFrame [ts, open, high,
                                                           low, close, volume]
    option_chain(ticker, ...)             -> pd.DataFrame [strike, expiry,
                                                           type, oi, iv, bid,
                                                           ask, last]

Switch vendors by setting env vars before launching Streamlit:

    # yfinance (default — retail delayed, no key needed)
    setx PROFITLAB_VENDOR yfinance

    # polygon.io direct
    setx PROFITLAB_VENDOR polygon
    setx POLYGON_API_KEY  pk_live_xxxx

    # polygon.io via api.market gateway
    setx PROFITLAB_VENDOR   polygon
    setx POLYGON_API_KEY    <your api.market key>
    setx POLYGON_BASE_URL   https://api.market/api/v1/service/polygon.io/polygon
"""

from __future__ import annotations

import os


def _vendor_module():
    name = os.environ.get("PROFITLAB_VENDOR", "yfinance").lower()
    if name in ("yf", "yfinance"):
        from . import yfinance as mod
    elif name in ("polygon", "polygon.io", "api.market"):
        from . import polygon as mod
    else:
        raise ValueError(
            f"Unknown PROFITLAB_VENDOR={name!r}. "
            "Set it to 'yfinance' or 'polygon'."
        )
    return mod


def vendor_name() -> str:
    return os.environ.get("PROFITLAB_VENDOR", "yfinance").lower()


def spot(ticker: str) -> float:
    return _vendor_module().spot(ticker)


def price_history(ticker, period="1y", interval="1d"):
    return _vendor_module().price_history(ticker, period=period, interval=interval)


def intraday_bars(ticker, interval="1m", period="1d"):
    return _vendor_module().intraday_bars(ticker, interval=interval, period=period)


def option_chain(ticker, expiries=None, max_expiries=4):
    return _vendor_module().option_chain(
        ticker, expiries=expiries, max_expiries=max_expiries
    )
