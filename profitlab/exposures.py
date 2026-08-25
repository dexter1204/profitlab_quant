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


def delta_surface(
    ctx: ChainContext,
    strike: float,
    iv: float,
    spot_min: float | None = None,
    spot_max: float | None = None,
    days_max: int = 60,
    n_spot: int = 60,
    n_time: int = 45,
    kind: str = "call",
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Black-Scholes delta grid over (spot, time-to-expiry) at fixed strike and IV.

    Returns (spot_axis, days_axis, delta_grid) with delta_grid shape
    (n_time, n_spot). Delta is dimensionless in [-1, 1]; multiply by
    contract multiplier × spot outside if you want dollar-delta per contract.
    """
    from . import greeks

    spot_min = spot_min if spot_min is not None else ctx.spot * 0.85
    spot_max = spot_max if spot_max is not None else ctx.spot * 1.15
    spot_axis = np.linspace(spot_min, spot_max, n_spot)
    days_axis = np.linspace(1.0, float(days_max), n_time)
    t_axis = days_axis / 365.0

    S, T = np.meshgrid(spot_axis, t_axis)
    grid = greeks.delta(S, strike, T, ctx.r, iv, ctx.q, kind=kind)
    return spot_axis, days_axis, np.asarray(grid, dtype=float)


def oi_by_strike_expiry(chain: pd.DataFrame) -> pd.DataFrame:
    """Long-form OI grid with a `net_oi` (call OI minus put OI) column
    suitable for the OI heat map."""
    df = chain.copy()
    df["expiry"] = pd.to_datetime(df["expiry"])
    signed = df.assign(
        call_oi=np.where(df["type"].str.lower() == "call", df["oi"], 0.0),
        put_oi=np.where(df["type"].str.lower() == "put", df["oi"], 0.0),
    )
    grouped = (
        signed.groupby(["strike", "expiry"], as_index=False)
        [["call_oi", "put_oi"]].sum()
    )
    grouped["net_oi"] = grouped["call_oi"] - grouped["put_oi"]
    grouped["total_oi"] = grouped["call_oi"] + grouped["put_oi"]
    return grouped.sort_values(["expiry", "strike"])


def pct_oi_by_strike_expiry(chain: pd.DataFrame) -> pd.DataFrame:
    """Share of total OI at each strike/expiry cell — for the "% OI" tab."""
    grid = oi_by_strike_expiry(chain).copy()
    total = float(grid["total_oi"].sum()) or 1.0
    grid["pct_total_oi"] = grid["total_oi"] / total
    grid["pct_net_oi"] = grid["net_oi"] / total
    return grid


def iv_by_expiry(chain: pd.DataFrame, spot: float, atm_window: int = 3) -> pd.DataFrame:
    """ATM implied-vol per expiry (median IV over the `atm_window` strikes
    nearest to spot) — powers the VOLATILITY DRIFT term-structure chart."""
    df = chain.copy()
    df["expiry"] = pd.to_datetime(df["expiry"])
    out = []
    for exp, sub in df.groupby("expiry"):
        near = sub.iloc[(sub["strike"] - spot).abs().argsort()].head(atm_window * 2)
        atm_iv = float(np.nanmedian(near["iv"]))
        call_iv = float(np.nanmedian(near.loc[near["type"].str.lower() == "call", "iv"]))
        put_iv = float(np.nanmedian(near.loc[near["type"].str.lower() == "put", "iv"]))
        out.append({
            "expiry": exp, "atm_iv": atm_iv,
            "call_iv": call_iv, "put_iv": put_iv,
            "skew": (put_iv - call_iv) if np.isfinite(put_iv - call_iv) else 0.0,
        })
    df_out = pd.DataFrame(out).sort_values("expiry")
    df_out["dte"] = (df_out["expiry"] - df_out["expiry"].min()).dt.days
    return df_out


def iv_surface(chain: pd.DataFrame, spot: float,
               strike_window: int = 20) -> pd.DataFrame:
    """Wide grid of IV per (strike × expiry) — feeds the 3-D vol surface."""
    df = chain.copy()
    df["expiry"] = pd.to_datetime(df["expiry"])
    strikes = np.sort(df["strike"].unique())
    step = float(np.median(np.diff(strikes))) if len(strikes) > 1 else 1.0
    lo, hi = spot - strike_window * step, spot + strike_window * step
    df = df[(df["strike"] >= lo) & (df["strike"] <= hi)]
    grid = (
        df.groupby(["strike", "expiry"], as_index=False)["iv"].median()
    )
    return grid


def net_drift(chain: pd.DataFrame, ctx: ChainContext,
              spot_pct: float = 0.05, n: int = 61) -> pd.DataFrame:
    """Dealer net-delta drift profile: total dealer delta if spot moved
    from `spot*(1-spot_pct)` to `spot*(1+spot_pct)`. Slope tells you where
    dealer hedging pressure amplifies (short-gamma) or dampens (long-gamma)
    price moves."""
    from . import greeks

    spot_axis = np.linspace(ctx.spot * (1 - spot_pct), ctx.spot * (1 + spot_pct), n)
    t = _time_to_expiry(chain["expiry"], ctx.asof)
    kind = chain["type"].str.lower().to_numpy()
    strike = chain["strike"].to_numpy(dtype=float)
    iv = chain["iv"].to_numpy(dtype=float)
    oi = chain["oi"].to_numpy(dtype=float)
    is_call = kind == "call"

    profile = np.empty(n, dtype=float)
    for i, s in enumerate(spot_axis):
        d_call = greeks.delta(s, strike, t, ctx.r, iv, ctx.q, "call")
        d_put = greeks.delta(s, strike, t, ctx.r, iv, ctx.q, "put")
        d = np.where(is_call, d_call, d_put)
        sign = np.where(is_call, -1.0, 1.0)  # dealer short call / long put
        contract_dollar_delta = sign * d * CONTRACT_MULT * s
        profile[i] = float((contract_dollar_delta * oi).sum())
    return pd.DataFrame({"spot": spot_axis, "net_delta": profile})


def totals(chain: pd.DataFrame, ctx: ChainContext) -> dict:
    return {
        "gex": float(gex_by_strike(chain, ctx)["gex"].sum()),
        "dex": float(dex_by_strike(chain, ctx)["dex"].sum()),
        "vanna": float(vanna_by_strike(chain, ctx)["vanna"].sum()),
        "charm": float(charm_by_strike(chain, ctx)["charm"].sum()),
    }
