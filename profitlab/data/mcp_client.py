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
        self._session_id: str | None = None
        self._initialized = False
        self._session = requests.Session()
        # Streamable HTTP transport: server can respond with plain JSON or an
        # SSE stream at will, so we must advertise both media types.
        self._session.headers.update({
            "Authorization": f"Bearer {self.api_key}",
            "x-api-key": self.api_key,
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "User-Agent": "profitlab-quant/0.1 (mcp)",
        })

    # ── low-level ──────────────────────────────────────────────────────
    def _parse_sse(self, text: str) -> dict:
        """Extract the first `data:` payload from an SSE frame and JSON-decode."""
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("data:"):
                payload = line[5:].strip()
                if payload and payload != "[DONE]":
                    return json.loads(payload)
        raise RuntimeError(f"MCP SSE frame had no data: line — got: {text[:200]}")

    def _rpc(self, method: str, params: dict | None = None) -> Any:
        body: dict = {
            "jsonrpc": "2.0",
            "id": next(_ID_COUNTER),
            "method": method,
        }
        if params is not None:
            body["params"] = params

        headers: dict = {}
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id

        r = self._session.post(
            self.url, data=json.dumps(body), headers=headers, timeout=self.timeout
        )
        # Streamable HTTP: the server may return a session id on initialize
        # that we must echo on subsequent requests.
        sid = r.headers.get("Mcp-Session-Id") or r.headers.get("mcp-session-id")
        if sid:
            self._session_id = sid

        if not r.ok:
            raise RuntimeError(f"MCP {r.status_code} @ {method}: {r.text[:300]}")

        ctype = (r.headers.get("Content-Type") or "").lower()
        raw = r.text
        try:
            if "text/event-stream" in ctype:
                data = self._parse_sse(raw)
            else:
                data = json.loads(raw) if raw else {}
        except json.JSONDecodeError as e:
            raise RuntimeError(f"MCP {method} returned non-JSON: {raw[:300]}") from e

        if isinstance(data, dict) and data.get("error"):
            err = data["error"]
            raise RuntimeError(
                f"MCP error {err.get('code')}: {err.get('message')} @ {method}"
            )
        # Notifications (no id) can come back as {} — return an empty dict.
        return (data or {}).get("result", {}) if isinstance(data, dict) else {}

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        self.initialize()
        # Streamable HTTP requires the client to send `notifications/initialized`
        # after initialize before it can call tools/*.
        try:
            self._notify("notifications/initialized")
        except RuntimeError:
            pass  # some servers accept without it; ignore if the notify errors
        self._initialized = True

    def _notify(self, method: str, params: dict | None = None) -> None:
        """Fire a JSON-RPC notification (no id, no response expected)."""
        body: dict = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            body["params"] = params
        headers: dict = {}
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        self._session.post(
            self.url, data=json.dumps(body), headers=headers, timeout=self.timeout
        )

    def session_headers(self) -> dict:
        """Currently-set HTTP headers — exposed for tests / debugging."""
        return dict(self._session.headers)

    # ── protocol helpers ───────────────────────────────────────────────
    def initialize(self) -> dict:
        return self._rpc("initialize", {
            "protocolVersion": "2025-03-26",
            "capabilities": {"tools": {}},
            "clientInfo": {"name": "profitlab-quant", "version": "0.1"},
        })

    def list_tools(self) -> list[dict]:
        self._ensure_initialized()
        res = self._rpc("tools/list")
        return list(res.get("tools", []))

    def call_tool(self, name: str, arguments: dict | None = None) -> Any:
        self._ensure_initialized()
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


_CACHED_CLIENT: MCPClient | None = None
_CACHED_KEY: tuple[str, str] | None = None


def from_env() -> MCPClient:
    """Build (or reuse) a client from POLYGON_MCP_URL + POLYGON_MCP_KEY.

    The client is cached at module scope keyed by (url, key), so repeated
    Streamlit reruns reuse the same requests.Session (HTTP keep-alive)
    and the same MCP session id — no repeated `initialize` handshake.
    Rebuilds when the credentials change.
    """
    global _CACHED_CLIENT, _CACHED_KEY
    url = os.environ.get("POLYGON_MCP_URL", "").strip()
    key = os.environ.get("POLYGON_MCP_KEY", "").strip()
    if not url or not key:
        raise RuntimeError(
            "POLYGON_MCP_URL and POLYGON_MCP_KEY must be set before using "
            "the polygon_mcp vendor. Set them in profitlab/_credentials.py "
            "(local, git-ignored) or export them as env vars."
        )
    creds = (url, key)
    if _CACHED_CLIENT is not None and _CACHED_KEY == creds:
        return _CACHED_CLIENT
    _CACHED_CLIENT = MCPClient(url, key)
    _CACHED_KEY = creds
    return _CACHED_CLIENT
