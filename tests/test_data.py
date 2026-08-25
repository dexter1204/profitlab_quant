"""Vendor dispatcher + polygon adapter sanity checks (no network)."""

import os
from unittest.mock import patch

import pandas as pd
import pytest

from profitlab import data


def test_dispatcher_default_is_yfinance():
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("PROFITLAB_VENDOR", None)
        assert data.vendor_name() == "yfinance"


def test_dispatcher_selects_polygon_when_env_set():
    with patch.dict(os.environ, {"PROFITLAB_VENDOR": "polygon"}):
        assert data.vendor_name() == "polygon"


def test_dispatcher_rejects_unknown_vendor():
    with patch.dict(os.environ, {"PROFITLAB_VENDOR": "bogus"}):
        with pytest.raises(ValueError, match="Unknown PROFITLAB_VENDOR"):
            data.spot("QQQ")


def test_polygon_requires_api_key():
    from profitlab.data import polygon as polygon_mod
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("POLYGON_API_KEY", None)
        with pytest.raises(RuntimeError, match="POLYGON_API_KEY"):
            polygon_mod.spot("QQQ")


def test_polygon_normalizes_option_chain_snapshot():
    """The chain builder must convert Polygon's snapshot response into
    the [strike, expiry, type, oi, iv, bid, ask, last] schema used by
    the rest of the library."""
    from profitlab.data import polygon as polygon_mod

    fake_response = {
        "results": [
            {
                "details": {"strike_price": 740.0, "expiration_date": "2026-09-05",
                            "contract_type": "call"},
                "open_interest": 1200,
                "implied_volatility": 0.245,
                "greeks": {"delta": 0.55, "gamma": 0.012},
                "last_quote": {"bid": 3.10, "ask": 3.30},
                "day": {"close": 3.20},
            },
            {
                "details": {"strike_price": 740.0, "expiration_date": "2026-09-05",
                            "contract_type": "put"},
                "open_interest": 900,
                "implied_volatility": 0.28,
                "greeks": {"delta": -0.44, "gamma": 0.011},
                "last_quote": {"bid": 3.55, "ask": 3.70},
                "day": {"close": 3.62},
            },
        ],
        "next_url": None,
    }
    with patch.dict(os.environ, {"POLYGON_API_KEY": "test_key"}):
        with patch.object(polygon_mod, "_get", return_value=fake_response):
            df = polygon_mod.option_chain("QQQ", max_expiries=1)

    assert {"strike", "expiry", "type", "oi", "iv", "bid", "ask", "last"}.issubset(df.columns)
    assert len(df) == 2
    assert set(df["type"]) == {"call", "put"}
    assert df["strike"].iloc[0] == 740.0
    assert df["iv"].between(0.2, 0.3).all()


def test_mcp_client_wraps_jsonrpc_body_and_headers():
    """RPC call must send Bearer + x-api-key headers, JSON-RPC 2.0 body,
    and unwrap MCP's content envelope back to a Python object."""
    from profitlab.data import mcp_client

    class FakeResponse:
        ok = True
        text = ('{"jsonrpc":"2.0","id":1,"result":{"content":'
                '[{"type":"text","text":"{\\"ticker\\":{\\"min\\":{\\"c\\":741.23}}}"}]}}')
        headers = {"Content-Type": "application/json"}

    cli = mcp_client.MCPClient("https://x/mcp", "key123")
    cli._initialized = True  # skip handshake for this unit test

    captured = {}
    def fake_post(url, data, headers=None, timeout=None):
        captured["url"] = url
        captured["body"] = data
        captured["headers"] = dict(cli._session.headers)
        return FakeResponse()

    with patch.object(cli._session, "post", side_effect=fake_post):
        out = cli.call_tool("get_snapshot_ticker", {"ticker": "QQQ"})

    assert out == {"ticker": {"min": {"c": 741.23}}}
    assert captured["url"] == "https://x/mcp"
    import json
    body = json.loads(captured["body"])
    assert body["jsonrpc"] == "2.0"
    assert body["method"] == "tools/call"
    assert body["params"]["name"] == "get_snapshot_ticker"
    assert captured["headers"]["Authorization"] == "Bearer key123"
    assert captured["headers"]["x-api-key"] == "key123"


def test_mcp_client_parses_sse_and_dual_accept_header():
    """Streamable HTTP transport — server can return SSE or JSON. Client
    must accept both and unwrap the SSE data: line."""
    from profitlab.data import mcp_client

    class SSEResponse:
        ok = True
        text = 'event: message\ndata: {"jsonrpc":"2.0","id":1,"result":{"tools":[{"name":"get_aggs"}]}}\n\n'
        headers = {"Content-Type": "text/event-stream", "Mcp-Session-Id": "sess-abc"}

    cli = mcp_client.MCPClient("https://x/mcp", "key123")
    # Force initialized so list_tools() doesn't try the handshake first.
    cli._initialized = True

    with patch.object(cli._session, "post", return_value=SSEResponse()):
        tools = cli.list_tools()

    assert cli.session_headers()["Accept"] == "application/json, text/event-stream"
    assert cli._session_id == "sess-abc"  # session id captured from response
    assert [t["name"] for t in tools] == ["get_aggs"]


def test_mcp_client_echoes_session_id_on_followup_requests():
    from profitlab.data import mcp_client

    class InitResponse:
        ok = True
        text = '{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2025-03-26"}}'
        headers = {"Content-Type": "application/json", "Mcp-Session-Id": "sess-xyz"}

    class ToolsResponse:
        ok = True
        text = '{"jsonrpc":"2.0","id":2,"result":{"tools":[]}}'
        headers = {"Content-Type": "application/json"}

    cli = mcp_client.MCPClient("https://x/mcp", "k")
    calls: list = []
    def fake_post(url, data, headers=None, timeout=None):
        calls.append(dict(headers or {}))
        return InitResponse() if len(calls) <= 2 else ToolsResponse()

    with patch.object(cli._session, "post", side_effect=fake_post):
        cli.list_tools()  # triggers initialize → notify → tools/list

    # 3rd call (tools/list) must carry the Mcp-Session-Id header captured on init.
    assert calls[-1].get("Mcp-Session-Id") == "sess-xyz"


def test_polygon_mcp_dispatcher_registered():
    """The dispatcher must resolve `polygon_mcp` to the mcp adapter."""
    with patch.dict(os.environ, {"PROFITLAB_VENDOR": "polygon_mcp"}):
        assert data.vendor_name() == "polygon_mcp"


def test_polygon_mcp_spot_extracts_price_from_snapshot_shape():
    """The adapter must find a price whether it's under min.c, day.c, or prevDay.c."""
    from profitlab.data import polygon_mcp

    for shape in (
        {"ticker": {"min": {"c": 500.10}}},
        {"ticker": {"day": {"c": 500.20}}},
        {"ticker": {"prevDay": {"c": 500.30}}},
        {"results": [{"min": {"c": 500.40}}]},
    ):
        with patch.dict(os.environ,
                        {"POLYGON_MCP_URL": "https://x/mcp",
                         "POLYGON_MCP_KEY": "test"}):
            with patch.object(polygon_mcp, "_client") as fake_client:
                fake_client.return_value.call_tool.return_value = shape
                px = polygon_mcp.spot("QQQ")
        assert 500.0 < px < 501.0


def test_polygon_intraday_bars_normalizes_aggs():
    from profitlab.data import polygon as polygon_mod

    fake = {
        "results": [
            {"t": 1_700_000_000_000, "o": 740.1, "h": 740.5, "l": 739.9, "c": 740.2, "v": 12000},
            {"t": 1_700_000_060_000, "o": 740.2, "h": 740.7, "l": 740.0, "c": 740.6, "v": 15000},
        ]
    }
    with patch.dict(os.environ, {"POLYGON_API_KEY": "test_key"}):
        with patch.object(polygon_mod, "_get", return_value=fake):
            df = polygon_mod.intraday_bars("QQQ", interval="1m", period="1d")
    assert list(df.columns) == ["ts", "open", "high", "low", "close", "volume"]
    assert len(df) == 2
    assert df["close"].iloc[-1] == 740.6
