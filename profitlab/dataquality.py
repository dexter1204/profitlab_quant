"""Data-quality checks for an option chain.

GEX/DEX are only as good as the chain they're built from. This flags the
common ways a vendor response goes bad — empty chain, missing/zero implied
vol, missing open interest, stale snapshot — so the dashboard can warn (or
refuse to plot) instead of drawing a confident-looking chart over garbage.
"""

from __future__ import annotations

from typing import Optional

import pandas as pd


def assess_chain(
    chain: Optional[pd.DataFrame],
    spot: Optional[float] = None,
    asof: Optional[pd.Timestamp] = None,
    max_age_days: int = 4,
) -> dict:
    """Return a health report: ok flag, severity, human issues, and coverage
    metrics. Never raises — bad input just yields ok=False."""
    issues: list[str] = []
    warnings: list[str] = []

    if chain is None or len(chain) == 0:
        return {
            "ok": False, "severity": "error", "n_contracts": 0,
            "iv_coverage": 0.0, "oi_coverage": 0.0,
            "issues": ["La fuente devolvió una cadena de opciones vacía "
                       "(sin contratos). Puede ser límite de tasa del proveedor "
                       "o un símbolo/plan sin opciones."],
            "warnings": [],
        }

    n = len(chain)

    def _cov(col: str) -> float:
        if col not in chain.columns:
            return 0.0
        s = pd.to_numeric(chain[col], errors="coerce")
        return float((s.fillna(0) > 0).mean())

    iv_cov = _cov("iv")
    oi_cov = _cov("oi")

    if iv_cov == 0.0:
        issues.append("Ninguna IV válida en la cadena → el GEX/DEX no es fiable.")
    elif iv_cov < 0.5:
        warnings.append(f"IV presente en solo {iv_cov*100:.0f}% de los contratos.")

    if oi_cov == 0.0:
        issues.append("Open interest ausente o cero en toda la cadena → "
                      "GEX/DEX saldrá plano (OI es el peso).")
    elif oi_cov < 0.3:
        warnings.append(f"Open interest > 0 en solo {oi_cov*100:.0f}% de los contratos.")

    if spot is not None:
        try:
            if not (spot > 0):
                issues.append("Spot no válido (<= 0).")
        except TypeError:
            issues.append("Spot no válido.")

    # Snapshot staleness: newest expiry in the past, or asof older than N days.
    try:
        if asof is not None:
            age = (pd.Timestamp.now("UTC").tz_localize(None).normalize()
                   - pd.Timestamp(asof).tz_localize(None).normalize()).days
            if age > max_age_days:
                warnings.append(f"Snapshot con {age} días de antigüedad.")
        exps = pd.to_datetime(chain["expiry"], errors="coerce").dropna()
        if len(exps):
            today = pd.Timestamp.now("UTC").tz_localize(None).normalize()
            if exps.max().tz_localize(None).normalize() < today:
                issues.append("Todos los vencimientos ya expiraron (cadena vieja).")
    except Exception:
        pass

    severity = "error" if issues else ("warning" if warnings else "ok")
    return {
        "ok": severity != "error",
        "severity": severity,
        "n_contracts": int(n),
        "iv_coverage": round(iv_cov, 3),
        "oi_coverage": round(oi_cov, 3),
        "issues": issues,
        "warnings": warnings,
    }
