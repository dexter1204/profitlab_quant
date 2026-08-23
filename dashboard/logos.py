"""Stock-ticker logo chips as offline SVG data-URIs.

Plotly cannot fetch external images from a Streamlit app that renders in
the user's browser without a network round-trip, and we want the demo to
work offline. So each logo is a small SVG (brand color + white initial)
serialized to a data URI — deterministic, tiny, and referenced inline.

Colors follow public brand identities; keep the palette conservative
(single hex) so the chip reads as an icon rather than a rendered logo.
"""

from __future__ import annotations

import base64
from functools import lru_cache


BRAND_COLORS: dict[str, str] = {
    # Technology
    "AAPL": "#000000", "MSFT": "#00A4EF", "NVDA": "#76B900",
    "AMD":  "#111827", "PLTR": "#101828", "MSTR": "#F97316",
    # Communication Services
    "META": "#1877F2", "GOOG": "#FFFFFF", "GOOGL": "#FFFFFF", "NFLX": "#E50914",
    # Consumer Cyclical
    "AMZN": "#FF9900", "TSLA": "#CC0000",
    # Broad Market ETFs
    "SPY": "#EF4444", "QQQ": "#2563EB", "IWM": "#0EA5E9",
    # Indexes
    "SPX": "#111827", "NDX": "#A855F7", "RUT": "#22C55E", "VIX": "#A855F7",
    # Macro & Sector ETFs
    "GLD": "#EAB308", "SLV": "#94A3B8", "XLE": "#F97316", "XLF": "#22C55E",
    "TLT": "#3B82F6",
    # Financial Services
    "COIN": "#2563EB", "HOOD": "#22C55E", "SOFI": "#1E293B",
}

_FG_ON_LIGHT = "#0f172a"
_FG_ON_DARK = "#ffffff"

# Hex codes we consider "light" so the letter falls back to a dark tone.
_LIGHT_BACKGROUNDS = {"#FFFFFF", "#FAFAFA", "#F5F5F5"}


def _fg_for(bg: str) -> str:
    return _FG_ON_LIGHT if bg.upper() in _LIGHT_BACKGROUNDS else _FG_ON_DARK


@lru_cache(maxsize=128)
def logo_data_uri(ticker: str) -> str:
    """Return `data:image/svg+xml;base64,...` for a small rounded logo chip."""
    color = BRAND_COLORS.get(ticker.upper(), "#1f2937")
    letter = ticker.strip()[0].upper() if ticker.strip() else "?"
    fg = _fg_for(color)
    svg = (
        "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'>"
        f"<rect width='100' height='100' rx='16' ry='16' fill='{color}' "
        "stroke='rgba(255,255,255,0.08)' stroke-width='2'/>"
        f"<text x='50' y='50' text-anchor='middle' dominant-baseline='central' "
        f"font-family='Inter, system-ui, sans-serif' font-size='58' "
        f"font-weight='700' fill='{fg}'>{letter}</text>"
        "</svg>"
    )
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()


def brand_color(ticker: str) -> str:
    return BRAND_COLORS.get(ticker.upper(), "#1f2937")
