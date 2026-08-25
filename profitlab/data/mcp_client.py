"""Minimal JSON-RPC 2.0 client for MCP (Model Context Protocol) servers
served over plain HTTP POST.

Used by `profitlab.data.polygon_mcp` to hit api.market's MCP endpoint
for Polygon.io. Keeps the surface small — enough to `initialize`,
`tools/list`, and `tools/call`. No SSE / WebSocket / session state.

Auth: sends the key both as `Authorization: Bearer <key>` and
`x-api-key: <key>` — api.market accepts the latter, polygon.io direct
would accept the former; either or both are ignored if not required.
"""

from __future__ import annotations

import itertools
import json
import os
from typing import Any

import requests


_ID_COUNTER = itertools.count(1)


class MCPClient:
    def __init__(self, url: str, api_key: str, timeout: float = 20.0):
        self.url = url.rstrip("/")
        self.api_key = api_key.strip()
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {self.api_key}",
            "x-api-key": self.api_key,
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "profitlab-quant/0.1 (mcp)",
        })

    def _rpc(self, method: str, params: dict | None = None) -> Any:
        body = {
            "jsonrpc": "2.0",
            "id": next(_ID_COUNTER),
            "method": method,
        }
        if params is not None:
            body["params"] = params
        r = self._session.post(self.url, data=json.dumps(body), timeout=self.timeout)
        if not r.ok:
            raise RuntimeError(f"MCP {r.status_code} @ {method}: {r.text[:300]}")
        try:
            data = r.json()
        except Exception as e:
            raise RuntimeError(f"MCP {method} returned non-JSON: {r.text[:300]}") from e
        if "error" in data and data["error"]:
            err = data["error"]
            raise RuntimeError(
                f"MCP error {err.get('code')}: {err.get('message')} @ {method}"
            )
        return data.get("result", {})

    # ── protocol helpers ───────────────────────────────────────────────
    def initialize(self) -> dict:
        return self._rpc("initialize", {
            "protocolVersion": "2025-03-26",
            "capabilities": {"tools": {}},
            "clientInfo": {"name": "profitlab-quant", "version": "0.1"},
        })

    def list_tools(self) -> list[dict]:
        res = self._rpc("tools/list")
        return list(res.get("tools", []))

    def call_tool(self, name: str, arguments: dict | None = None) -> Any:
        """Invoke a tool. Unwraps MCP's `content` envelope: for a JSON
        tool the payload lives in `content[0].text` as a JSON string;
        for text-only tools it's plain text. Returns the decoded object
        (dict / list) if the text is JSON, else the raw string."""
        res = self._rpc("tools/call", {
            "name": name,
            "arguments": arguments or {},
        })
        content = res.get("content") or []
        if not content:
            return res
        first = content[0]
        text = first.get("text", "")
        # Try JSON — many MCP tools return stringified JSON.
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return text


def from_env() -> MCPClient:
    """Build a client from POLYGON_MCP_URL + POLYGON_MCP_KEY env vars."""
    url = os.environ.get("POLYGON_MCP_URL", "").strip()
    key = os.environ.get("POLYGON_MCP_KEY", "").strip()
    if not url or not key:
        raise RuntimeError(
            "POLYGON_MCP_URL and POLYGON_MCP_KEY must be set before using "
            "the polygon_mcp vendor. Example values from api.market:\n"
            "  POLYGON_MCP_URL=https://prod.api.market/api/mcp/polygon.io/polygon\n"
            "  POLYGON_MCP_KEY=<the API key api.market issued for the listing>"
        )
    return MCPClient(url, key)
