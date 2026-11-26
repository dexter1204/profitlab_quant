"""Identificación única de instrumentos (fuente de verdad para web, iOS y Android).

Cada símbolo que pide el usuario se resuelve aquí a:
  · options   subyacente cuya cadena de opciones alimenta GEX/DEX/espectros
  · fallback  subyacente alternativo si la cadena de `options` no es válida
              (p. ej. índice sin datos en el plan → su ETF)
  · bars      símbolo para precio/volumen intradía (Volume Profile, drifts).
              Los índices no tienen volumen negociado: se usa su ETF.
  · proxy     True si el dato NO es del instrumento pedido sino de un sustituto
              (CFD → índice/ETF, futuro → índice). La API lo informa siempre.

Regla acordada con ProfitLab (2026-11): opciones del índice si tiene datos;
volumen y barras siempre del ETF; todo lo que sea sustituto, etiquetado.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Optional

# Índice → ETF con volumen real (para barras y Volume Profile).
INDEX_ETF = {
    "SPX": "SPY", "NDX": "QQQ", "DJX": "DIA", "RUT": "IWM", "OEX": "SPY",
}
INDICES = {"SPX", "NDX", "DJX", "RUT", "OEX", "VIX"}


@dataclass(frozen=True)
class Instrument:
    symbol: str                 # lo que pidió el usuario (clave de caché)
    label: str
    kind: str                   # cfd | future | index | equity
    options: str
    fallback: Optional[str]
    bars: Optional[str]         # None = sin barras con volumen (p. ej. VIX)
    proxy: bool
    note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


# CFD / símbolos de broker → subyacentes con opciones y volumen.
CFD = {
    "SPX500": Instrument("SPX500", "S&P 500 (CFD)", "cfd", "SPX", "SPY", "SPY", True,
                         "Opciones del índice SPX (o SPY); precio y volumen de SPY."),
    "US500":  Instrument("US500", "S&P 500 (CFD)", "cfd", "SPX", "SPY", "SPY", True,
                         "Opciones del índice SPX (o SPY); precio y volumen de SPY."),
    "NAS100": Instrument("NAS100", "Nasdaq 100 (CFD)", "cfd", "NDX", "QQQ", "QQQ", True,
                         "Opciones del índice NDX (o QQQ); precio y volumen de QQQ."),
    "US100":  Instrument("US100", "Nasdaq 100 (CFD)", "cfd", "NDX", "QQQ", "QQQ", True,
                         "Opciones del índice NDX (o QQQ); precio y volumen de QQQ."),
    "US30":   Instrument("US30", "Dow Jones 30 (CFD)", "cfd", "DIA", None, "DIA", True,
                         "Opciones y volumen de DIA (las opciones DJX casi no tienen liquidez)."),
    "XAUUSD": Instrument("XAUUSD", "Oro (CFD)", "cfd", "GLD", None, "GLD", True,
                         "Proxy: ETF GLD. El oro al contado no tiene opciones listadas."),
    "WTI":    Instrument("WTI", "Petróleo WTI (CFD)", "cfd", "USO", None, "USO", True,
                         "Proxy: ETF USO. Escala de precio distinta al barril."),
    "USOIL":  Instrument("USOIL", "Petróleo WTI (CFD)", "cfd", "USO", None, "USO", True,
                         "Proxy: ETF USO. Escala de precio distinta al barril."),
}

# Futuros → índice/ETF cuya gamma de opciones los mueve.
FUTURES = {
    "ES": "SPX", "MES": "SPX", "NQ": "NDX", "MNQ": "NDX",
    "YM": "DIA", "MYM": "DIA", "RTY": "RUT", "M2K": "RUT",
    "CL": "USO", "MCL": "USO", "GC": "GLD", "MGC": "GLD",
    "SI": "SLV", "ZB": "TLT", "ZN": "IEF",
}


def resolve(symbol: str) -> Instrument:
    s = (symbol or "").upper().strip()
    if not s:
        raise ValueError("Símbolo vacío")
    if s in CFD:
        return CFD[s]
    if s in FUTURES:
        u = FUTURES[s]
        return Instrument(s, f"{s} (futuro)", "future", u, INDEX_ETF.get(u),
                          INDEX_ETF.get(u, u), True,
                          f"Futuro {s}: se usa la gamma de opciones de {u}.")
    if s in INDICES:
        etf = INDEX_ETF.get(s)
        return Instrument(s, s, "index", s, etf, etf, False,
                          f"Índice sin volumen propio: barras y volumen de {etf}." if etf
                          else "Índice sin volumen negociado.")
    return Instrument(s, s, "equity", s, None, s, False)
