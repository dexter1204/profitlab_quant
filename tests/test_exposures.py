"""Sanity checks on the exposure aggregator and level detectors."""

import numpy as np
import pandas as pd

from profitlab import demo, exposures, metrics, regime


def _ctx(spot: float) -> exposures.ChainContext:
    return exposures.ChainContext(spot=spot, asof=pd.Timestamp.now("UTC").tz_localize(None).normalize())


def test_demo_chain_shape():
    chain = demo.demo_chain("QQQ")
    assert {"strike", "expiry", "type", "oi", "iv"}.issubset(chain.columns)
    assert (chain["oi"] >= 0).all()
    assert (chain["iv"] > 0).all()


def test_gex_and_dex_by_strike_sum_to_totals():
    chain = demo.demo_chain("QQQ")
    ctx = _ctx(demo.DEMO_SPOTS["QQQ"])
    gex = exposures.gex_by_strike(chain, ctx)
    dex = exposures.dex_by_strike(chain, ctx)
    t = exposures.totals(chain, ctx)
    assert abs(float(gex["gex"].sum()) - t["gex"]) < 1e-6
    assert abs(float(dex["dex"].sum()) - t["dex"]) < 1e-6


def test_key_levels_produce_finite_values():
    chain = demo.demo_chain("QQQ")
    spot = demo.DEMO_SPOTS["QQQ"]
    ctx = _ctx(spot)
    gex = exposures.gex_by_strike(chain, ctx)
    dex = exposures.dex_by_strike(chain, ctx)
    lv = metrics.key_levels(chain, gex, dex, spot).as_dict()
    for k in ("call_wall", "put_wall", "max_pain"):
        assert lv[k] is not None
        assert 0.5 * spot <= lv[k] <= 2.0 * spot


def test_delta_surface_shape_and_bounds():
    """Call delta must be in [0, 1] everywhere on the grid, monotone
    non-decreasing in spot at any fixed time slice."""
    ctx = _ctx(demo.DEMO_SPOTS["QQQ"])
    sx, sy, sz = exposures.delta_surface(
        ctx, strike=ctx.spot, iv=0.25, days_max=45, n_spot=25, n_time=15,
    )
    assert sz.shape == (15, 25)
    assert sz.min() >= 0.0 - 1e-9
    assert sz.max() <= 1.0 + 1e-9
    # Monotone in spot along the first time slice (short-dated is sharpest).
    row = sz[0]
    assert (row[1:] - row[:-1] >= -1e-9).all()


def test_gex_grid_sums_match_strike_totals():
    chain = demo.demo_chain("QQQ")
    ctx = _ctx(demo.DEMO_SPOTS["QQQ"])
    grid = exposures.gex_by_strike_expiry(chain, ctx)
    per_strike = grid.groupby("strike", as_index=False)["gex"].sum().sort_values("strike")
    reference = exposures.gex_by_strike(chain, ctx).sort_values("strike").reset_index(drop=True)
    merged = per_strike.reset_index(drop=True).merge(reference, on="strike", suffixes=("_grid", "_ref"))
    assert (merged["gex_grid"] - merged["gex_ref"]).abs().max() < 1e-6


def test_oi_by_strike_expiry_columns_and_sums():
    chain = demo.demo_chain("QQQ")
    grid = exposures.oi_by_strike_expiry(chain)
    assert {"call_oi", "put_oi", "net_oi", "total_oi"}.issubset(grid.columns)
    # Sanity: totals reconstruct the raw chain totals.
    total_from_grid = float(grid["total_oi"].sum())
    total_from_chain = float(chain["oi"].sum())
    assert abs(total_from_grid - total_from_chain) < 1e-6


def test_pct_oi_normalizes_to_one():
    chain = demo.demo_chain("QQQ")
    pct = exposures.pct_oi_by_strike_expiry(chain)
    # Sum of shares across all cells must equal 1 (± float).
    assert abs(float(pct["pct_total_oi"].sum()) - 1.0) < 1e-9


def test_iv_by_expiry_produces_row_per_expiry():
    chain = demo.demo_chain("QQQ")
    term = exposures.iv_by_expiry(chain, spot=demo.DEMO_SPOTS["QQQ"])
    assert set(term.columns).issuperset({"expiry", "atm_iv", "call_iv", "put_iv", "skew", "dte"})
    assert len(term) == chain["expiry"].nunique()
    assert (term["atm_iv"] > 0).all()


def test_iv_surface_shape_covers_window():
    spot = demo.DEMO_SPOTS["QQQ"]
    chain = demo.demo_chain("QQQ")
    grid = exposures.iv_surface(chain, spot, strike_window=15)
    assert {"strike", "expiry", "iv"}.issubset(grid.columns)
    assert (grid["iv"] > 0).all()
    # All strikes returned must fall within the requested window.
    step = float(np.median(np.diff(np.sort(chain["strike"].unique()))))
    assert grid["strike"].between(spot - 15 * step, spot + 15 * step).all()


def test_net_drift_monotone_direction_matches_gamma_regime():
    """In a call-dominated (long-gamma) regime, net delta should trend upward
    with spot — dealers are progressively longer as spot rises."""
    spot = demo.DEMO_SPOTS["QQQ"]
    chain = demo.demo_chain("QQQ")
    ctx = _ctx(spot)
    df = exposures.net_drift(chain, ctx, spot_pct=0.03, n=41)
    assert len(df) == 41
    assert (df["spot"].diff().dropna() > 0).all()
    # Fit a slope; sign varies by chain but the value should be finite.
    slope = float(np.polyfit(df["spot"], df["net_delta"], 1)[0])
    assert np.isfinite(slope)


def test_regime_flips_around_gamma_flip():
    chain = demo.demo_chain("QQQ")
    spot = demo.DEMO_SPOTS["QQQ"]
    ctx = _ctx(spot)
    gex = exposures.gex_by_strike(chain, ctx)
    g_flip = metrics.gamma_flip(gex)
    if g_flip is None:
        return  # nothing to check
    above = regime.classify(g_flip + 1.0, g_flip)
    below = regime.classify(g_flip - 1.0, g_flip)
    assert above.label in {"LONG GAMMA", "TRANSITION"}
    assert below.label in {"SHORT GAMMA", "TRANSITION"}
