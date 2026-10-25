"""GexBot (NFA) Classic API client.

Pulls the GexBot "classic" analytics — per-strike GEX, zero gamma, major
positive/negative levels, net GEX and max-change priors — from the official
REST API (https://api.gex.bot/v2) so the dashboard can render the GexBot
classic chart from GexBot's own numbers.

Auth: a per-product Bearer key. Set it server-side:
    GEXBOT_API_KEY     your GexBot classic API key (required)
    GEXBOT_BASE_URL    override base URL (default https://api.gex.bot/v2)

LICENSING NOTE (important): a standard GexBot subscription licenses the data
for PERSONAL, non-commercial use. Redistributing/broadcasting it (e.g. showing
it to Aula students) requires a COMMERCIAL license from GexBot
(admin@gexbot.com). This client only talks to the API; respecting the licence
is the operator's responsibility.

API shape (from the official OpenAPI spec, nfa-llc/gexbot-openapi):
    GET /{ticker}/classic/{category}            → chart snapshot
    GET /{ticker}/classic/{category}/majors     → majors only
    GET /{ticker}/classic/{category}/maxchange  → max-change priors
    GET /tickers · GET /classic/categories · GET /whoami
`category` ∈ full | gex_full | zero | gex_zero | one | gex_one.
`strikes` rows are [strike, gex_vol, gex_oi, priors]; priors holds the
1/5/10/15/30-minute lookback GEX values.
"""

from __future__ import annotations

import gzip
import io
import json
import os
import time
import zipfile
from typing import Optional

import requests

DEFAULT_BASE_URL = "https://api.gex.bot/v2"
USER_AGENT = "profitlab-quant/1.0 (+https://profitlab-academy.com)"
VALID_CATEGORIES = ("full", "gex_full", "zero", "gex_zero", "one", "gex_one")


def _base_url() -> str:
    return os.environ.get("GEXBOT_BASE_URL", DEFAULT_BASE_URL).rstrip("/")


def _api_key() -> str:
    key = os.environ.get("GEXBOT_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "GEXBOT_API_KEY no está configurada. Ponla en el backend (Render → "
            "Environment) con tu clave de la API de GexBot (plan Classic)."
        )
    return key


def _get(path: str, _retries: int = 2) -> dict:
    """GET {base}{path} with Bearer auth + descriptive User-Agent (GexBot
    requires both). Retries on HTTP 429 with exponential backoff."""
    url = path if path.startswith("http") else f"{_base_url()}{path if path.startswith('/') else '/' + path}"
    headers = {
        "Authorization": f"Bearer {_api_key()}",
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    }
    delay = 2.0
    for attempt in range(_retries + 1):
        r = requests.get(url, headers=headers, timeout=15)
        if r.ok:
            return r.json()
        if r.status_code == 429 and attempt < _retries:
            retry_after = r.headers.get("Retry-After")
            wait = float(retry_after) if (retry_after or "").isdigit() else delay
            time.sleep(min(wait, 15.0))
            delay *= 2
            continue
        if r.status_code in (401, 403):
            raise RuntimeError(
                f"GexBot {r.status_code}: clave inválida o el plan no cubre este "
                f"endpoint ({path}). Revisa GEXBOT_API_KEY y tu suscripción."
            )
        raise RuntimeError(f"GexBot {r.status_code} @ {path}: {r.text[:200]}")
    raise RuntimeError(f"GexBot: reintentos agotados @ {path}")


def _norm_category(category: str) -> str:
    c = (category or "full").strip().lower()
    return c if c in VALID_CATEGORIES else "full"


def _strikes_rows(raw: list) -> list[dict]:
    """Normalize the `strikes` array ([strike, gex_vol, gex_oi, priors]) into
    dicts, sorted by strike. `priors` are the 1/5/10/15/30-minute lookback
    GEX values for that strike (a 0 means "no data yet" at that lookback)."""
    out = []
    for row in raw or []:
        if not isinstance(row, (list, tuple)) or len(row) < 3:
            continue
        try:
            strike = float(row[0])
            gex_vol = float(row[1])
            gex_oi = float(row[2])
        except (TypeError, ValueError):
            continue
        priors = []
        if len(row) >= 4 and isinstance(row[3], (list, tuple)):
            for p in row[3]:
                try:
                    priors.append(float(p))
                except (TypeError, ValueError):
                    priors.append(0.0)
        out.append({"strike": strike, "gex_vol": gex_vol, "gex_oi": gex_oi,
                    "priors": priors})
    out.sort(key=lambda d: d["strike"])
    return out


# The per-strike `priors` array is ordered 1, 5, 10, 15, 30 minutes.
PRIOR_WINDOWS = (1, 5, 10, 15, 30)


def classic(ticker: str, category: str = "full") -> dict:
    """Classic chart snapshot for `ticker`: spot, zero gamma, major +/-,
    net GEX and the per-strike GEX profile."""
    t = ticker.upper().strip()
    cat = _norm_category(category)
    data = _get(f"/{t}/classic/{cat}")
    return {
        "ticker": t,
        "category": cat,
        "timestamp": data.get("timestamp"),
        "spot": data.get("spot"),
        "zero_gamma": data.get("zero_gamma"),
        "major_pos_oi": data.get("major_pos_oi"),
        "major_pos_vol": data.get("major_pos_vol"),
        "major_neg_oi": data.get("major_neg_oi"),
        "major_neg_vol": data.get("major_neg_vol"),
        "net_gex_oi": data.get("sum_gex_oi"),
        "net_gex_vol": data.get("sum_gex_vol"),
        "delta_risk_reversal": data.get("delta_risk_reversal"),
        "min_dte": data.get("min_dte"),
        "sec_min_dte": data.get("sec_min_dte"),
        "max_priors": data.get("max_priors"),
        "strikes": _strikes_rows(data.get("strikes")),
    }


def majors(ticker: str, category: str = "full") -> dict:
    t = ticker.upper().strip()
    return _get(f"/{t}/classic/{_norm_category(category)}/majors")


def maxchange(ticker: str, category: str = "full") -> dict:
    """Max-change GEX priors: current + 1/5/10/15/30-minute lookbacks, each a
    list of [strike, gex] (or values) per the API."""
    t = ticker.upper().strip()
    return _get(f"/{t}/classic/{_norm_category(category)}/maxchange")


def expiries(ticker: str) -> dict:
    """Valid option expiries for the realtime expiry groups (YYYY-MM-DD)."""
    return _get(f"/options/{ticker.upper().strip()}/expiries")


def _zip_category(category: str) -> str:
    """Map a category alias to the `gex_full|gex_zero|gex_one` form used inside
    the hist/eod ZIP file paths and by the API routes."""
    c = (category or "full").strip().lower()
    return {"full": "gex_full", "zero": "gex_zero", "one": "gex_one"}.get(c, c)


def _get_bytes(path: str, timeout: int = 120) -> bytes:
    """GET raw bytes (for the hist/eod ZIP), Bearer + descriptive UA."""
    url = path if path.startswith("http") else f"{_base_url()}{path if path.startswith('/') else '/' + path}"
    headers = {
        "Authorization": f"Bearer {_api_key()}",
        "User-Agent": USER_AGENT,
    }
    r = requests.get(url, headers=headers, timeout=timeout)
    if r.status_code in (401, 403):
        raise RuntimeError(
            f"GexBot {r.status_code}: la clave no cubre hist/eod de {path}. "
            f"hist/eod está en el tier Classic; revisa tu suscripción."
        )
    if not r.ok:
        raise RuntimeError(f"GexBot {r.status_code} @ {path}: {r.text[:200]}")
    return r.content


def hist_eod_series(ticker: str, category: str = "full",
                    target_points: int = 600) -> dict:
    """Intraday series for the latest end-of-day recording.

    GexBot's `/hist/eod/{ticker}` returns a ZIP with one gzipped JSON per
    category (gex_full / gex_zero / gex_one). Each is a LIST of ~16k classic
    snapshots across that day (≈1.5s cadence). We pick the requested category,
    downsample to ~`target_points` evenly-spaced points and keep only the
    scalar levels + spot, so the replay payload stays light.

    Returns {ticker, category, date, points:[{t, spot, zero_gamma,
    major_pos_oi, major_neg_oi, major_pos_vol, major_neg_vol, net_gex_oi,
    net_gex_vol}]}.
    """
    t = ticker.upper().strip()
    zcat = _zip_category(category)
    raw = _get_bytes(f"/hist/eod/{t}")
    zf = zipfile.ZipFile(io.BytesIO(raw))
    # Find the entry for this category, e.g. ".../classic/gex_full/DATE_....json.gz"
    name = next((n for n in zf.namelist()
                 if f"/classic/{zcat}/" in n and n.endswith(".json.gz")), None)
    if name is None:
        raise RuntimeError(
            f"hist/eod de {t}: no hay grabación para la categoría {zcat}.")
    with zf.open(name) as fh:
        snaps = json.loads(gzip.decompress(fh.read()))
    if not isinstance(snaps, list) or not snaps:
        raise RuntimeError(f"hist/eod de {t}: grabación vacía.")

    # Date from the filename (DATE_TICKER_classic_cat.json.gz).
    base = name.rsplit("/", 1)[-1]
    date = base.split("_", 1)[0]

    n = len(snaps)
    step = max(1, n // max(1, target_points))
    points = []
    for i in range(0, n, step):
        s = snaps[i]
        if not isinstance(s, dict):
            continue
        points.append({
            "t": s.get("timestamp"),
            "spot": s.get("spot"),
            "zero_gamma": s.get("zero_gamma"),
            "major_pos_oi": s.get("major_pos_oi"),
            "major_neg_oi": s.get("major_neg_oi"),
            "major_pos_vol": s.get("major_pos_vol"),
            "major_neg_vol": s.get("major_neg_vol"),
            "net_gex_oi": s.get("sum_gex_oi"),
            "net_gex_vol": s.get("sum_gex_vol"),
        })
    # Always include the very last snapshot (session close).
    if (n - 1) % step != 0:
        s = snaps[-1]
        if isinstance(s, dict):
            points.append({
                "t": s.get("timestamp"), "spot": s.get("spot"),
                "zero_gamma": s.get("zero_gamma"),
                "major_pos_oi": s.get("major_pos_oi"),
                "major_neg_oi": s.get("major_neg_oi"),
                "major_pos_vol": s.get("major_pos_vol"),
                "major_neg_vol": s.get("major_neg_vol"),
                "net_gex_oi": s.get("sum_gex_oi"),
                "net_gex_vol": s.get("sum_gex_vol"),
            })
    return {"ticker": t, "category": zcat, "date": date,
            "count_raw": n, "points": points}


def tickers() -> list:
    return _get("/tickers")


def categories(package: str = "classic") -> list:
    return _get(f"/{package}/categories")


def whoami() -> dict:
    """Verify the API key and see the account/plan it belongs to."""
    return _get("/whoami")


def is_configured() -> bool:
    return bool(os.environ.get("GEXBOT_API_KEY", "").strip())
