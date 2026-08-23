"""Market universe + heat-map builder sanity checks."""

import pandas as pd

from profitlab import market
from dashboard import components


def test_demo_heatmap_shape():
    df = market.demo_heatmap()
    assert {"ticker", "sector", "price", "pct", "weight"}.issubset(df.columns)
    assert len(df) == len(market.UNIVERSE)
    # Every sector referenced in UNIVERSE appears in the frame.
    assert set(df["sector"].unique()) == {s for _, s, _ in market.UNIVERSE}
    assert (df["weight"] > 0).all()
    assert df["pct"].between(-0.06, 0.06).all()


def test_summary_matches_frame():
    df = market.demo_heatmap()
    s = market.summarize(df)
    assert s.n_symbols == len(df)
    assert s.n_up + s.n_down <= s.n_symbols  # zero-change rows possible in principle
    assert s.best[0] == df.loc[df["pct"].idxmax(), "ticker"]
    assert s.worst[0] == df.loc[df["pct"].idxmin(), "ticker"]


def test_market_heatmap_figure_builds_and_serializes():
    import plotly.io as pio
    df = market.demo_heatmap()
    fig = components.market_heatmap(df)
    assert len(fig.data) == 1
    pio.to_json(fig)  # same code path Streamlit uses


def test_treemap_parent_totals_equal_child_sums():
    """Regression: branchvalues='total' collapses the tree if the sector
    root value doesn't equal the sum of its children's values."""
    from collections import defaultdict

    df = market.demo_heatmap()
    fig = components.market_heatmap(df)
    labels = list(fig.data[0].labels)
    parents = list(fig.data[0].parents)
    values = list(fig.data[0].values)

    kids_sum = defaultdict(float)
    for lbl, par, val in zip(labels, parents, values):
        if par:
            kids_sum[par] += val
    for lbl, par, val in zip(labels, parents, values):
        if par == "":
            assert abs(val - kids_sum[lbl]) < 1e-6, f"sector {lbl!r} value ≠ children"


def test_cell_color_diverges_around_zero():
    green = components._cell_color(0.05)
    red = components._cell_color(-0.05)
    black = components._cell_color(0.0)
    assert green.startswith("rgb(") and red.startswith("rgb(")
    assert black == "rgb(11,18,32)"  # dark base
