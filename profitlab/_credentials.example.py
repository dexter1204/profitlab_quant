"""Local credentials override (opt-in).

Copy this file to `profitlab/_credentials.py` and fill in your keys.
`_credentials.py` is git-ignored so your keys never reach GitHub. The
dispatcher and MCP client will pick these up automatically at boot —
no UI, no sidebar fields, no per-session paste.

Precedence (highest wins):
  1. OS environment variables (setx PROFITLAB_VENDOR=...)
  2. Streamlit Cloud secrets (.streamlit/secrets.toml or App settings)
  3. This file (profitlab/_credentials.py)

Only set the ones you use — leave the rest as empty strings.
"""

CREDENTIALS: dict[str, str] = {
    # Default is yfinance so an unedited copy of this file still runs the
    # app end-to-end (delayed retail data, no key needed). Change to
    # "polygon" or "polygon_mcp" when you fill in the corresponding keys.
    "PROFITLAB_VENDOR": "yfinance",

    # Polygon.io — rebranded to Massive.com (Oct 2025). The REST API is the
    # same and the same key works on both bases:
    #   https://api.massive.com   (new default)
    #   https://api.polygon.io    (still supported)
    # Options-plan keys cover the chain (OI/IV/greeks) and the spot embedded
    # in the options snapshot; underlying price history (chart/beta/heatmap)
    # needs a Stocks plan.
    "POLYGON_API_KEY": "",
    "POLYGON_BASE_URL": "https://api.massive.com",

    # polygon via api.market MCP gateway (alternative to direct REST)
    "POLYGON_MCP_URL": "https://prod.api.market/api/mcp/polygon.io/polygon",
    "POLYGON_MCP_KEY": "",

    # Force specific MCP tool names (leave empty for auto-discovery)
    "POLYGON_MCP_TOOL_SPOT": "",
    "POLYGON_MCP_TOOL_AGGS": "",
    "POLYGON_MCP_TOOL_OPTIONS_SNAPSHOT": "",
}
