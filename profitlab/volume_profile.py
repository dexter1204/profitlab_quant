"""Volume Profile (volumen por precio) a partir de barras OHLCV intradía.

Construcción estándar de market profile: el volumen de cada barra se reparte
entre los bins de precio que abarca su rango [low, high]; luego se halla el
Point of Control (POC, el precio más negociado) y el Value Area (la banda
contigua alrededor del POC que concentra `value_area` del volumen del día —
70 % por convención; VAH/VAL son sus bordes superior e inferior).

numpy puro, sin pandas ni DOM, para poder probarlo de forma aislada.
"""
from __future__ import annotations

import numpy as np


def compute(high, low, close, volume, bins: int = 48, value_area: float = 0.70) -> dict:
    """Devuelve el perfil de volumen.

    Parámetros: arrays paralelos de high/low/close/volume (una entrada por
    barra). `bins` = nº de niveles de precio; `value_area` = fracción del
    volumen que define el área de valor.

    Retorna dict con: price (centros de bin), volume (por bin), poc, vah, val,
    value_area, total_volume, low, high, bins.
    """
    high = np.asarray(high, dtype=float)
    low = np.asarray(low, dtype=float)
    close = np.asarray(close, dtype=float)
    volume = np.asarray(volume, dtype=float)
    n = int(len(close))
    if n == 0:
        raise ValueError("sin barras")

    lo = float(np.nanmin(low))
    hi = float(np.nanmax(high))
    if not np.isfinite(lo):
        lo = float(np.nanmin(close))
    if not np.isfinite(hi):
        hi = float(np.nanmax(close))
    if hi <= lo:                      # sesión plana: una franja mínima para no dividir por cero
        hi = lo + 1e-9

    bins = max(1, int(bins))
    edges = np.linspace(lo, hi, bins + 1)
    centers = 0.5 * (edges[:-1] + edges[1:])
    width = (hi - lo) / bins
    vol_bins = np.zeros(bins, dtype=float)

    for i in range(n):
        v = volume[i]
        if not np.isfinite(v) or v <= 0:
            continue
        b_lo = low[i] if np.isfinite(low[i]) else close[i]
        b_hi = high[i] if np.isfinite(high[i]) else close[i]
        if not np.isfinite(b_lo) or not np.isfinite(b_hi):
            continue
        if b_hi < b_lo:
            b_lo, b_hi = b_hi, b_lo
        j0 = int(np.clip(np.floor((b_lo - lo) / width), 0, bins - 1))
        j1 = int(np.clip(np.floor((b_hi - lo) / width), 0, bins - 1))
        span = j1 - j0 + 1
        vol_bins[j0:j1 + 1] += v / span   # reparto uniforme en los niveles que tocó la barra

    total = float(vol_bins.sum())
    poc_idx = int(np.argmax(vol_bins)) if total > 0 else 0

    # Value Area: desde el POC, se expande hacia el vecino con más volumen
    # hasta acumular `value_area` del total.
    lo_idx = hi_idx = poc_idx
    acc = float(vol_bins[poc_idx])
    target = value_area * total
    while acc < target and (lo_idx > 0 or hi_idx < bins - 1):
        below = float(vol_bins[lo_idx - 1]) if lo_idx > 0 else -1.0
        above = float(vol_bins[hi_idx + 1]) if hi_idx < bins - 1 else -1.0
        if above >= below:
            hi_idx += 1
            acc += float(vol_bins[hi_idx])
        else:
            lo_idx -= 1
            acc += float(vol_bins[lo_idx])

    return {
        "bins": bins,
        "price": [float(c) for c in centers],
        "volume": [float(v) for v in vol_bins],
        "poc": float(centers[poc_idx]),
        "vah": float(edges[hi_idx + 1]),
        "val": float(edges[lo_idx]),
        "value_area": float(value_area),
        "total_volume": total,
        "low": lo,
        "high": hi,
    }


def nodes(price, volume, hvn_ratio: float = 1.25, lvn_ratio: float = 0.5) -> dict:
    """Nodos de volumen del perfil.

    Se suaviza el perfil con una media móvil de 3 niveles (reduce el ruido de
    bins vecinos) y se buscan extremos locales:
      · HVN (High Volume Node): máximo local con volumen ≥ hvn_ratio × media.
      · LVN (Low Volume Node):  mínimo local con volumen ≤ lvn_ratio × media,
        solo ENTRE dos zonas con volumen (los bordes vacíos no son nodos).
    Devuelve {"hvn": [precios], "lvn": [precios]} ordenados por precio.
    """
    p = np.asarray(price, dtype=float)
    v = np.asarray(volume, dtype=float)
    n = len(v)
    if n < 3 or v.sum() <= 0:
        return {"hvn": [], "lvn": []}
    k = np.ones(3) / 3.0
    s = np.convolve(np.pad(v, 1, mode="edge"), k, mode="valid")
    mean = float(s.mean())
    hvn, lvn = [], []
    nz = np.nonzero(v > 0)[0]
    first, last = (int(nz[0]), int(nz[-1])) if len(nz) else (0, n - 1)
    for i in range(1, n - 1):
        if s[i] >= s[i - 1] and s[i] >= s[i + 1] and s[i] >= hvn_ratio * mean:
            if s[i] > min(s[i - 1], s[i + 1]):
                hvn.append(float(p[i]))
        if first < i < last and s[i] <= s[i - 1] and s[i] <= s[i + 1] and s[i] <= lvn_ratio * mean:
            if s[i] < max(s[i - 1], s[i + 1]):
                lvn.append(float(p[i]))
    return {"hvn": hvn, "lvn": lvn}
