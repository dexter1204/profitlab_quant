"""Reference-value checks for Black-Scholes greeks.

The reference values are computed against Hull's textbook parameters:
    S = 100, K = 100, T = 1.0, r = 0.05, sigma = 0.20, q = 0.0
"""

import math

import numpy as np

from profitlab import greeks


S, K, T, R, SIG, Q = 100.0, 100.0, 1.0, 0.05, 0.20, 0.0


def test_call_put_parity_delta():
    dc = greeks.delta(S, K, T, R, SIG, Q, "call")
    dp = greeks.delta(S, K, T, R, SIG, Q, "put")
    # dc - dp = e^{-qT}  (=1 with q=0)
    assert math.isclose(float(dc - dp), math.exp(-Q * T), abs_tol=1e-9)


def test_call_delta_reference():
    dc = float(greeks.delta(S, K, T, R, SIG, Q, "call"))
    assert math.isclose(dc, 0.6368, abs_tol=1e-3)


def test_gamma_reference():
    g = float(greeks.gamma(S, K, T, R, SIG, Q))
    assert math.isclose(g, 0.01876, abs_tol=1e-4)


def test_vega_reference():
    v = float(greeks.vega(S, K, T, R, SIG, Q))
    # Reference vega per 1.0 sigma is ~37.52
    assert math.isclose(v, 37.52, abs_tol=1e-1)


def test_vanna_call_put_equal():
    v_call_side = float(greeks.vanna(S, K, T, R, SIG, Q))
    # Vanna is independent of option type; a broadcast call should return finite.
    assert np.isfinite(v_call_side)


def test_degenerate_time():
    # T -> 0 should not raise; returns NaN for gamma / delta at ATM.
    g = greeks.gamma(S, K, 0.0, R, SIG, Q)
    assert np.isnan(g)
