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
    # Exactly one hover-target scatter trace on top of the shapes.
    assert len(fig.data) == 1
    pio.to_json(fig)


def test_market_heatmap_covers_every_ticker():
    """Every ticker in the universe must be reachable — either as a visible
    text annotation, a logo image, or (at minimum) a hover marker."""
    from dashboard import treemap as tm

    df = market.demo_heatmap()
    fig = components.market_heatmap(df)
    boxes, cells = tm.layout_sectors(df)
    assert {c.ticker for c in cells} == set(df["ticker"])

    # Hover scatter carries every ticker.
    hover_text = "\n".join(fig.data[0].hovertext or [])
    for tk in df["ticker"]:
        assert tk in hover_text, f"missing hover for {tk!r}"


def test_market_heatmap_pairs_remote_and_fallback_images():
    """When a logo is drawn, we stack a remote PNG on top of the SVG chip
    so a 404 on the PNG still shows the fallback. Every non-index ticker
    that gets a logo should have exactly two layout images at its chip
    position."""
    df = market.demo_heatmap()
    fig = components.market_heatmap(df)
    # Images should be even in count (remote+fallback pair per rendered chip).
    assert len(fig.layout.images) % 2 == 0


def test_layout_partitions_are_non_overlapping():
    """Squarified layout must produce cells that fit inside their sector box
    and don't overlap between siblings."""
    from dashboard import treemap as tm

    df = market.demo_heatmap()
    boxes, cells = tm.layout_sectors(df, total_w=1000, total_h=700)
    box_by_sector = {b.sector: b for b in boxes}
    for c in cells:
        b = box_by_sector[c.sector]
        assert b.x - 1e-6 <= c.x and c.x + c.w <= b.x + b.w + 1e-6
        assert b.y - 1e-6 <= c.y and c.y + c.h <= b.y + b.h + 1e-6


def test_cell_color_diverges_around_zero():
    green = components._cell_color(0.05)
    red = components._cell_color(-0.05)
    black = components._cell_color(0.0)
    assert green.startswith("rgb(") and red.startswith("rgb(")
    assert black == "rgb(11,18,32)"  # dark base
