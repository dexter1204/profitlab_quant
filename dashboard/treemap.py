"""Custom squarified treemap layout for the market heat map.

Plotly's built-in Treemap trace doesn't expose per-cell bounding boxes,
so we cannot position logos or custom shapes per tile. Instead, we
compute the layout ourselves (via `squarify`), then render each cell as
a shape + text + image on a normal Figure.

`layout_sectors` splits the plotting area into sector strips (each
sector's height/width is proportional to the sum of its children's
weights), then squarifies each strip independently. Every sector gets a
thin header band at the top; cells are laid out below.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import pandas as pd
import squarify


@dataclass
class Cell:
    ticker: str
    sector: str
    pct: float
    price: float
    x: float
    y: float
    w: float
    h: float


@dataclass
class SectorBox:
    sector: str
    x: float
    y: float
    w: float
    h: float
    header_h: float  # height of the sector header strip


def _normalize_weights(weights: Iterable[float]) -> list[float]:
    total = float(sum(weights))
    if total <= 0:
        n = max(len(list(weights)), 1)
        return [1.0 / n] * n
    return [w / total for w in weights]


def _sector_slice(sector_totals: pd.Series, x: float, y: float,
                  w: float, h: float) -> list[SectorBox]:
    """Partition the outer rect into per-sector rects, sized by total weight."""
    sizes = sector_totals.tolist()
    # squarify.normalize_sizes maps abstract sizes onto the target area.
    normed = squarify.normalize_sizes(sizes, w, h)
    rects = squarify.squarify(normed, x, y, w, h)
    boxes: list[SectorBox] = []
    for sector, r in zip(sector_totals.index.tolist(), rects):
        header = min(0.05 * r["dy"], 22.0)  # cap the header at 22 units tall
        boxes.append(SectorBox(
            sector=str(sector),
            x=r["x"], y=r["y"], w=r["dx"], h=r["dy"], header_h=header,
        ))
    return boxes


def layout_sectors(
    df: pd.DataFrame,
    total_w: float = 1000.0,
    total_h: float = 700.0,
    gap: float = 4.0,
) -> tuple[list[SectorBox], list[Cell]]:
    """Return sector boxes + per-ticker cells for the whole universe.

    `df` must have columns [ticker, sector, price, pct, weight]. Coordinates
    are returned in the same unit space as `total_w` / `total_h` (pixels-ish);
    downstream code passes them to Plotly's paper-coord shapes/annotations.
    """
    df = df.copy()
    df["weight"] = df["weight"].astype(float).clip(lower=0.1)

    sector_totals = df.groupby("sector")["weight"].sum().sort_values(ascending=False)
    boxes = _sector_slice(sector_totals, 0.0, 0.0, total_w, total_h)

    cells: list[Cell] = []
    for box in boxes:
        rows = df[df["sector"] == box.sector].copy()
        # Sort descending → squarify prefers largest first for square-ish tiles.
        rows = rows.sort_values("weight", ascending=False)
        inner_x = box.x + gap
        inner_y = box.y + box.header_h + gap
        inner_w = max(box.w - 2 * gap, 1.0)
        inner_h = max(box.h - box.header_h - 2 * gap, 1.0)
        normed = squarify.normalize_sizes(rows["weight"].tolist(), inner_w, inner_h)
        rects = squarify.squarify(normed, inner_x, inner_y, inner_w, inner_h)
        for (_, row), r in zip(rows.iterrows(), rects):
            cells.append(Cell(
                ticker=str(row["ticker"]),
                sector=box.sector,
                pct=float(row["pct"]),
                price=float(row["price"]),
                x=r["x"], y=r["y"], w=r["dx"], h=r["dy"],
            ))
    return boxes, cells
