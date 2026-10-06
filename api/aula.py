"""Single sign-on with the Profit Lab Aula Virtual.

The dashboard reuses the Aula's accounts: students log in once in the Aula
(profitlab-academy.com/aulavirtual), their JWT is stored in the shared
`pl_token` localStorage key (same origin), and the quant frontend sends it
here as a Bearer token.

This backend does NOT keep its own users or touch MySQL. It delegates to the
Aula's PHP API:
    GET {AULA_API_BASE}/auth/me          → validates the token, returns the user
    GET {AULA_API_BASE}/enrollments/me   → the user's course enrollments

Access to the quant dashboard = being enrolled in the "ProfitLab Quant"
course (matched by id, exact title, or slug prefix), or being an Aula admin.

Env vars:
    AULA_API_BASE      default https://profitlab-academy.com/aulavirtual/api
    QUANT_COURSE_ID    exact course id (most precise); optional
    QUANT_COURSE_TITLE default "ProfitLab Quant" (matched case-insensitively)
    AULA_CACHE_TTL     seconds to cache an access decision per token (default 120)
    AULA_TIMEOUT       HTTP timeout to the Aula API (default 8s)
"""

from __future__ import annotations

import os
import time

import requests
from fastapi import Header, HTTPException

AULA_API_BASE = os.environ.get(
    "AULA_API_BASE", "https://profitlab-academy.com/aulavirtual/api"
).rstrip("/")
QUANT_COURSE_ID = os.environ.get("QUANT_COURSE_ID", "").strip()
QUANT_COURSE_TITLE = os.environ.get("QUANT_COURSE_TITLE", "ProfitLab Quant").strip().lower()
_TTL = float(os.environ.get("AULA_CACHE_TTL", "120"))
_TIMEOUT = float(os.environ.get("AULA_TIMEOUT", "8"))

_cache: dict[str, tuple[float, dict]] = {}


def _slug_prefix() -> str:
    # The Aula slugifies "ProfitLab Quant" → "profitlab-quant-xxxx"; match the stem.
    return "".join(c if c.isalnum() else "-" for c in QUANT_COURSE_TITLE).strip("-")


def _course_matches(course: dict) -> bool:
    if not course:
        return False
    if QUANT_COURSE_ID and str(course.get("id", "")) == QUANT_COURSE_ID:
        return True
    title = str(course.get("title", "")).strip().lower()
    if QUANT_COURSE_TITLE and title == QUANT_COURSE_TITLE:
        return True
    slug = str(course.get("slug", "")).strip().lower()
    if slug and slug.startswith(_slug_prefix()):
        return True
    return False


def _aula_get(path: str, token: str):
    return requests.get(
        f"{AULA_API_BASE}{path}",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        timeout=_TIMEOUT,
    )


def resolve_access(token: str) -> dict:
    """Decide access for a token. Returns a dict with:
        authenticated: bool, has_access: bool, user: {...}|None, error: str|None
    Cached per token for _TTL seconds. Never raises for auth logic; `error`
    is set only when the Aula API can't be reached."""
    now = time.time()
    hit = _cache.get(token)
    if hit and now - hit[0] < _TTL:
        return hit[1]

    try:
        me = _aula_get("/auth/me", token)
    except requests.RequestException:
        return {"authenticated": False, "has_access": False, "user": None, "error": "aula_unreachable"}

    if me.status_code == 401:
        dec = {"authenticated": False, "has_access": False, "user": None, "error": None}
        _cache[token] = (now, dec)
        return dec
    if not me.ok:
        return {"authenticated": False, "has_access": False, "user": None, "error": "aula_error"}

    user = me.json() or {}
    pub = {"id": user.get("id"), "name": user.get("name"),
           "email": user.get("email"), "role": user.get("role")}

    if pub["role"] == "admin":
        dec = {"authenticated": True, "has_access": True, "user": pub, "error": None}
        _cache[token] = (now, dec)
        return dec

    has = False
    try:
        enr = _aula_get("/enrollments/me", token)
        rows = enr.json() if enr.ok else []
    except requests.RequestException:
        rows = []
    for e in rows or []:
        if _course_matches((e or {}).get("course") or {}):
            has = True
            break

    dec = {"authenticated": True, "has_access": has, "user": pub, "error": None}
    _cache[token] = (now, dec)
    return dec


def _token_from_header(authorization: str | None) -> str | None:
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    return authorization.split(" ", 1)[1].strip() or None


def access_status(authorization: str = Header(None)) -> dict:
    """Public status endpoint helper: never 401/403, just reports the decision
    so the frontend can route the user (login / buy course / dashboard)."""
    token = _token_from_header(authorization)
    if not token:
        return {"authenticated": False, "has_access": False, "user": None}
    dec = resolve_access(token)
    if dec.get("error") == "aula_unreachable":
        raise HTTPException(status_code=503, detail="No se pudo contactar el Aula Virtual")
    return {"authenticated": dec["authenticated"], "has_access": dec["has_access"], "user": dec["user"]}


def require_access(authorization: str = Header(None)):
    """Gate for data endpoints: valid Aula session + quant-course enrollment."""
    token = _token_from_header(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="No autenticado")
    dec = resolve_access(token)
    if dec.get("error") == "aula_unreachable":
        raise HTTPException(status_code=503, detail="No se pudo contactar el Aula Virtual")
    if not dec["authenticated"]:
        raise HTTPException(status_code=401, detail="Sesión inválida o expirada")
    if not dec["has_access"]:
        raise HTTPException(status_code=403, detail="No tienes acceso al dashboard ProfitLab Quant")
    return dec["user"]
