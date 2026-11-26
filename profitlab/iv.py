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


def fill_from_quotes(chain: pd.DataFrame, spot: float, asof: pd.Timestamp,
                     r: float = 0.045, q: float = 0.0) -> tuple[pd.DataFrame, dict]:
    """IV de los contratos SIN IV del proveedor, calculada desde su precio
    (mid bid/ask; si no, último) invirtiendo Black-Scholes con el mismo T que
    usan las griegas (máx(días, 1)/365). Nada se inventa: si el precio no es
    coherente queda la mediana del vencimiento (como antes) o NaN.

    Añade `iv_source`: 'vendor' | 'quotes' | 'median' | 'none'."""
    from . import greeks

    df = chain.copy()
    vendor_missing = df["iv_imputed"].to_numpy(bool) if "iv_imputed" in df.columns \
        else df["iv"].isna().to_numpy()
    src = np.where(vendor_missing, "median", "vendor").astype(object)
    bid = pd.to_numeric(df.get("bid"), errors="coerce")
    ask = pd.to_numeric(df.get("ask"), errors="coerce")
    mid = (bid + ask) / 2.0
    px = mid.where((bid > 0) & (ask > 0) & (ask >= bid)).fillna(pd.to_numeric(df.get("last"), errors="coerce"))
    days = (pd.to_datetime(df["expiry"]) - asof).dt.total_seconds() / 86400.0
    t = np.maximum(days.to_numpy(), 1.0) / 365.0
    solved = np.full(len(df), np.nan)
    if vendor_missing.any():
        idx = np.nonzero(vendor_missing)[0]
        solved[idx] = greeks.implied_vol(px.to_numpy(float)[idx], spot,
                                         df["strike"].to_numpy(float)[idx], t[idx], r, q,
                                         df["type"].str.lower().to_numpy()[idx])
    use = vendor_missing & np.isfinite(solved)
    ivv = df["iv"].to_numpy(float).copy()
    ivv[use] = solved[use]
    src[use] = "quotes"
    src[~np.isfinite(ivv)] = "none"
    df["iv"] = ivv
    df["iv_source"] = src
    n = len(df) or 1
    stats = {
        "vendor_pct": round(float((src == "vendor").sum()) / n * 100, 1),
        "quotes_pct": round(float((src == "quotes").sum()) / n * 100, 1),
        "median_pct": round(float((src == "median").sum()) / n * 100, 1),
        "none_pct": round(float((src == "none").sum()) / n * 100, 1),
    }
    df.attrs.update(chain.attrs)
    df.attrs["iv_missing"] = bool(np.isnan(ivv).all())
    return df, stats


def parity_spot(chain: pd.DataFrame, spot_guess: float, asof: pd.Timestamp,
                r: float = 0.045, band: float = 0.04, max_exp: int = 2) -> Optional[float]:
    """Spot implícito por paridad put-call con la PROPIA cadena:
        S = C − P + K·e^(−rT)
    en strikes a ±`band` del spot estimado, de los `max_exp` primeros
    vencimientos, solo donde call y put del mismo strike tienen precio
    (mid bid/ask o último). Devuelve la mediana (robusta a un strike malo)
    o None si hay menos de 3 pares."""
    df = chain.copy()
    bid = pd.to_numeric(df.get("bid"), errors="coerce")
    ask = pd.to_numeric(df.get("ask"), errors="coerce")
    mid = (bid + ask) / 2.0
    df["px"] = mid.where((bid > 0) & (ask > 0) & (ask >= bid)).fillna(pd.to_numeric(df.get("last"), errors="coerce"))
    df = df[df["px"] > 0]
    exps = sorted(pd.to_datetime(df["expiry"]).unique())[:max_exp]
    df = df[pd.to_datetime(df["expiry"]).isin(exps)
            & (df["strike"] >= spot_guess * (1 - band)) & (df["strike"] <= spot_guess * (1 + band))]
    piv = df.pivot_table(index=["expiry", "strike"], columns=df["type"].str.lower(),
                         values="px", aggfunc="mean")
    if "call" not in piv or "put" not in piv:
        return None
    piv = piv.dropna(subset=["call", "put"])
    if len(piv) < 3:
        return None
    exp_idx = pd.to_datetime(piv.index.get_level_values(0))
    k = piv.index.get_level_values(1).to_numpy(float)
    t = np.maximum((exp_idx - asof).total_seconds().to_numpy() / 86400.0, 1.0) / 365.0
    s = piv["call"].to_numpy(float) - piv["put"].to_numpy(float) + k * np.exp(-r * t)
    s = s[np.isfinite(s) & (s > 0)]
    return float(np.median(s)) if len(s) >= 3 else None
