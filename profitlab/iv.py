"""Realized volatility (HV) and IV-premium metrics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd


def hv(closes: pd.Series, window: int, annualization: int = 252) -> float:
    """Annualized close-to-close realized volatility over `window` sessions."""
    if len(closes) < window + 1:
        return float("nan")
    logret = np.log(closes.astype(float)).diff().dropna().tail(window)
    return float(logret.std(ddof=1) * np.sqrt(annualization))


@dataclass
class IVSnapshot:
    iv_atm: float
    hv10: float
    hv30: float
    hv60: float
    premium: float           # (iv_atm / hv30) - 1
    ratio_iv_hv30: float     # iv_atm / hv30
    term_structure: str      # "CONTANGO" | "BACKWARDATION" | "FLAT"
    reading: str

    def as_dict(self) -> dict:
        return {
            "iv_atm": self.iv_atm,
            "hv10": self.hv10,
            "hv30": self.hv30,
            "hv60": self.hv60,
            "premium": self.premium,
            "ratio_iv_hv30": self.ratio_iv_hv30,
            "term_structure": self.term_structure,
            "reading": self.reading,
        }


def _term_structure(front_iv: Optional[float], back_iv: Optional[float]) -> str:
    if front_iv is None or back_iv is None or np.isnan(front_iv) or np.isnan(back_iv):
        return "FLAT"
    diff = front_iv - back_iv
    if diff > 0.005:
        return "BACKWARDATION"
    if diff < -0.005:
        return "CONTANGO"
    return "FLAT"


def snapshot(
    iv_atm: float,
    closes: pd.Series,
    front_iv: Optional[float] = None,
    back_iv: Optional[float] = None,
) -> IVSnapshot:
    hv10 = hv(closes, 10)
    hv30 = hv(closes, 30)
    hv60 = hv(closes, 60)
    ratio = iv_atm / hv30 if hv30 and not np.isnan(hv30) else float("nan")
    premium = ratio - 1.0 if not np.isnan(ratio) else float("nan")
    ts = _term_structure(front_iv, back_iv)
    if not np.isnan(premium):
        if premium > 0.20:
            reading = "Opciones caras vs volatilidad realizada. Potencial ventaja al vender premium."
        elif premium < -0.10:
            reading = "Opciones baratas vs volatilidad realizada. Comprar premium puede ofrecer ventaja."
        else:
            reading = "IV alineada con HV — sin premium significativo."
    else:
        reading = "Insufficient HV history."
    return IVSnapshot(iv_atm, hv10, hv30, hv60, premium, ratio, ts, reading)
