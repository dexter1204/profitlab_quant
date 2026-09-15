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


def classify(
    spot: float,
    g_flip: Optional[float],
    total_gex: Optional[float] = None,
    transition_bp: float = 25.0,
) -> Regime:
    """Dealer gamma regime.

    Uses the sign of TOTAL GEX when available (the SpotGamma/MenthorQ
    convention: positive dealer gamma → dampens moves, negative →
    amplifies). Falls back to spot-vs-g-flip when total GEX isn't
    provided, but the two can disagree — total GEX is the truer signal.
    """
    gap = None
    if g_flip is not None and spot > 0:
        gap = (spot - g_flip) / spot

    if total_gex is not None:
        if total_gex > 0:
            return Regime("LONG GAMMA", "Stable — dealers dampen moves.",
                          spot, g_flip, gap)
        if total_gex < 0:
            return Regime("SHORT GAMMA", "Volatile — dealers amplify moves.",
                          spot, g_flip, gap)
        return Regime("TRANSITION", "Net dealer gamma near zero.",
                      spot, g_flip, gap)

    # Fallback: spot-vs-flip only
    if g_flip is None or spot <= 0 or gap is None:
        return Regime("UNKNOWN", "Insufficient data", spot, g_flip, None)
    if abs(gap) * 10_000 <= transition_bp:
        return Regime("TRANSITION",
                      "At the gamma flip — hedge flow can whip in either direction.",
                      spot, g_flip, gap)
    if gap > 0:
        return Regime("LONG GAMMA", "Stable — dealers dampen moves.",
                      spot, g_flip, gap)
    return Regime("SHORT GAMMA", "Volatile — dealers amplify moves.",
                  spot, g_flip, gap)
