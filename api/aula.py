"""Access control via the Profit Lab Aula Virtual.

The dashboard reuses the Aula accounts (same email + password) and gates access
by a coupon or a payment, handled by the Aula PHP API against its own MySQL.

Why auth is done *locally* here: SiteGround's anti-bot protection answers
server-to-server calls from Render with a 202 JavaScript challenge (not JSON),
so this backend cannot reliably call the Aula API. Instead it validates the
Aula JWT locally with the shared secret (HS256) — no HTTP to SiteGround — which
proves the caller is a signed-in Aula user. The coupon/payment paywall is
enforced by the frontend (the browser passes the anti-bot). When the Aula API
*is* reachable (e.g. the path is later exempted from bot mitigation), its
has_access answer is honored too.

Env:
    JWT_SECRET       the Aula's jwt_secret (from its config.php) — enables the
                     reliable local token validation. Strongly recommended.
    AULA_API_BASE    default https://profitlab-academy.com/aulavirtual/api
    AULA_CACHE_TTL   seconds to cache a remote decision per token (default 60)
    AULA_TIMEOUT     HTTP timeout to the Aula API (default 6s)
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time

import requests
from fastapi import Header, HTTPException

JWT_SECRET = os.environ.get("JWT_SECRET", "")
AULA_API_BASE = os.environ.get(
    "AULA_API_BASE", "https://profitlab-academy.com/aulavirtual/api"
).rstrip("/")
_TTL = float(os.environ.get("AULA_CACHE_TTL", "60"))
_TIMEOUT = float(os.environ.get("AULA_TIMEOUT", "6"))
_UA = os.environ.get(
    "AULA_USER_AGENT",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36 ProfitLabQuant/1.0",
)

_cache: dict[str, tuple[float, dict]] = {}


# ── local JWT validation (HS256, matches the Aula's jwt_encode) ──────────────
def _b64url_decode(seg: str) -> bytes:
    return base64.urlsafe_b64decode(seg + "=" * (-len(seg) % 4))


def verify_jwt(token: str) -> dict | None:
    """Validate the Aula JWT locally with JWT_SECRET. Returns the payload
    (sub/iat/exp) if the signature and expiry are valid, else None. Needs
    JWT_SECRET to be set to the same value as the Aula's config jwt_secret."""
    if not JWT_SECRET:
        return None
    try:
        h, p, s = token.split(".")
        sig = hmac.new(JWT_SECRET.encode(), f"{h}.{p}".encode(), hashlib.sha256).digest()
        expected = base64.urlsafe_b64encode(sig).rstrip(b"=").decode()
        if not hmac.compare_digest(expected, s):
            return None
        payload = json.loads(_b64url_decode(p))
        if float(payload.get("exp", 0)) < time.time():
            return None
        return payload
    except Exception:
        return None


# ── best-effort remote access check (may be blocked by SiteGround anti-bot) ──
def resolve_access(token: str) -> dict:
    """Ask the Aula whether the token's user has quant access. Best-effort:
    may be blocked (202 challenge) → returns an `error`. Cached per token."""
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
        dec = {"authenticated": False, "has_access": False, "user": None,
               "error": "aula_unreachable", "detail": f"{url}: {e}"}
        _cache[token] = (now, dec)
        return dec

    if r.status_code == 401:
        dec = {"authenticated": False, "has_access": False, "user": None, "error": None}
        _cache[token] = (now, dec)
        return dec
    if not r.ok and r.status_code != 202:
        dec = {"authenticated": False, "has_access": False, "user": None,
               "error": "aula_error", "detail": f"HTTP {r.status_code} from {url}: {r.text[:160]}"}
        _cache[token] = (now, dec)
        return dec

    try:
        d = r.json() or {}
    except ValueError:
        dec = {"authenticated": False, "has_access": False, "user": None,
               "error": "aula_badjson",
               "detail": f"Respuesta no-JSON de {url} (HTTP {r.status_code}): {r.text[:120]!r}"}
        _cache[token] = (now, dec)
        return dec

    dec = {"authenticated": True, "has_access": bool(d.get("has_access")),
           "user": d.get("user"), "access_until": d.get("access_until"), "error": None}
    _cache[token] = (now, dec)
    return dec


def _token(authorization: str | None) -> str | None:
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    return authorization.split(" ", 1)[1].strip() or None


def require_access(authorization: str = Header(None)):
    """Gate for data endpoints.

    Identity: a valid Aula JWT (checked locally with JWT_SECRET) OR, if the
    Aula API happens to be reachable, its confirmation. Access: when the Aula
    API answers (not blocked) its has_access decides; when it's blocked, a
    valid signed-in user is allowed and the frontend paywall governs coupons."""
    tok = _token(authorization)
    if not tok:
        raise HTTPException(status_code=401, detail="No autenticado")

    payload = verify_jwt(tok)             # local, reliable (needs JWT_SECRET)
    dec = resolve_access(tok)             # remote, best-effort (often blocked)
    remote_ok = dec.get("authenticated") and not dec.get("error")

    if not payload and not remote_ok:
        # Can't confirm identity either way.
        if not JWT_SECRET and dec.get("error"):
            raise HTTPException(
                status_code=503,
                detail="Configura JWT_SECRET en el backend (= jwt_secret del Aula) "
                       "para validar la sesión; el Aula no es accesible desde el servidor. "
                       + (dec.get("detail") or ""))
        raise HTTPException(status_code=401, detail="Sesión inválida o expirada")

    # If the Aula API gave a definitive answer, honor the coupon/payment gate.
    if remote_ok:
        if not dec["has_access"]:
            raise HTTPException(status_code=403,
                                detail="Acceso no activo. Canjea un cupón o adquiere el acceso.")
        return dec["user"]

    # Remote blocked but the JWT is valid → allow (frontend enforces the paywall).
    return {"id": (payload or {}).get("sub"), "role": None}
