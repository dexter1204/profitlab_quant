"""Black-Scholes greeks for European options on a dividend-paying stock.

All functions accept scalars or numpy arrays and are broadcast-safe.
Time `t` is measured in calendar years. Interest rate `r` and dividend
yield `q` are continuously compounded.
"""

from __future__ import annotations

import numpy as np
from scipy.stats import norm

SQRT_2PI = np.sqrt(2.0 * np.pi)


def _d1_d2(spot, strike, t, r, sigma, q):
    spot = np.asarray(spot, dtype=float)
    strike = np.asarray(strike, dtype=float)
    t = np.asarray(t, dtype=float)
    sigma = np.asarray(sigma, dtype=float)
    # Guard against zero-time / zero-vol degenerate inputs.
    denom = np.where((sigma > 0) & (t > 0), sigma * np.sqrt(t), np.nan)
    d1 = (np.log(spot / strike) + (r - q + 0.5 * sigma * sigma) * t) / denom
    d2 = d1 - denom
    return d1, d2


def delta(spot, strike, t, r, sigma, q=0.0, kind="call"):
    d1, _ = _d1_d2(spot, strike, t, r, sigma, q)
    disc_q = np.exp(-q * np.asarray(t, dtype=float))
    if kind == "call":
        return disc_q * norm.cdf(d1)
    return disc_q * (norm.cdf(d1) - 1.0)


def gamma(spot, strike, t, r, sigma, q=0.0):
    d1, _ = _d1_d2(spot, strike, t, r, sigma, q)
    spot = np.asarray(spot, dtype=float)
    sigma = np.asarray(sigma, dtype=float)
    t = np.asarray(t, dtype=float)
    disc_q = np.exp(-q * t)
    return disc_q * np.exp(-0.5 * d1 * d1) / (SQRT_2PI * spot * sigma * np.sqrt(t))


def vega(spot, strike, t, r, sigma, q=0.0):
    """Vega per 1.0 change in sigma (not per 1 vol point). Divide by 100 for
    the per-point convention."""
    d1, _ = _d1_d2(spot, strike, t, r, sigma, q)
    spot = np.asarray(spot, dtype=float)
    t = np.asarray(t, dtype=float)
    disc_q = np.exp(-q * t)
    return spot * disc_q * np.exp(-0.5 * d1 * d1) / SQRT_2PI * np.sqrt(t)


def theta(spot, strike, t, r, sigma, q=0.0, kind="call"):
    d1, d2 = _d1_d2(spot, strike, t, r, sigma, q)
    spot = np.asarray(spot, dtype=float)
    strike = np.asarray(strike, dtype=float)
    t = np.asarray(t, dtype=float)
    sigma = np.asarray(sigma, dtype=float)
    disc_r = np.exp(-r * t)
    disc_q = np.exp(-q * t)
    pdf = np.exp(-0.5 * d1 * d1) / SQRT_2PI
    term1 = -spot * disc_q * pdf * sigma / (2.0 * np.sqrt(t))
    if kind == "call":
        return term1 - r * strike * disc_r * norm.cdf(d2) + q * spot * disc_q * norm.cdf(d1)
    return term1 + r * strike * disc_r * norm.cdf(-d2) - q * spot * disc_q * norm.cdf(-d1)


def vanna(spot, strike, t, r, sigma, q=0.0):
    """d(delta)/d(sigma) = d(vega)/d(spot). Same for calls and puts."""
    d1, d2 = _d1_d2(spot, strike, t, r, sigma, q)
    sigma = np.asarray(sigma, dtype=float)
    t = np.asarray(t, dtype=float)
    disc_q = np.exp(-q * t)
    pdf = np.exp(-0.5 * d1 * d1) / SQRT_2PI
    return -disc_q * pdf * d2 / sigma


def charm(spot, strike, t, r, sigma, q=0.0, kind="call"):
    """d(delta)/d(t) — the "delta decay". Per year; divide by 365 for daily."""
    d1, d2 = _d1_d2(spot, strike, t, r, sigma, q)
    t = np.asarray(t, dtype=float)
    sigma = np.asarray(sigma, dtype=float)
    disc_q = np.exp(-q * t)
    pdf = np.exp(-0.5 * d1 * d1) / SQRT_2PI
    common = disc_q * pdf * (2.0 * (r - q) * t - d2 * sigma * np.sqrt(t)) / (2.0 * t * sigma * np.sqrt(t))
    if kind == "call":
        return q * disc_q * norm.cdf(d1) - common
    return -q * disc_q * norm.cdf(-d1) - common
