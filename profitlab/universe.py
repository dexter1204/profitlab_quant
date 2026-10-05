"""Curated universe of optionable symbols for the ticker search box.

Covers the names a GEX/gamma trader actually looks at — mega/large-cap
equities with deep option chains, the main ETFs, and the index symbols.
It is NOT exhaustive: Polygon/Massive lists ~10k US tickers. The search
box allows free-text entry, so any symbol not here can still be typed —
this list just powers fast type-ahead for the common ones.

Grouped so the UI can show section labels if desired; SEARCH_LIST is the
flat, de-duplicated, display-ordered list the selector consumes.
"""

from __future__ import annotations

# ── indices (options via OPRA; yfinance uses ^, polygon uses I:) ──────────────
INDICES = ["SPX", "NDX", "VIX", "RUT", "DJX", "OEX"]

# ── broad-market & popular ETFs ──────────────────────────────────────────────
ETFS = [
    "SPY", "QQQ", "IWM", "DIA", "VOO", "VTI",
    "GLD", "SLV", "USO", "UNG", "GDX", "GDXJ",
    "TLT", "IEF", "HYG", "LQD", "TBT",
    "XLE", "XLF", "XLK", "XLV", "XLI", "XLP", "XLU", "XLY", "XLB", "XLRE", "XLC",
    "SMH", "SOXL", "SOXS", "TQQQ", "SQQQ", "SPXL", "SPXS",
    "ARKK", "KWEB", "FXI", "EEM", "EFA", "EWZ",
    "UVXY", "VXX", "SVXY",
    "BITO", "IBIT", "ETHA",
]

# ── mega / large-cap equities with liquid options ────────────────────────────
MEGACAP = [
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
]

# ── high-beta / retail-favorite names ────────────────────────────────────────
MOMENTUM = [
    "COIN", "HOOD", "SOFI", "MSTR", "MARA", "RIOT", "CLSK",
    "GME", "AMC", "BBAI", "RKLB", "ACHR", "LUNR",
    "UBER", "LYFT", "ABNB", "DASH", "SHOP", "SQ", "PYPL", "ROKU",
    "DKNG", "RBLX", "U", "NET", "DDOG", "CRWD", "ZS", "MDB",
    "F", "GM", "RIVN", "LCID", "NIO", "XPEV", "LI",
    "BABA", "PDD", "JD", "NIO",
    "CVNA", "AFRM", "UPST", "DJT", "SMR", "OKLO",
]

# Flat, de-duplicated, display order: ETFs & indices first (most-traded for
# gamma), then equities.
_SEEN: set[str] = set()
SEARCH_LIST: list[str] = []
for group in (
    ["QQQ", "SPY", "SPX", "NDX"],   # pin the four most common at the very top
    INDICES, ETFS, MEGACAP, MOMENTUM,
):
    for sym in group:
        u = sym.upper()
        if u not in _SEEN:
            _SEEN.add(u)
            SEARCH_LIST.append(u)


def is_known(ticker: str) -> bool:
    return ticker.upper() in _SEEN
