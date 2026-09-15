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
    band_pct: float = 0.10,
) -> Optional[float]:
    """Linear interpolation of the strike where the cumulative series
    flips sign.

    When `spot` is supplied, restricts the search to strikes within
    `band_pct` of spot — otherwise the cumulative-sum sign flip can pick
    a nonsense crossing at deep-OTM strikes with tiny OI that doesn't
    represent an actual dealer gamma flip. This is the standard SpotGamma
    / MenthorQ convention.
    """
    if df.empty:
        return None
    view = df
    if spot is not None:
        lo = spot * (1 - band_pct)
        hi = spot * (1 + band_pct)
        view = df[(df["strike"] >= lo) & (df["strike"] <= hi)]
        if view.empty:
            view = df  # fall back to the full range
    xs = view["strike"].to_numpy(dtype=float)
    ys = view[column].cumsum().to_numpy(dtype=float)
    signs = np.sign(ys)
    if np.all(signs >= 0) or np.all(signs <= 0):
        return None
    idx = int(np.argmax(np.diff(signs) != 0))
    x0, x1 = xs[idx], xs[idx + 1]
    y0, y1 = ys[idx], ys[idx + 1]
    if y1 == y0:
        return float(x0)
    return float(x0 - y0 * (x1 - x0) / (y1 - y0))


def call_wall(gex: pd.DataFrame, spot: float) -> Optional[float]:
    """Largest positive-GEX strike at or above spot."""
    above = gex[(gex["strike"] >= spot) & (gex["gex"] > 0)]
    return _peak_strike(above, "gex")


def put_wall(gex: pd.DataFrame, spot: float) -> Optional[float]:
    """Largest negative-GEX strike at or below spot (magnitude)."""
    below = gex[(gex["strike"] <= spot) & (gex["gex"] < 0)].copy()
    if below.empty:
        return None
    below["mag"] = below["gex"].abs()
    return _peak_strike(below, "mag")


def gamma_flip(gex: pd.DataFrame, spot: Optional[float] = None) -> Optional[float]:
    return _zero_crossing(gex, "gex", spot=spot)


def delta_flip(dex: pd.DataFrame, spot: Optional[float] = None) -> Optional[float]:
    return _zero_crossing(dex, "dex", spot=spot)


def delta_wall(dex: pd.DataFrame, spot: float) -> Optional[float]:
    """Largest positive-delta strike above spot — resistance from dealer hedge flow."""
    above = dex[(dex["strike"] >= spot) & (dex["dex"] > 0)]
    return _peak_strike(above, "dex")


def major_neg_delta(dex: pd.DataFrame, spot: float) -> Optional[float]:
    """Largest negative-delta strike; either side of spot."""
    return _trough_strike(dex, "dex")


def max_pain(chain: pd.DataFrame) -> Optional[float]:
    """Strike that minimizes total intrinsic option value across all OI."""
    if chain.empty:
        return None
    strikes = np.sort(chain["strike"].unique())
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
        max_pain=max_pain(chain),
    )
