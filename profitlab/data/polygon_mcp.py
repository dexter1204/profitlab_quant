"""Polygon.io backend via the api.market MCP gateway.

api.market wraps Polygon as an MCP server (28 tools) instead of exposing
Polygon's REST API directly. This adapter speaks MCP and normalizes the
tool responses into the same schema `profitlab.data.__init__` documents.

Tool names come from Polygon's official MCP server (published at
polygon-io/mcp_polygon) and match what api.market forwards. If your
listing exposes different names, override them via env:

    POLYGON_MCP_TOOL_SPOT              default get_snapshot_ticker
    POLYGON_MCP_TOOL_AGGS              default get_aggs
    POLYGON_MCP_TOOL_OPTIONS_SNAPSHOT  default list_snapshot_options_chain

`list_available_tools()` calls tools/list on the server so you can see
what your gateway actually exposes.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd

from . import mcp_client


# ── tool-name resolution ───────────────────────────────────────────────────
# Candidate names per operation, tried in order. api.market and other MCP
# wrappers of Polygon rename tools inconsistently; we auto-discover by
# calling tools/list once and picking the first candidate that exists.
# You can force a specific name with the matching POLYGON_MCP_TOOL_* env var.
# api.market names tools by flattening the Polygon REST URL path to
# snake_case, e.g. GET /v3/snapshot/options/{underlyingAsset}
#                → get_v3_snapshot_options_underlyingasset
# Polygon's official MCP uses friendlier names, and other wrappers vary.
# We list both styles per operation so the resolver matches whichever
# lives on the current gateway.
_CANDIDATES = {
    "spot": [
        os.environ.get("POLYGON_MCP_TOOL_SPOT", ""),
        "get_v2_snapshot_locale_us_markets_stocks_tickers_stocksticker",
        "get_snapshot_ticker",
        "get_snapshot_all",
        "snapshot_ticker",
        "get_last_trade",
        "last_trade",
    ],
    "aggs": [
        os.environ.get("POLYGON_MCP_TOOL_AGGS", ""),
        "get_v2_aggs_ticker_stocksticker_range_multiplier_timespan_from_to",
        "get_aggs",
        "list_aggs",
        "aggregates",
    ],
    "options_snapshot": [
        os.environ.get("POLYGON_MCP_TOOL_OPTIONS_SNAPSHOT", ""),
        # api.market URL-path style — the chain snapshot endpoint
        "get_v3_snapshot_options_underlyingasset",
        "get_v3_snapshot_options_underlyingAsset",
        # Polygon official MCP naming
        "list_snapshot_options_chain",
        "get_snapshot_option_chain",
        # Other wrappers
        "options_snapshot_chain",
        "snapshot_options",
        "get_options_chain_snapshot",
    ],
}

# Must-have + must-not-have tokens for keyword-based fallback.
_KEYWORDS = {
    "spot":              {"require": ("snapshot",), "any": ("ticker", "tickers"),
                          "reject": ("options", "aggregates", "trades", "quotes",
                                     "open_close", "list", "contract")},
    "aggs":              {"require": ("aggs",), "any": (),
                          "reject": ("options", "grouped", "previous")},
    "options_snapshot":  {"require": ("snapshot", "option"), "any": (),
                          "reject": ("contract_", "open_close", "unified",
                                     "aggregates", "trades", "quotes",
                                     "reference", "previous")},
}

_resolved: dict[str, str] = {}
_available_names: list[str] | None = None
_tools_by_name: dict[str, dict] = {}


def _tool_arg_names(tool_name: str) -> set[str]:
    """Return the parameter names declared on `tool_name`'s inputSchema."""
    tool = _tools_by_name.get(tool_name) or {}
    schema = tool.get("inputSchema") or tool.get("input_schema") or {}
    props = schema.get("properties") or {}
    return set(props.keys())


def _pick_arg_key(tool_name: str, candidates: list[str]) -> str | None:
    """Given a list of candidate argument names, return the first one the
    tool's schema declares. Falls back to the first candidate when the
    schema is empty (some wrappers omit inputSchema)."""
    declared = _tool_arg_names(tool_name)
    if declared:
        for c in candidates:
            if c in declared:
                return c
        return None
    return candidates[0] if candidates else None


def _client() -> mcp_client.MCPClient:
    return mcp_client.from_env()


def list_available_tools() -> list[dict]:
    """One-shot discovery — call from the sidebar to see what your
    listing exposes. Also caches the tool names + schemas for the resolver."""
    global _available_names, _tools_by_name
    tools = _client().list_tools()
    _available_names = [t.get("name", "") for t in tools if t.get("name")]
    _tools_by_name = {t.get("name", ""): t for t in tools if t.get("name")}
    return tools


def _refresh_available_names() -> list[str]:
    global _available_names, _tools_by_name
    if _available_names is None:
        tools = _client().list_tools()
        _available_names = [t.get("name", "") for t in tools if t.get("name")]
        _tools_by_name = {t.get("name", ""): t for t in tools if t.get("name")}
    return _available_names


def _resolve_tool(op: str) -> str:
    """Return the actual tool name for `op` on the current server.
    Priority: exact candidate → keyword match with reject list → fail
    with a full list of what's available."""
    if op in _resolved:
        return _resolved[op]

    names = _refresh_available_names()
    name_set = set(names)

    # 1) Configured / hardcoded candidates — first exact match wins.
    for cand in _CANDIDATES.get(op, []):
        if cand and cand in name_set:
            _resolved[op] = cand
            return cand

    # 2) Keyword match — require ALL required tokens, none of the rejected
    #    ones, and any of the "any" tokens (if provided).
    kws = _KEYWORDS.get(op, {})
    require = kws.get("require", ())
    any_of = kws.get("any", ())
    reject = kws.get("reject", ())

    def _fits(name: str) -> bool:
        low = name.lower()
        if require and not all(k in low for k in require):
            return False
        if reject and any(k in low for k in reject):
            return False
        if any_of and not any(k in low for k in any_of):
            return False
        return True

    matches = sorted(n for n in name_set if _fits(n))
    if matches:
        picked = matches[0]
        _resolved[op] = picked
        return picked

    raise RuntimeError(
        f"polygon_mcp: could not resolve a tool for {op!r}.\n"
        f"  tried candidates: {[c for c in _CANDIDATES.get(op, []) if c]}\n"
        f"  keyword rules: {kws}\n"
        f"  Set POLYGON_MCP_TOOL_{op.upper()} to the correct name.\n"
        f"  Available tools on this gateway ({len(names)}):\n    - "
        + "\n    - ".join(sorted(names))
    )


def clear_resolved_cache() -> None:
    """Force re-discovery on next call — useful if you switch env vars."""
    global _resolved, _available_names, _tools_by_name
    _resolved = {}
    _available_names = None
    _tools_by_name = {}


# ── endpoints (same signatures as data/yfinance.py, data/polygon.py) ──────
def spot(ticker: str) -> float:
    ticker = ticker.upper()
    cli = _client()
    tool = _resolve_tool("spot")
    payload = cli.call_tool(tool, {"ticker": ticker, "market_type": "stocks"})
    # Response shape varies by MCP wrapper — try the common paths.
    px = _dig(payload, ["ticker", "min", "c"]) \
         or _dig(payload, ["ticker", "day", "c"]) \
         or _dig(payload, ["ticker", "prevDay", "c"]) \
         or _dig(payload, ["results", 0, "min", "c"]) \
         or _dig(payload, ["results", 0, "day", "c"])
    if px is None:
        raise RuntimeError(
            f"polygon_mcp.spot: couldn't extract a price from {_TOOL_SPOT!r} "
            f"response. Raw keys: {list(payload)[:8]}"
        )
    return float(px)


def price_history(ticker: str, period: str = "1y", interval: str = "1d") -> pd.Series:
    ticker = ticker.upper()
    span = _period_days(period)
    end = datetime.utcnow().date()
    start = end - timedelta(days=span)
    mult, timespan = _interval_to_polygon(interval)
    payload = _client().call_tool(_resolve_tool("aggs"), {
        "ticker": ticker, "multiplier": mult, "timespan": timespan,
        "from_": start.isoformat(), "to": end.isoformat(),
        "adjusted": True, "sort": "asc", "limit": 50000,
    })
    rows = _dig(payload, ["results"]) or []
    if not rows:
        raise RuntimeError(f"polygon_mcp: empty history for {ticker!r}")
    return pd.Series(
        [float(r["c"]) for r in rows],
        index=pd.to_datetime([r["t"] for r in rows], unit="ms"),
        name=ticker,
    )


def intraday_bars(ticker: str, interval: str = "1m", period: str = "1d") -> pd.DataFrame:
    ticker = ticker.upper()
    span = _period_days(period)
    end = datetime.utcnow().date()
    start = end - timedelta(days=max(span, 1))
    mult, timespan = _interval_to_polygon(interval)
    payload = _client().call_tool(_resolve_tool("aggs"), {
        "ticker": ticker, "multiplier": mult, "timespan": timespan,
        "from_": start.isoformat(), "to": end.isoformat(),
        "adjusted": True, "sort": "asc", "limit": 50000,
    })
    rows = _dig(payload, ["results"]) or []
    if not rows:
        raise RuntimeError(f"polygon_mcp: no intraday bars for {ticker!r}")
    return pd.DataFrame({
        "ts":     pd.to_datetime([r["t"] for r in rows], unit="ms"),
        "open":   [float(r["o"]) for r in rows],
        "high":   [float(r["h"]) for r in rows],
        "low":    [float(r["l"]) for r in rows],
        "close":  [float(r["c"]) for r in rows],
        "volume": [float(r.get("v", 0)) for r in rows],
    })


def option_chain(
    ticker: str,
    expiries: Optional[list[str]] = None,
    max_expiries: int = 4,
) -> pd.DataFrame:
    ticker = ticker.upper()
    tool = _resolve_tool("options_snapshot")

    # Underlying-ticker arg name varies by wrapper — pick the one this tool
    # actually declares in its inputSchema.
    underlying_key = _pick_arg_key(
        tool,
        ["underlyingAsset", "underlying_asset", "underlyingTicker",
         "underlying_ticker", "ticker", "symbol", "asset"],
    ) or "underlyingAsset"
    args = {underlying_key: ticker, "limit": 250}
    if expiries:
        # Expiration arg name likewise varies.
        exp_key = _pick_arg_key(
            tool, ["expirationDate", "expiration_date", "expiration"],
        ) or "expiration_date"
        args[exp_key] = ",".join(expiries)

    payload = _client().call_tool(tool, args)

    contracts = (_dig(payload, ["results"])
                 or _dig(payload, ["snapshots"])
                 or _dig(payload, ["data"])
                 or _dig(payload, ["contracts"])
                 or [])
    if not contracts and isinstance(payload, list):
        contracts = payload
    rows = []
    for opt in contracts:
        det = _dig(opt, ["details"]) or {}
        greeks = _dig(opt, ["greeks"]) or {}
        last_q = _dig(opt, ["last_quote"]) or {}
        day = _dig(opt, ["day"]) or {}
        strike = det.get("strike_price") or opt.get("strike_price")
        exp = det.get("expiration_date") or opt.get("expiration_date")
        kind = det.get("contract_type") or opt.get("contract_type")
        if strike is None or exp is None or kind not in ("call", "put"):
            continue
        rows.append({
            "strike": float(strike),
            "expiry": pd.Timestamp(exp),
            "type": kind,
            "oi": float(opt.get("open_interest") or 0.0),
            "iv": float(opt.get("implied_volatility") or np.nan),
            "delta": float(greeks.get("delta") or np.nan),
            "gamma": float(greeks.get("gamma") or np.nan),
            "bid": float(last_q.get("bid") or np.nan),
            "ask": float(last_q.get("ask") or np.nan),
            "last": float(day.get("close") or np.nan),
        })
    if not rows:
        # Include enough context to diagnose: the tool name we called, the
        # arg keys we used, and a preview of the raw payload shape so the
        # user can see whether the call was accepted but empty, or the
        # response is in a shape we didn't unpack.
        import json as _json
        preview = _json.dumps(payload, default=str)[:800]
        arg_hint = ", ".join(f"{k}={v!r}" for k, v in args.items())
        raise RuntimeError(
            f"polygon_mcp: empty options snapshot for {ticker!r}.\n"
            f"  tool: {tool}\n"
            f"  args: {arg_hint}\n"
            f"  payload preview: {preview}\n"
            f"If the payload has a 'results' array with contracts, share it and "
            f"we'll wire up the missing field mapping. If the response is empty, "
            f"your api.market plan may not include the options-chain snapshot."
        )
    df = pd.DataFrame(rows)

    if not expiries and max_expiries:
        keep = (
            df[["expiry"]].drop_duplicates().sort_values("expiry")
              .head(max_expiries)["expiry"].tolist()
        )
        df = df[df["expiry"].isin(keep)]

    df.loc[(df["iv"] <= 0.01) | (df["iv"] > 5.0), "iv"] = np.nan
    df["iv"] = df["iv"].fillna(df["iv"].median() if df["iv"].notna().any() else 0.22)
    return df.reset_index(drop=True)


# ── helpers ────────────────────────────────────────────────────────────────
def _dig(obj, path):
    """Safely walk a nested dict/list by keys/indices; returns None on any miss."""
    cur = obj
    for step in path:
        if cur is None:
            return None
        try:
            cur = cur[step]
        except (KeyError, IndexError, TypeError):
            return None
    return cur


_INTERVAL_MAP = {
    "1m": (1, "minute"), "2m": (2, "minute"), "3m": (3, "minute"),
    "5m": (5, "minute"), "15m": (15, "minute"), "30m": (30, "minute"),
    "60m": (60, "minute"), "1h": (1, "hour"), "1d": (1, "day"),
}


def _interval_to_polygon(interval: str) -> tuple[int, str]:
    if interval not in _INTERVAL_MAP:
        raise ValueError(f"Unsupported interval: {interval!r}")
    return _INTERVAL_MAP[interval]


def _period_days(period: str) -> int:
    return {
        "1d": 2, "5d": 7, "1mo": 35, "3mo": 95, "6mo": 185, "1y": 400,
        "2y": 760, "5y": 1830, "ytd": 400, "max": 7300,
    }.get(period, 400)
