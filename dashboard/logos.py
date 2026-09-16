"""Stock-ticker logos.

Two sources, tried in order:

1. `logo_url(ticker)` — a live PNG served by financialmodelingprep.com's
   free image endpoint (`/image-stock/{TICKER}.png`). Plotly serializes
   URLs into the figure spec, and the *user's browser* fetches them at
   render time — so this works from Streamlit as long as the user has
   internet, even if our data toggle is on "demo" (chain data is offline
   but images can still load).

2. `logo_data_uri(ticker)` — a deterministic SVG chip (brand color +
   ticker initial) serialized as `data:image/svg+xml;base64,...`. Used
   as a fallback for tickers we don't have a remote URL for, or when the
   caller opts into fully-offline rendering.

Colors follow public brand identities; keep the palette conservative
(single hex) so the fallback chip reads as an icon rather than a rendered
logo.
"""

from __future__ import annotations

import base64
from functools import lru_cache


_REMOTE_LOGO_TEMPLATE = "https://financialmodelingprep.com/image-stock/{ticker}.png"

# Tickers that don't have a listed equity backing them (indexes, some ETFs
# not indexed by FMP). Skip the remote lookup and go straight to the SVG chip.
_REMOTE_LOGO_SKIP = {"SPX", "NDX", "RUT", "VIX"}


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


def logo_url(ticker: str) -> str | None:
    """URL of a public logo PNG, or None when we don't want a remote lookup."""
    tk = ticker.strip().upper()
    if not tk or tk in _REMOTE_LOGO_SKIP:
        return None
    return _REMOTE_LOGO_TEMPLATE.format(ticker=tk)


def logo_source(ticker: str, prefer_remote: bool = True) -> str:
    """Best available logo source for `ticker` — remote URL or embedded SVG."""
    if prefer_remote:
        url = logo_url(ticker)
        if url:
            return url
    return logo_data_uri(ticker)


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
