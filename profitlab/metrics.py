"""Key option-market levels derived from a strike-level GEX / DEX profile."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd


@dataclass
class KeyLevels:
    call_wall: Optional[float]
    put_wall: Optional[float]
    gamma_flip: Optional[float]
    delta_flip: Optional[float]
    delta_wall: Optional[float]
    major_neg_delta: Optional[float]
    max_pain: Optional[float]

    def as_dict(self) -> dict:
        return {
            "call_wall": self.call_wall,
            "put_wall": self.put_wall,
            "gamma_flip": self.gamma_flip,
            "delta_flip": self.delta_flip,
            "delta_wall": self.delta_wall,
            "major_neg_delta": self.major_neg_delta,
            "max_pain": self.max_pain,
        }


def _peak_strike(df: pd.DataFrame, column: str) -> Optional[float]:
    if df.empty:
        return None
    row = df.loc[df[column].idxmax()]
    return float(row["strike"])


def _trough_strike(df: pd.DataFrame, column: str) -> Optional[float]:
    if df.empty:
        return None
    row = df.loc[df[column].idxmin()]
    return float(row["strike"])


def _zero_crossing(
    df: pd.DataFrame, column: str, spot: Optional[float] = None,
    band_pct: float = 0.10, cumulative: bool = True,
) -> Optional[float]:
    """Linear interpolation of the strike where a series flips sign.

    `cumulative=True` crosses the cumulative (net) series — the classic
    net-gamma flip. `cumulative=False` crosses the per-strike series, which
    still finds the ATM negative→positive transition even when one side so
    dominates that the cumulative never returns to zero.

    When `spot` is supplied the search is restricted to strikes within
    `band_pct` of spot, and (for multiple crossings) the one nearest spot is
    returned — the standard SpotGamma / MenthorQ convention.
    """
    if df.empty:
        return None
    view = df.sort_values("strike")
    if spot is not None:
        lo, hi = spot * (1 - band_pct), spot * (1 + band_pct)
        band = view[(view["strike"] >= lo) & (view["strike"] <= hi)]
        if not band.empty:
            view = band
    xs = view["strike"].to_numpy(dtype=float)
    ys = (view[column].cumsum() if cumulative else view[column]).to_numpy(dtype=float)
    signs = np.sign(ys)
    flips = np.nonzero(np.diff(signs) != 0)[0]
    if len(flips) == 0:
        return None

    def _interp(idx: int) -> float:
        x0, x1 = xs[idx], xs[idx + 1]
        y0, y1 = ys[idx], ys[idx + 1]
        return float(x0) if y1 == y0 else float(x0 - y0 * (x1 - x0) / (y1 - y0))

    crossings = [_interp(i) for i in flips]
    if spot is not None:
        return min(crossings, key=lambda x: abs(x - spot))
    return crossings[0]


def call_wall(gex: pd.DataFrame, spot: float, band_pct: float = 0.10) -> Optional[float]:
    """Largest positive-GEX strike within [spot, spot*(1+band_pct)]."""
    hi = spot * (1 + band_pct)
    above = gex[(gex["strike"] >= spot) & (gex["strike"] <= hi) & (gex["gex"] > 0)]
    if above.empty:
        # Fall back to any positive-GEX strike at or above spot.
        above = gex[(gex["strike"] >= spot) & (gex["gex"] > 0)]
    return _peak_strike(above, "gex")


def put_wall(gex: pd.DataFrame, spot: float, band_pct: float = 0.10) -> Optional[float]:
    """Largest negative-GEX strike within [spot*(1-band_pct), spot]."""
    lo = spot * (1 - band_pct)
    below = gex[(gex["strike"] <= spot) & (gex["strike"] >= lo) & (gex["gex"] < 0)].copy()
    if below.empty:
        below = gex[(gex["strike"] <= spot) & (gex["gex"] < 0)].copy()
    if below.empty:
        return None
    below["mag"] = below["gex"].abs()
    return _peak_strike(below, "mag")


def gamma_flip(gex: pd.DataFrame, spot: Optional[float] = None) -> Optional[float]:
    """Zero-gamma level. Try the classic net (cumulative) crossing first;
    when the profile is so one-sided that the net never returns to zero,
    fall back to the per-strike ATM sign flip, then to a full-range net
    crossing. This keeps the flip populated for put-heavy index chains."""
    return (
        _zero_crossing(gex, "gex", spot=spot, cumulative=True)
        or _zero_crossing(gex, "gex", spot=spot, cumulative=False)
        or _zero_crossing(gex, "gex", spot=None, cumulative=True)
    )


def delta_flip(dex: pd.DataFrame, spot: Optional[float] = None) -> Optional[float]:
    return (
        _zero_crossing(dex, "dex", spot=spot, cumulative=True)
        or _zero_crossing(dex, "dex", spot=spot, cumulative=False)
    )


def delta_wall(dex: pd.DataFrame, spot: float, band_pct: float = 0.10) -> Optional[float]:
    """Dominant delta-exposure strike near spot. Prefer the largest
    positive-delta strike (call-side wall); when none is positive in the
    band (a put-heavy chain), fall back to the largest ABSOLUTE delta strike
    so the level is always populated."""
    lo, hi = spot * (1 - band_pct), spot * (1 + band_pct)
    pos = dex[(dex["strike"] >= lo) & (dex["strike"] <= hi) & (dex["dex"] > 0)]
    if not pos.empty:
        return _peak_strike(pos, "dex")
    pos = dex[(dex["strike"] >= spot) & (dex["dex"] > 0)]
    if not pos.empty:
        return _peak_strike(pos, "dex")
    # put-heavy: no positive delta → strongest |delta| in the band
    band = dex[(dex["strike"] >= lo) & (dex["strike"] <= hi)].copy()
    if band.empty:
        band = dex.copy()
    if band.empty:
        return None
    band["mag"] = band["dex"].abs()
    return _peak_strike(band, "mag")


def major_neg_delta(dex: pd.DataFrame, spot: float,
                    band_pct: float = 0.10) -> Optional[float]:
    """Largest negative-delta strike within ±band around spot."""
    lo, hi = spot * (1 - band_pct), spot * (1 + band_pct)
    window = dex[(dex["strike"] >= lo) & (dex["strike"] <= hi) & (dex["dex"] < 0)]
    if window.empty:
        window = dex[dex["dex"] < 0]
    return _trough_strike(window, "dex")


def max_pain(chain: pd.DataFrame, spot: Optional[float] = None,
             band_pct: float = 0.15) -> Optional[float]:
    """Strike within `band_pct` of spot that minimizes total intrinsic
    option value across all OI. Restricted so deep-OTM strikes with
    lopsided OI can't hijack the result."""
    if chain.empty:
        return None
    strikes = np.sort(chain["strike"].unique())
    if spot is not None:
        lo, hi = spot * (1 - band_pct), spot * (1 + band_pct)
        band = strikes[(strikes >= lo) & (strikes <= hi)]
        if len(band):
            strikes = band
    call_mask = chain["type"].str.lower() == "call"
    calls = chain[call_mask]
    puts = chain[~call_mask]
    call_k = calls["strike"].to_numpy(dtype=float)
    call_oi = calls["oi"].to_numpy(dtype=float)
    put_k = puts["strike"].to_numpy(dtype=float)
    put_oi = puts["oi"].to_numpy(dtype=float)
    pain = []
    for k in strikes:
        c = np.maximum(k - call_k, 0.0) * call_oi
        p = np.maximum(put_k - k, 0.0) * put_oi
        pain.append(c.sum() + p.sum())
    return float(strikes[int(np.argmin(pain))])


def key_levels(
    chain: pd.DataFrame,
    gex: pd.DataFrame,
    dex: pd.DataFrame,
    spot: float,
) -> KeyLevels:
    return KeyLevels(
        call_wall=call_wall(gex, spot),
        put_wall=put_wall(gex, spot),
        gamma_flip=gamma_flip(gex, spot=spot),
        delta_flip=delta_flip(dex, spot=spot),
        delta_wall=delta_wall(dex, spot),
        major_neg_delta=major_neg_delta(dex, spot),
        max_pain=max_pain(chain, spot=spot),
    )
