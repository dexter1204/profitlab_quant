"""Sanity checks on the exposure aggregator and level detectors."""

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
