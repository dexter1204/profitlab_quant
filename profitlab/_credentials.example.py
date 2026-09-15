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
    "PROFITLAB_VENDOR": "polygon_mcp",

    # polygon.io direct — Starter plan or higher
    "POLYGON_API_KEY": "",
    "POLYGON_BASE_URL": "https://api.polygon.io",

    # polygon via api.market MCP gateway
    "POLYGON_MCP_URL": "https://prod.api.market/api/mcp/polygon.io/polygon",
    "POLYGON_MCP_KEY": "",

    # Force specific MCP tool names (leave empty for auto-discovery)
    "POLYGON_MCP_TOOL_SPOT": "",
    "POLYGON_MCP_TOOL_AGGS": "",
    "POLYGON_MCP_TOOL_OPTIONS_SNAPSHOT": "",
}
