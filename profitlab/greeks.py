"""Black-Scholes greeks for European options on a dividend-paying stock.

All functions accept scalars or numpy arrays and are broadcast-safe.
Time `t` is measured in calendar years. Interest rate `r` and dividend
yield `q` are continuously compounded.
"""

from __future__ import annotations

import numpy as np

SQRT_2PI = np.sqrt(2.0 * np.pi)


def _erf(x):
    """Vectorized error function — Abramowitz & Stegun 7.1.26.
    Max abs error ~1.5e-7, which is far below any options-data noise.
    Pure numpy so the project needs no scipy (whose compiled DLLs get
    blocked by Windows Smart App Control on some machines)."""
    x = np.asarray(x, dtype=float)
    sign = np.sign(x)
    ax = np.abs(x)
    t = 1.0 / (1.0 + 0.3275911 * ax)
    poly = ((((1.061405429 * t - 1.453152027) * t + 1.421413741) * t
             - 0.284496736) * t + 0.254829592) * t
    return sign * (1.0 - poly * np.exp(-ax * ax))


class _Norm:
    """Minimal drop-in for scipy.stats.norm — only cdf is needed here."""

    @staticmethod
    def cdf(x):
        return 0.5 * (1.0 + _erf(np.asarray(x, dtype=float) / np.sqrt(2.0)))


norm = _Norm()


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


def price(spot, strike, t, r, sigma, q=0.0, kind="call"):
    """Precio Black-Scholes europeo (con rendimiento continuo q)."""
    d1, d2 = _d1_d2(spot, strike, t, r, sigma, q)
    df_q, df_r = np.exp(-q * t), np.exp(-r * t)
    call = spot * df_q * norm.cdf(d1) - strike * df_r * norm.cdf(d2)
    if kind == "call":
        return call
    return call - spot * df_q + strike * df_r          # paridad put-call


def implied_vol(opt_price, spot, strike, t, r, q=0.0, kind="call",
                lo: float = 0.01, hi: float = 5.0, iters: int = 80):
    """Volatilidad implícita por inversión de Black-Scholes (bisección
    vectorizada; el precio BS es monótono en sigma). Devuelve NaN cuando el
    precio no es coherente (≤ valor intrínseco descontado o ≥ cota superior),
    en vez de forzar un número. `kind` puede ser escalar o array de
    'call'/'put'."""
    p = np.asarray(opt_price, dtype=float)
    S = np.broadcast_to(np.asarray(spot, dtype=float), p.shape)
    K = np.broadcast_to(np.asarray(strike, dtype=float), p.shape)
    T = np.broadcast_to(np.asarray(t, dtype=float), p.shape)
    kinds = np.broadcast_to(np.asarray(kind), p.shape)
    is_call = kinds == "call"
    df_q, df_r = np.exp(-q * T), np.exp(-r * T)
    intrinsic = np.where(is_call, np.maximum(S * df_q - K * df_r, 0.0),
                         np.maximum(K * df_r - S * df_q, 0.0))
    upper = np.where(is_call, S * df_q, K * df_r)
    ok = np.isfinite(p) & (p > intrinsic + 1e-9) & (p < upper) & (T > 0) & (S > 0) & (K > 0)
    a = np.full(p.shape, lo)
    b = np.full(p.shape, hi)
    for _ in range(iters):
        m = 0.5 * (a + b)
        pm = np.where(is_call, price(S, K, T, r, m, q, "call"), price(S, K, T, r, m, q, "put"))
        above = pm > p
        b = np.where(above, m, b)
        a = np.where(above, a, m)
    iv = 0.5 * (a + b)
    # en los extremos del intervalo no hubo solución real
    iv = np.where(ok & (iv > lo * 1.001) & (iv < hi * 0.999), iv, np.nan)
    return iv
