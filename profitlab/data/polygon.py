"""Polygon.io-backed market-data loader.

Works with:
  1. polygon.io direct       → default base URL https://api.polygon.io
  2. api.market gateway      → set POLYGON_BASE_URL to the marketplace URL

Auth is sent both as `apiKey` query param and `Authorization: Bearer <key>`
header. polygon.io accepts either; api.market's gateway keeps whichever
form its listing requires — one of the two always works and the other
is ignored.

Env vars:
    POLYGON_API_KEY       your key (required)
    POLYGON_BASE_URL      override base URL; default https://api.polygon.io
    POLYGON_MAX_STRIKES   cap on returned option contracts per chain
                          (default 500 — Polygon paginates at 250)

Response schema is normalized to match `profitlab.data.__init__`.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd
import requests


DEFAULT_BASE_URL = "https://api.polygon.io"


def _base_url() -> str:
    return os.environ.get("POLYGON_BASE_URL", DEFAULT_BASE_URL).rstrip("/")


def _api_key() -> str:
    key = os.environ.get("POLYGON_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "POLYGON_API_KEY is not set. Set it before launching Streamlit — "
            "e.g. `setx POLYGON_API_KEY <your key>` on Windows, then reopen the shell."
        )
    return key


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "Authorization": f"Bearer {_api_key()}",
        "Accept": "application/json",
        "User-Agent": "profitlab-quant/0.1",
    })
    return s


def _get(path: str, params: Optional[dict] = None, _retries: int = 2) -> dict:
    """GET wrapper: prepends base URL if `path` is relative; always
    sends the API key as `apiKey` param too (some proxies strip
    Authorization).

    Retries on HTTP 429 with exponential backoff (respecting Retry-After
    when present). 429 happens on an Options-only plan when a *stocks*
    endpoint is called — those fall back to free-tier limits (5/min) —
    so the final message names that cause."""
    if path.startswith("http"):
        url = path
    else:
        url = f"{_base_url()}{path if path.startswith('/') else '/' + path}"
    params = dict(params or {})
    params.setdefault("apiKey", _api_key())

    delay = 2.0
    for attempt in range(_retries + 1):
        r = _session().get(url, params=params, timeout=15)
        if r.ok:
            return r.json()
        if r.status_code == 429 and attempt < _retries:
            retry_after = r.headers.get("Retry-After")
            wait = float(retry_after) if (retry_after or "").isdigit() else delay
            time.sleep(min(wait, 15.0))
            delay *= 2
            continue
        if r.status_code == 429:
            raise RuntimeError(
                f"Polygon 429 (rate limit) @ {path}. This is a STOCKS endpoint; "
                f"your Options plan doesn't entitle stocks data, so it falls back "
                f"to the free 5-requests/min limit. The gamma views (GEX/DEX, heat "
                f"maps, OI) use options endpoints and are unaffected — the Chart, "
                f"Market Heat Map and Portfolio Beta need a Stocks subscription."
            )
        raise RuntimeError(f"Polygon {r.status_code} @ {path}: {r.text[:200]}")
    raise RuntimeError(f"Polygon: exhausted retries @ {path}")


# ── endpoints ──────────────────────────────────────────────────────────────
def _contract_price(opt: dict) -> Optional[float]:
    """Best available price for one option contract: quote mid, else last
    trade, else day close."""
    lq = opt.get("last_quote") or {}
    bid, ask = lq.get("bid"), lq.get("ask")
    if bid and ask and bid > 0 and ask > 0:
        return (float(bid) + float(ask)) / 2.0
    lt = opt.get("last_trade") or {}
    if lt.get("price"):
        return float(lt["price"])
    day = opt.get("day") or {}
    if day.get("close"):
        return float(day["close"])
    return None


def _spot_from_parity(results: list[dict], r: float = 0.045) -> Optional[float]:
    """Implied underlying spot from put-call parity:  S = C - P + K·e^(-rT).
    Uses the front expiry and medians across strikes that have both a call
    and a put priced — accurate to the bid/ask spread, and derived purely
    from options data (works on an Options-only plan, market open or not)."""
    from datetime import datetime as _dt

    # group by expiry → strike → {call, put} price
    by_exp: dict[str, dict[float, dict[str, float]]] = {}
    for opt in results:
        det = opt.get("details") or {}
        exp = det.get("expiration_date")
        k = det.get("strike_price")
        kind = det.get("contract_type")
        if not exp or k is None or kind not in ("call", "put"):
            continue
        price = _contract_price(opt)
        if price is None:
            continue
        by_exp.setdefault(exp, {}).setdefault(float(k), {})[kind] = price

    if not by_exp:
        return None
    front = min(by_exp)  # nearest expiry date (ISO sorts chronologically)
    try:
        days = max((_dt.fromisoformat(front).date() - _dt.utcnow().date()).days, 0)
    except ValueError:
        days = 7
    t = max(days, 1) / 365.0
    disc = pow(2.718281828, -r * t)

    spots = []
    for k, legs in by_exp[front].items():
        if "call" in legs and "put" in legs:
            spots.append(legs["call"] - legs["put"] + k * disc)
    if not spots:
        return None
    spots.sort()
    return float(spots[len(spots) // 2])  # median — robust to a bad strike


def _spot_from_options(ticker: str) -> Optional[float]:
    return _spot_from_options_src(ticker)[0]


def _spot_from_options_src(ticker: str) -> tuple[Optional[float], str]:
    """Underlying spot on an Options-only plan, in order of accuracy:
      1. underlying_asset.price from the snapshot (the real delayed price)
      2. put-call parity across the front expiry (options-implied spot)
      3. max-OI strike (≈ ATM) as a last-resort proxy
    Never touches a stocks endpoint. Solo vencimientos vigentes (antes podía
    leer contratos ya vencidos)."""
    try:
        data = _get(f"/v3/snapshot/options/{ticker.upper()}", {
            "limit": 250, "expiration_date.gte": _today_ny().isoformat(),
            "sort": "expiration_date", "order": "asc",
        })
    except RuntimeError:
        return None, ""
    results = data.get("results", [])

    for opt in results:
        ua = opt.get("underlying_asset") or {}
        px = ua.get("price") or ua.get("value")
        if px and float(px) > 0:
            return float(px), "options_underlying"

    parity = _spot_from_parity(results)
    if parity and parity > 0:
        return parity, "options_parity"

    oi_by_strike: dict[float, float] = {}
    for opt in results:
        det = opt.get("details") or {}
        k = det.get("strike_price")
        if k is None:
            continue
        oi_by_strike[float(k)] = oi_by_strike.get(float(k), 0.0) + float(
            opt.get("open_interest") or 0.0
        )
    if oi_by_strike:
        return max(oi_by_strike.items(), key=lambda kv: kv[1])[0], "options_max_oi"
    return None, ""


# Cortocircuito: con planes Basic (fin de día, 5 llamadas/min) la barra de hoy
# nunca llega y los reintentos por 429 frenan cada respuesta. Tras un fallo se
# deja de pedir intradía a Massive durante PROFITLAB_INTRADAY_COOLDOWN s.
_INTRADAY_OFF_UNTIL: dict[str, float] = {}


def _intraday_cooldown() -> float:
    return float(os.environ.get("PROFITLAB_INTRADAY_COOLDOWN", "600"))


def intraday_available(ticker: str) -> bool:
    kind = "index" if ticker.upper() in _INDEX_TICKERS else "stock"
    return time.time() >= _INTRADAY_OFF_UNTIL.get(kind, 0.0)


def _mark_intraday_off(ticker: str) -> None:
    kind = "index" if ticker.upper() in _INDEX_TICKERS else "stock"
    _INTRADAY_OFF_UNTIL[kind] = time.time() + _intraday_cooldown()


def _spot_from_intraday(ticker: str) -> Optional[float]:
    """Último cierre de 1 minuto de HOY (hora NY). None si el plan no da
    intradía o la última barra no es de hoy."""
    if not intraday_available(ticker):
        return None
    try:
        df = intraday_bars(ticker, interval="1m", period="1d")
        if df is not None and len(df):
            last = df.iloc[-1]
            if pd.Timestamp(last["ts"]).date() == _today_ny() and float(last["close"]) > 0:
                return float(last["close"])
    except Exception:
        pass
    _mark_intraday_off(ticker)
    return None


def _spot_from_prev_close(ticker: str) -> Optional[float]:
    try:
        r = _get(f"/v2/aggs/ticker/{_agg_ticker(ticker)}/prev", {"adjusted": "true"})
        res = r.get("results") or []
        if res and res[0].get("c"):
            return float(res[0]["c"])
    except Exception:
        pass
    return None


def _spot_from_aggs(ticker: str) -> Optional[float]:
    """Compatibilidad: intradía de hoy y, si no, cierre anterior."""
    return _spot_from_intraday(ticker) or _spot_from_prev_close(ticker)


def spot(ticker: str) -> float:
    """Spot price. Prefers the latest aggregate close (accurate, matches the
    tape) and falls back to the options-snapshot underlying / parity / max-OI
    proxy on Options-only plans where stock aggregates aren't entitled. Some
    resellers return a stale `underlying_asset.price`, so aggregates first
    avoids a spot that disagrees with the chart and TradingView."""
    return spot_info(ticker)["price"]


# Origen del último spot calculado por ticker (para los metadatos de la API).
SPOT_SOURCE: dict[str, str] = {}


def spot_info(ticker: str) -> dict:
    """Spot + de dónde salió. `source`:
      aggregates            precio negociado real (agregados)
      options_underlying    precio del subyacente que trae el snapshot de opciones
      options_parity        implícito por paridad put-call (estimado)
      options_max_oi        strike con más open interest (estimación burda)"""
    ticker = ticker.upper()
    _api_key()  # raise the clear "POLYGON_API_KEY not set" error up front
    # Orden por calidad para un plan de opciones con retraso de 15 min:
    #   1. barra intradía de hoy (agregados)           → precio negociado
    #   2. subyacente del snapshot de opciones          → precio del proveedor
    #   3. paridad put-call con cotizaciones de opciones → estimado, mismo retraso
    #   4. cierre de ayer (planes Basic: fin de día)    → estimado y viejo
    #   5. strike con más OI                             → estimación burda
    px = _spot_from_intraday(ticker)
    if px and px > 0:
        SPOT_SOURCE[ticker] = "aggregates"
        return {"price": float(px), "source": "aggregates", "estimated": False}
    px, src = _spot_from_options_src(ticker)
    if px and src in ("options_underlying", "options_parity"):
        SPOT_SOURCE[ticker] = src
        return {"price": float(px), "source": src, "estimated": src != "options_underlying"}
    prev = _spot_from_prev_close(ticker)
    if prev and prev > 0:
        SPOT_SOURCE[ticker] = "prev_close"
        return {"price": float(prev), "source": "prev_close", "estimated": True}
    if px:
        SPOT_SOURCE[ticker] = src
        return {"price": float(px), "source": src, "estimated": True}
    raise RuntimeError(
        f"Polygon: couldn't derive a spot for {ticker!r} from aggregates or the "
        f"options snapshot — it may have no listed options on this plan."
    )


def price_history(ticker: str, period: str = "1y", interval: str = "1d") -> pd.Series:
    ticker = ticker.upper()
    span, unit = _parse_period(period)
    end = datetime.utcnow().date()
    start = end - timedelta(days=span)
    mult, timespan = _interval_to_polygon(interval)
    path = (f"/v2/aggs/ticker/{ticker}/range/{mult}/{timespan}/"
            f"{start.isoformat()}/{end.isoformat()}")
    data = _get(path, {"adjusted": "true", "sort": "asc", "limit": 50_000})
    rows = data.get("results") or []
    if not rows:
        raise RuntimeError(f"Polygon: empty history for {ticker!r}")
    ser = pd.Series(
        [float(r["c"]) for r in rows],
        index=pd.to_datetime([r["t"] for r in rows], unit="ms"),
        name=ticker,
    )
    return ser


MARKET_TZ = "America/New_York"


_INDEX_TICKERS = {"SPX", "NDX", "DJX", "RUT", "OEX", "VIX", "XSP"}


def _agg_ticker(ticker: str) -> str:
    """Massive/Polygon: los índices van con prefijo I: en los agregados."""
    t = ticker.upper()
    return f"I:{t}" if t in _INDEX_TICKERS else t


def _ms_to_ny(ms) -> pd.DatetimeIndex:
    """epoch-ms (UTC) → hora local de Nueva York sin tz (reloj del mercado)."""
    return (pd.to_datetime(ms, unit="ms", utc=True)
            .tz_convert(MARKET_TZ).tz_localize(None))


def _today_ny():
    return pd.Timestamp.now(tz=MARKET_TZ).date()


def intraday_bars(ticker: str, interval: str = "1m", period: str = "1d") -> pd.DataFrame:
    ticker = ticker.upper()
    if not intraday_available(ticker):
        raise RuntimeError(f"Polygon: intradía de {ticker!r} no disponible en el plan (en pausa).")
    span, _ = _parse_period(period)
    end = datetime.utcnow().date() + timedelta(days=1)  # incluye el día UTC en curso completo
    start = end - timedelta(days=max(span, 1))
    mult, timespan = _interval_to_polygon(interval)
    path = (f"/v2/aggs/ticker/{_agg_ticker(ticker)}/range/{mult}/{timespan}/"
            f"{start.isoformat()}/{end.isoformat()}")
    try:
        data = _get(path, {"adjusted": "true", "sort": "asc", "limit": 50_000}, _retries=0)
    except RuntimeError:
        _mark_intraday_off(ticker)
        raise
    rows = data.get("results") or []
    if not rows:
        _mark_intraday_off(ticker)
        raise RuntimeError(f"Polygon: no intraday bars for {ticker!r}")
    df = pd.DataFrame({
        # Polygon da epoch-ms en UTC. Se normaliza a hora de Nueva York (naive),
        # igual que yfinance/yahoo_direct: así todas las fuentes comparten el
        # mismo reloj de mercado y la ventana de sesión (09:30–16:00) es válida.
        "ts":     _ms_to_ny([r["t"] for r in rows]),
        "open":   [float(r["o"]) for r in rows],
        "high":   [float(r["h"]) for r in rows],
        "low":    [float(r["l"]) for r in rows],
        "close":  [float(r["c"]) for r in rows],
        "volume": [float(r.get("v", 0)) for r in rows],
    })
    return df


def option_chain(
    ticker: str,
    expiries: Optional[list[str]] = None,
    max_expiries: int = 4,
    spot: Optional[float] = None,
    strike_pct: Optional[float] = None,
) -> pd.DataFrame:
    """Snapshot de la cadena de opciones, paginado vía `next_url`.

    Antes se pedía la cadena sin filtro ni orden y se cortaba en 500 contratos:
    en subyacentes con muchos strikes eso dejaba 1–2 vencimientos (llenos de
    strikes lejanos) y en índices podía devolver solo contratos vencidos. Ahora:
      · solo vencimientos desde HOY (hora de Nueva York),
      · ordenado por vencimiento ascendente,
      · si se conoce el spot, solo strikes dentro de ±strike_pct alrededor,
      · se para al completar `max_expiries` vencimientos (el siguiente, que
        llegaría incompleto, se descarta)."""
    ticker = ticker.upper()
    max_contracts = int(os.environ.get("POLYGON_MAX_STRIKES", "6000"))
    rows: list[dict] = []
    path = f"/v3/snapshot/options/{ticker}"
    params: dict = {
        "limit": 250,
        "expiration_date.gte": _today_ny().isoformat(),
        "sort": "expiration_date",
        "order": "asc",
    }
    if spot and spot > 0:
        pct = strike_pct if strike_pct else float(os.environ.get("PROFITLAB_STRIKE_PCT", "0.12"))
        params["strike_price.gte"] = round(spot * (1 - pct), 2)
        params["strike_price.lte"] = round(spot * (1 + pct), 2)
    if expiries:
        params.pop("expiration_date.gte", None)
        params["expiration_date"] = ",".join(expiries)
    exp_seen: set = set()

    seen_urls: set[str] = set()
    while True:
        data = _get(path, params if not path.startswith("http") else None)
        for opt in data.get("results", []):
            det = opt.get("details", {})
            greeks = opt.get("greeks") or {}
            last_q = opt.get("last_quote") or {}
            day = opt.get("day") or {}
            strike = det.get("strike_price")
            exp = det.get("expiration_date")
            kind = det.get("contract_type")
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
                "volume": float(day.get("volume") or 0.0),
            })
            exp_seen.add(exp)
        if len(rows) >= max_contracts:
            break
        # Ordenado por vencimiento: con max_expiries+1 vistos, el último está
        # incompleto y los anteriores ya llegaron enteros.
        if not expiries and max_expiries and len(exp_seen) > max_expiries:
            break
        nxt = data.get("next_url")
        if not nxt or nxt in seen_urls:
            break
        seen_urls.add(nxt)
        path = nxt
        params = None

    if not rows:
        raise RuntimeError(f"Polygon: empty options snapshot for {ticker!r}")

    df = pd.DataFrame(rows)

    # If caller asked for a specific number of expiries, trim to the nearest N.
    if not expiries and max_expiries:
        keep = (
            df[["expiry"]].drop_duplicates().sort_values("expiry")
              .head(max_expiries)["expiry"].tolist()
        )
        df = df[df["expiry"].isin(keep)]

    # Defensa extra: nunca contratos vencidos (por si el proveedor ignora el filtro).
    df = df[df["expiry"] >= pd.Timestamp(_today_ny())]
    if df.empty:
        raise RuntimeError(f"Polygon: la cadena de {ticker!r} solo tiene vencimientos pasados")

    # IV: se descartan valores absurdos y los huecos se rellenan con la mediana
    # DEL MISMO VENCIMIENTO (documentado). Si no hay ninguna IV real, NO se
    # inventa una constante: se marca y los cálculos que la necesitan fallan
    # con "datos insuficientes".
    df.loc[(df["iv"] <= 0.01) | (df["iv"] > 5.0), "iv"] = np.nan
    df["iv_imputed"] = df["iv"].isna()
    df["iv"] = df.groupby("expiry")["iv"].transform(lambda s: s.fillna(s.median()))
    df.attrs["iv_missing"] = bool(df["iv"].isna().all())
    df.attrs["spot_used"] = spot
    return df.reset_index(drop=True)


# ── helpers ────────────────────────────────────────────────────────────────
_INTERVAL_MAP = {
    "1m": (1, "minute"), "2m": (2, "minute"), "3m": (3, "minute"),
    "5m": (5, "minute"), "15m": (15, "minute"), "30m": (30, "minute"),
    "60m": (60, "minute"), "1h": (1, "hour"), "1d": (1, "day"), "1wk": (1, "week"),
}


def _interval_to_polygon(interval: str) -> tuple[int, str]:
    if interval not in _INTERVAL_MAP:
        raise ValueError(f"Unsupported interval: {interval!r}")
    return _INTERVAL_MAP[interval]


def _parse_period(period: str) -> tuple[int, str]:
    """Convert yfinance-style period strings to (days, unit) roughly."""
    m = {
        "1d": (2, "d"), "5d": (7, "d"), "1mo": (35, "d"),
        "3mo": (95, "d"), "6mo": (185, "d"), "1y": (400, "d"),
        "2y": (760, "d"), "5y": (1830, "d"), "10y": (3650, "d"),
        "ytd": (400, "d"), "max": (7300, "d"),
    }
    return m.get(period, (400, "d"))
