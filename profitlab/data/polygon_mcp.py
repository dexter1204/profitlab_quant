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


# ── configurable tool names ────────────────────────────────────────────────
_TOOL_SPOT = os.environ.get("POLYGON_MCP_TOOL_SPOT", "get_snapshot_ticker")
_TOOL_AGGS = os.environ.get("POLYGON_MCP_TOOL_AGGS", "get_aggs")
_TOOL_OPTIONS_SNAPSHOT = os.environ.get(
    "POLYGON_MCP_TOOL_OPTIONS_SNAPSHOT", "list_snapshot_options_chain"
)


def _client() -> mcp_client.MCPClient:
    return mcp_client.from_env()


def list_available_tools() -> list[dict]:
    """One-shot discovery — call from the sidebar to see what your
    api.market listing exposes so you can pin the right tool names."""
    return _client().list_tools()


# ── endpoints (same signatures as data/yfinance.py, data/polygon.py) ──────
def spot(ticker: str) -> float:
    ticker = ticker.upper()
    cli = _client()
    payload = cli.call_tool(_TOOL_SPOT, {"ticker": ticker, "market_type": "stocks"})
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
    payload = _client().call_tool(_TOOL_AGGS, {
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
    payload = _client().call_tool(_TOOL_AGGS, {
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
    args = {"underlying_asset": ticker, "limit": 250}
    if expiries:
        args["expiration_date"] = ",".join(expiries)
    payload = _client().call_tool(_TOOL_OPTIONS_SNAPSHOT, args)

    contracts = _dig(payload, ["results"]) or _dig(payload, ["snapshots"]) or []
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
        raise RuntimeError(
            f"polygon_mcp: empty options snapshot for {ticker!r}. "
            "Some starter plans don't include options snapshots — check your api.market "
            "listing entitlements or try list_available_tools() to see what's exposed."
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
