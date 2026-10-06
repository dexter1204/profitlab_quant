"""Access control via the Profit Lab Aula Virtual.

The dashboard reuses the Aula accounts (shared `pl_token`, same domain) and
gates access by a **coupon** or a **payment**, both handled by the Aula's PHP
API against its own MySQL. This backend keeps no users and no database — on
each data request it asks the Aula whether the caller has quant access:

    GET {AULA_API_BASE}/quant/me   → { has_access, access_until, user, ... }

Env:
    AULA_API_BASE    default https://profitlab-academy.com/aulavirtual/api
    AULA_CACHE_TTL   seconds to cache a decision per token (default 60)
    AULA_TIMEOUT     HTTP timeout to the Aula API (default 8s)
"""

from __future__ import annotations

import os
import time

import requests
from fastapi import Header, HTTPException

AULA_API_BASE = os.environ.get(
    "AULA_API_BASE", "https://profitlab-academy.com/aulavirtual/api"
).rstrip("/")
_TTL = float(os.environ.get("AULA_CACHE_TTL", "60"))
_TIMEOUT = float(os.environ.get("AULA_TIMEOUT", "8"))

# A browser-like User-Agent — some shared hosts (SiteGround) block the default
# "python-requests" UA with an anti-bot HTML page, which isn't JSON.
_UA = os.environ.get(
    "AULA_USER_AGENT",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36 ProfitLabQuant/1.0",
)

_cache: dict[str, tuple[float, dict]] = {}


def resolve_access(token: str) -> dict:
    """Ask the Aula whether this token's user has quant access. Cached per
    token for _TTL seconds. Never raises; `error`/`detail` describe failures so
    the caller can return a clean response (with CORS headers)."""
    now = time.time()
    hit = _cache.get(token)
    if hit and now - hit[0] < _TTL:
        return hit[1]

    url = f"{AULA_API_BASE}/quant/me"
    try:
        r = requests.get(
            url,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json", "User-Agent": _UA},
            timeout=_TIMEOUT,
        )
    except requests.RequestException as e:
        return {"authenticated": False, "has_access": False, "user": None,
                "error": "aula_unreachable", "detail": f"{url}: {e}"}

    if r.status_code == 401:
        dec = {"authenticated": False, "has_access": False, "user": None, "error": None}
        _cache[token] = (now, dec)
        return dec
    if not r.ok:
        return {"authenticated": False, "has_access": False, "user": None,
                "error": "aula_error", "detail": f"HTTP {r.status_code} from {url}: {r.text[:160]}"}

    try:
        d = r.json() or {}
    except ValueError:
        # 2xx but the body isn't JSON (anti-bot HTML page, redirect, wrong path…)
        return {"authenticated": False, "has_access": False, "user": None,
                "error": "aula_badjson",
                "detail": f"Respuesta no-JSON de {url} (HTTP {r.status_code}): {r.text[:160]!r}"}

    dec = {
        "authenticated": True,
        "has_access": bool(d.get("has_access")),
        "user": d.get("user"),
        "access_until": d.get("access_until"),
        "error": None,
    }
    _cache[token] = (now, dec)
    return dec


def _token(authorization: str | None) -> str | None:
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    return authorization.split(" ", 1)[1].strip() or None


def require_access(authorization: str = Header(None)):
    """Gate for data endpoints: valid Aula session with active quant access."""
    tok = _token(authorization)
    if not tok:
        raise HTTPException(status_code=401, detail="No autenticado")
    dec = resolve_access(tok)
    if dec.get("error") in ("aula_unreachable", "aula_error", "aula_badjson"):
        raise HTTPException(status_code=503,
                            detail=dec.get("detail") or "No se pudo verificar el acceso con el Aula Virtual")
    if not dec["authenticated"]:
        raise HTTPException(status_code=401, detail="Sesión inválida o expirada")
    if not dec["has_access"]:
        raise HTTPException(status_code=403, detail="Acceso no activo. Canjea un cupón o adquiere el acceso.")
    return dec["user"]
