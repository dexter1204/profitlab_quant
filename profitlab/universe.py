"""Curated universe for the ticker search box, grouped into three
sections shown in the dropdown:

  1. OPTIONS  — equities & ETFs with listed option chains (GEX works)
  2. FUTURES  — CME futures, each mapped to the index/ETF whose option
                gamma actually drives it (ES→SPX, NQ→NDX, …) so a futures
                trader sees the relevant gamma
  3. INDICES  — cash index symbols (options via OPRA)

SEARCH_LIST interleaves non-selectable section headers so the dropdown
reads as three labeled groups; `resolve()` turns whatever the user
picks into the symbol the data layer should actually load.
"""

from __future__ import annotations

# ── section 1: optionable equities & ETFs ────────────────────────────────────
OPTIONS_SYMBOLS = [
    # broad-market & popular ETFs
    "QQQ", "SPY", "IWM", "DIA", "VOO", "VTI",
    "GLD", "SLV", "USO", "UNG", "GDX", "GDXJ",
    "TLT", "IEF", "HYG", "LQD",
    "XLE", "XLF", "XLK", "XLV", "XLI", "XLP", "XLU", "XLY", "XLB", "XLRE", "XLC",
    "SMH", "SOXL", "SOXS", "TQQQ", "SQQQ", "SPXL", "SPXS",
    "ARKK", "KWEB", "FXI", "EEM", "EFA", "EWZ",
    "UVXY", "VXX", "SVXY",
    "BITO", "IBIT", "ETHA",
    # mega / large-cap equities
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "GOOG", "META", "TSLA",
    "AVGO", "AMD", "NFLX", "ADBE", "CRM", "ORCL", "CSCO", "INTC", "QCOM",
    "TXN", "MU", "AMAT", "ARM", "SMCI", "PLTR", "SNOW", "NOW", "PANW",
    "BRK.B", "JPM", "BAC", "WFC", "GS", "MS", "C", "SCHW", "V", "MA", "AXP",
    "UNH", "JNJ", "LLY", "PFE", "MRK", "ABBV", "TMO", "ABT", "DHR",
    "XOM", "CVX", "COP", "SLB", "OXY",
    "WMT", "COST", "HD", "LOW", "TGT", "NKE", "MCD", "SBUX", "DIS",
    "PG", "KO", "PEP", "PM", "MDLZ",
    "BA", "CAT", "DE", "GE", "HON", "UPS", "FDX", "LMT", "RTX",
    "T", "VZ", "TMUS", "CMCSA",
    # high-beta / retail favorites
    "COIN", "HOOD", "SOFI", "MSTR", "MARA", "RIOT", "CLSK",
    "GME", "AMC", "RKLB", "ACHR", "LUNR",
    "UBER", "LYFT", "ABNB", "DASH", "SHOP", "SQ", "PYPL", "ROKU",
    "DKNG", "RBLX", "U", "NET", "DDOG", "CRWD", "ZS", "MDB",
    "F", "GM", "RIVN", "LCID", "NIO", "XPEV", "LI",
    "BABA", "PDD", "JD", "CVNA", "AFRM", "UPST", "DJT", "OKLO",
]

# ── section 2: futures → the index/ETF whose gamma drives them ────────────────
# A futures trader picks ES and the dashboard loads SPX gamma (ES tracks
# SPX ~1:1). Keys are what the user sees; values are what we load.
FUTURES_MAP = {
    "ES": "SPX", "MES": "SPX",
    "NQ": "NDX", "MNQ": "NDX",
    "YM": "DJX", "MYM": "DJX",
    "RTY": "RUT", "M2K": "RUT",
    "CL": "USO", "MCL": "USO",
    "GC": "GLD", "MGC": "GLD",
    "SI": "SLV",
    "ZB": "TLT", "ZN": "IEF",
}
FUTURES_SYMBOLS = list(FUTURES_MAP.keys())

# ── section 3: cash indices (options via OPRA) ───────────────────────────────
INDEX_SYMBOLS = ["SPX", "NDX", "VIX", "RUT", "DJX", "OEX"]


# ── dropdown assembly ────────────────────────────────────────────────────────
HEADER_OPTIONS = "─────  OPTIONS · stocks & ETFs  ─────"
HEADER_FUTURES = "─────  FUTURES → index gamma  ─────"
HEADER_INDICES = "─────  INDICES  ─────"
HEADERS = {HEADER_OPTIONS, HEADER_FUTURES, HEADER_INDICES}

SEARCH_LIST: list[str] = (
    [HEADER_OPTIONS] + OPTIONS_SYMBOLS
    + [HEADER_FUTURES] + FUTURES_SYMBOLS
    + [HEADER_INDICES] + INDEX_SYMBOLS
)

_KNOWN: set[str] = set(OPTIONS_SYMBOLS) | set(FUTURES_SYMBOLS) | set(INDEX_SYMBOLS)


def resolve(picked: str | None) -> str | None:
    """Map a dropdown pick to the symbol the data layer should load.
    Headers and empty picks return None (caller keeps its default);
    futures map to their gamma underlying; everything else passes
    through upper-cased."""
    if not picked or picked in HEADERS:
        return None
    p = picked.strip().upper()
    return FUTURES_MAP.get(p, p)


def is_futures(picked: str | None) -> bool:
    return bool(picked) and picked.strip().upper() in FUTURES_MAP


def is_known(ticker: str) -> bool:
    return ticker.upper() in _KNOWN
