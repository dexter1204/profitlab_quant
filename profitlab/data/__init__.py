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
import threading
import time


def _vendor_module():
    name = os.environ.get("PROFITLAB_VENDOR", "yfinance").lower()
    if name in ("yf", "yfinance"):
        from . import yfinance as mod
    elif name in ("polygon", "polygon.io"):
        from . import polygon as mod
    elif name in ("polygon_mcp", "polygon-mcp", "api.market", "mcp"):
        from . import polygon_mcp as mod
    elif name in ("demo", "mock", "offline"):
        from . import demo_vendor as mod
    else:
        raise ValueError(
            f"Unknown PROFITLAB_VENDOR={name!r}. "
            "Set it to 'yfinance', 'polygon', 'polygon_mcp' or 'demo'."
        )
    return mod


def vendor_name() -> str:
    return os.environ.get("PROFITLAB_VENDOR", "yfinance").lower()


def spot(ticker: str) -> float:
    return _vendor_module().spot(ticker)


def price_history(ticker, period="1y", interval="1d"):
    return _vendor_module().price_history(ticker, period=period, interval=interval)


def price_history_batch(tickers, period="1y"):
    """Batch loader. Falls back to sequential price_history calls for
    vendors that don't implement it natively."""
    mod = _vendor_module()
    fn = getattr(mod, "price_history_batch", None)
    if fn is not None:
        return fn(tickers, period=period)
    out = {}
    for t in tickers:
        try:
            out[t] = mod.price_history(t, period=period, interval="1d")
        except Exception:
            continue
    return out


def intraday_bars(ticker, interval="1m", period="1d"):
    return _vendor_module().intraday_bars(ticker, interval=interval, period=period)


# ── Shared options-chain cache ───────────────────────────────────────────────
# The dashboard fires several heavy endpoints at once (OI, flow, GEX heatmap,
# delta/vol surfaces, net/vol drift), and each one re-fetches and rebuilds the
# full options chain. On the single Render worker that multiplies both Polygon
# calls and peak memory, which is what OOM-kills the process. A short TTL cache
# with single-flight lets a burst for one ticker fetch the chain ONCE; the rest
# wait briefly and reuse it. Each caller gets a defensive copy, so they may
# mutate their frame freely. Disable with PROFITLAB_CHAIN_TTL=0.
_CHAIN_LOCK = threading.Lock()
_CHAIN_CACHE: dict = {}       # key -> (monotonic_ts, DataFrame)
_CHAIN_FLIGHT: dict = {}      # key -> threading.Lock (one fetch in flight)


def _chain_ttl() -> float:
    try:
        return float(os.environ.get("PROFITLAB_CHAIN_TTL", "90"))
    except ValueError:
        return 90.0


def option_chain(ticker, expiries=None, max_expiries=4):
    mod = _vendor_module()
    ttl = _chain_ttl()
    if ttl <= 0:
        return mod.option_chain(
            ticker, expiries=expiries, max_expiries=max_expiries
        )

    exp_key = tuple(expiries) if expiries else None
    key = (mod.__name__, str(ticker).upper().strip(), exp_key, max_expiries)

    with _CHAIN_LOCK:
        hit = _CHAIN_CACHE.get(key)
        if hit and time.monotonic() - hit[0] < ttl:
            return hit[1].copy()
        flight = _CHAIN_FLIGHT.get(key)
        if flight is None:
            flight = _CHAIN_FLIGHT[key] = threading.Lock()

    # Single-flight: concurrent callers for the same key wait here, then the
    # losers re-check the cache the winner just filled instead of re-fetching.
    with flight:
        with _CHAIN_LOCK:
            hit = _CHAIN_CACHE.get(key)
            if hit and time.monotonic() - hit[0] < ttl:
                return hit[1].copy()
        df = mod.option_chain(
            ticker, expiries=expiries, max_expiries=max_expiries
        )
        with _CHAIN_LOCK:
            _CHAIN_CACHE[key] = (time.monotonic(), df)
    return df.copy()
