"""Dealer gamma-regime classification."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class Regime:
    label: str          # "LONG GAMMA" | "SHORT GAMMA" | "TRANSITION"
    reading: str        # short human-facing description
    spot: float
    g_flip: Optional[float]
    gap_pct: Optional[float]


def classify(spot: float, g_flip: Optional[float], transition_bp: float = 25.0) -> Regime:
    """Long gamma above the flip, short below; transition within `transition_bp` bp."""
    if g_flip is None or spot <= 0:
        return Regime("UNKNOWN", "Insufficient data", spot, g_flip, None)
    gap = (spot - g_flip) / spot
    if abs(gap) * 10_000 <= transition_bp:
        return Regime(
            label="TRANSITION",
            reading="At the gamma flip — hedge flow can whip in either direction.",
            spot=spot,
            g_flip=g_flip,
            gap_pct=gap,
        )
    if gap > 0:
        return Regime(
            label="LONG GAMMA",
            reading="Stable — dealers dampen moves.",
            spot=spot,
            g_flip=g_flip,
            gap_pct=gap,
        )
    return Regime(
        label="SHORT GAMMA",
        reading="Unstable — dealers amplify moves.",
        spot=spot,
        g_flip=g_flip,
        gap_pct=gap,
    )
