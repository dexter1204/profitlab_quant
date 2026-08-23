"""Dealer exposures (GEX / DEX / VEX / vanna / charm) from an option chain.

Sign convention: dealers are assumed short customer calls and long customer
puts. This is the same convention used by SpotGamma / MenthorQ and yields a
positive-GEX "long gamma" regime near ATM when call open interest dominates.

The chain schema (a pandas DataFrame) has these columns:

    strike : float          strike price
    expiry : pd.Timestamp   expiration
    type   : {"call","put"} option type
    oi     : float          open interest (contracts)
    iv     : float          implied vol (decimal, e.g. 0.22)
    bid, ask, last : float  optional, ignored by exposures
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import greeks

CONTRACT_MULT = 100.0  # US equity options


@dataclass
class ChainContext:
    spot: float
    asof: pd.Timestamp
    r: float = 0.045  # continuously-compounded risk-free
    q: float = 0.0    # continuously-compounded dividend yield


def _time_to_expiry(expiries: pd.Series, asof: pd.Timestamp) -> np.ndarray:
    days = (pd.to_datetime(expiries) - asof).dt.total_seconds() / 86400.0
    return np.maximum(days.to_numpy(), 1.0) / 365.0


def _dealer_sign(kind: pd.Series) -> np.ndarray:
    """+1 for calls (dealer short call), -1 for puts (dealer long put)."""
    return np.where(kind.str.lower() == "call", 1.0, -1.0)


def _prep(chain: pd.DataFrame, ctx: ChainContext):
    t = _time_to_expiry(chain["expiry"], ctx.asof)
    kind = chain["type"].str.lower().to_numpy()
    strike = chain["strike"].to_numpy(dtype=float)
    iv = chain["iv"].to_numpy(dtype=float)
    oi = chain["oi"].to_numpy(dtype=float)
    is_call = kind == "call"
    return t, is_call, strike, iv, oi


def gex_per_contract(chain: pd.DataFrame, ctx: ChainContext) -> np.ndarray:
    """GEX per contract in dollars per 1% move in spot.

    GEX = gamma * multiplier * spot^2 * 0.01, signed by dealer position.
    """
    t, is_call, strike, iv, _ = _prep(chain, ctx)
    g = greeks.gamma(ctx.spot, strike, t, ctx.r, iv, ctx.q)
    sign = np.where(is_call, 1.0, -1.0)
    return sign * g * CONTRACT_MULT * ctx.spot * ctx.spot * 0.01


def dex_per_contract(chain: pd.DataFrame, ctx: ChainContext) -> np.ndarray:
    """DEX per contract in dollar-delta (delta * multiplier * spot)."""
    t, is_call, strike, iv, _ = _prep(chain, ctx)
    d_call = greeks.delta(ctx.spot, strike, t, ctx.r, iv, ctx.q, "call")
    d_put = greeks.delta(ctx.spot, strike, t, ctx.r, iv, ctx.q, "put")
    d = np.where(is_call, d_call, d_put)
    # Dealer short call → -delta_call exposure; dealer long put → +delta_put.
    sign = np.where(is_call, -1.0, 1.0)
    return sign * d * CONTRACT_MULT * ctx.spot


def _by_strike(chain: pd.DataFrame, values: np.ndarray) -> pd.DataFrame:
    df = pd.DataFrame(
        {
            "strike": chain["strike"].to_numpy(dtype=float),
            "value": values * chain["oi"].to_numpy(dtype=float),
        }
    )
    return df.groupby("strike", as_index=False)["value"].sum().sort_values("strike")


def gex_by_strike(chain: pd.DataFrame, ctx: ChainContext) -> pd.DataFrame:
    return _by_strike(chain, gex_per_contract(chain, ctx)).rename(columns={"value": "gex"})


def dex_by_strike(chain: pd.DataFrame, ctx: ChainContext) -> pd.DataFrame:
    return _by_strike(chain, dex_per_contract(chain, ctx)).rename(columns={"value": "dex"})


def _by_strike_expiry(chain: pd.DataFrame, values: np.ndarray) -> pd.DataFrame:
    df = pd.DataFrame(
        {
            "strike": chain["strike"].to_numpy(dtype=float),
            "expiry": pd.to_datetime(chain["expiry"]),
            "value": values * chain["oi"].to_numpy(dtype=float),
        }
    )
    return (
        df.groupby(["strike", "expiry"], as_index=False)["value"].sum()
        .sort_values(["expiry", "strike"])
    )


def gex_by_strike_expiry(chain: pd.DataFrame, ctx: ChainContext) -> pd.DataFrame:
    """Long-form GEX with strike × expiry granularity (feeds the heat map)."""
    return _by_strike_expiry(chain, gex_per_contract(chain, ctx)).rename(columns={"value": "gex"})


def dex_by_strike_expiry(chain: pd.DataFrame, ctx: ChainContext) -> pd.DataFrame:
    return _by_strike_expiry(chain, dex_per_contract(chain, ctx)).rename(columns={"value": "dex"})


def vanna_by_strike(chain: pd.DataFrame, ctx: ChainContext) -> pd.DataFrame:
    t, is_call, strike, iv, _ = _prep(chain, ctx)
    v = greeks.vanna(ctx.spot, strike, t, ctx.r, iv, ctx.q)
    sign = np.where(is_call, -1.0, 1.0)
    values = sign * v * CONTRACT_MULT * ctx.spot
    return _by_strike(chain, values).rename(columns={"value": "vanna"})


def charm_by_strike(chain: pd.DataFrame, ctx: ChainContext) -> pd.DataFrame:
    t, is_call, strike, iv, _ = _prep(chain, ctx)
    c_call = greeks.charm(ctx.spot, strike, t, ctx.r, iv, ctx.q, "call")
    c_put = greeks.charm(ctx.spot, strike, t, ctx.r, iv, ctx.q, "put")
    c = np.where(is_call, c_call, c_put)
    sign = np.where(is_call, -1.0, 1.0)
    values = sign * c * CONTRACT_MULT * ctx.spot / 365.0  # per calendar day
    return _by_strike(chain, values).rename(columns={"value": "charm"})


def totals(chain: pd.DataFrame, ctx: ChainContext) -> dict:
    return {
        "gex": float(gex_by_strike(chain, ctx)["gex"].sum()),
        "dex": float(dex_by_strike(chain, ctx)["dex"].sum()),
        "vanna": float(vanna_by_strike(chain, ctx)["vanna"].sum()),
        "charm": float(charm_by_strike(chain, ctx)["charm"].sum()),
    }
