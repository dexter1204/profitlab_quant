"""Accounts, coupons and admin — auth helpers + API routers.

Security choices (zero extra deps, all stdlib):
  - Passwords: PBKDF2-HMAC-SHA256, 200k iterations, per-user random salt.
  - Tokens:    compact HS256 JWT signed with JWT_SECRET.

Routers exposed:
  /api/auth/register, /api/auth/login, /api/auth/me
  /api/coupons/redeem
  /api/admin/students…, /api/admin/coupons…   (admin only)
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import string
import time
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import insert, select, update

from . import db
from .db import coupons, engine, redemptions, users, LIFETIME

JWT_SECRET = os.environ.get("JWT_SECRET", "")
if not JWT_SECRET:
    # Dev fallback so local runs work; set JWT_SECRET in Render for production.
    JWT_SECRET = "dev-insecure-secret-change-me"
TOKEN_TTL = int(os.environ.get("TOKEN_TTL_SECONDS", str(60 * 60 * 24 * 30)))  # 30d

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ── password hashing (PBKDF2, stdlib) ────────────────────────────────────────
def hash_password(pw: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, 200_000)
    return f"pbkdf2_sha256$200000${base64.b16encode(salt).decode()}${base64.b16encode(dk).decode()}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        _algo, iters, salt_h, hash_h = stored.split("$")
        salt = base64.b16decode(salt_h)
        expected = base64.b16decode(hash_h)
        dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, int(iters))
        return hmac.compare_digest(dk, expected)
    except Exception:
        return False


# ── JWT (HS256, stdlib) ──────────────────────────────────────────────────────
def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _unb64(seg: str) -> bytes:
    return base64.urlsafe_b64decode(seg + "=" * (-len(seg) % 4))


def make_token(payload: dict, ttl: int = TOKEN_TTL) -> str:
    body = dict(payload)
    body["exp"] = int(time.time()) + ttl
    header = {"alg": "HS256", "typ": "JWT"}
    segs = _b64(json.dumps(header, separators=(",", ":")).encode()) + "." + \
        _b64(json.dumps(body, separators=(",", ":")).encode())
    sig = hmac.new(JWT_SECRET.encode(), segs.encode(), hashlib.sha256).digest()
    return segs + "." + _b64(sig)


def read_token(token: str) -> dict | None:
    try:
        h, p, s = token.split(".")
        segs = f"{h}.{p}"
        expected = _b64(hmac.new(JWT_SECRET.encode(), segs.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(expected, s):
            return None
        payload = json.loads(_unb64(p))
        if payload.get("exp", 0) < time.time():
            return None
        return payload
    except Exception:
        return None


# ── row → JSON ───────────────────────────────────────────────────────────────
def _user_public(row) -> dict:
    au = row.access_until
    lifetime = au is not None and au >= LIFETIME
    return {
        "id": row.id,
        "email": row.email,
        "name": row.name,
        "is_admin": bool(row.is_admin),
        "active": bool(row.active),
        "access_until": None if au is None else au.isoformat(),
        "lifetime": lifetime,
        "has_access": db.has_access(row),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _get_user_by_id(uid: int):
    with engine.connect() as conn:
        return conn.execute(select(users).where(users.c.id == uid)).first()


def _get_user_by_email(email: str):
    with engine.connect() as conn:
        return conn.execute(
            select(users).where(users.c.email == email.lower().strip())
        ).first()


# ── FastAPI dependencies ─────────────────────────────────────────────────────
def current_user(authorization: str = Header(None)):
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="No autenticado")
    payload = read_token(authorization.split(" ", 1)[1].strip())
    if not payload:
        raise HTTPException(status_code=401, detail="Sesión inválida o expirada")
    row = _get_user_by_id(int(payload.get("sub", 0)))
    if row is None or not row.active:
        raise HTTPException(status_code=401, detail="Cuenta no disponible")
    return row


def require_access(user=Depends(current_user)):
    if not db.has_access(user):
        raise HTTPException(status_code=403, detail="Tu acceso no está activo. Canjea un cupón.")
    return user


def require_admin(user=Depends(current_user)):
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Solo administradores")
    return user


# ── admin bootstrap (from env) ───────────────────────────────────────────────
def ensure_admin() -> None:
    """Create/refresh the admin account from ADMIN_EMAIL / ADMIN_PASSWORD."""
    email = (os.environ.get("ADMIN_EMAIL") or "").lower().strip()
    pw = os.environ.get("ADMIN_PASSWORD") or ""
    if not email or not pw:
        return
    row = _get_user_by_email(email)
    with engine.begin() as conn:
        if row is None:
            conn.execute(insert(users).values(
                email=email, name="Administrador", password_hash=hash_password(pw),
                access_until=LIFETIME, is_admin=True, active=True,
                created_at=datetime.utcnow(),
            ))
        else:
            # keep admin flag + lifetime access; refresh password to env value
            conn.execute(update(users).where(users.c.id == row.id).values(
                is_admin=True, active=True, access_until=LIFETIME,
                password_hash=hash_password(pw),
            ))


# ── request models ───────────────────────────────────────────────────────────
class RegisterIn(BaseModel):
    email: str
    password: str
    name: str = ""


class LoginIn(BaseModel):
    email: str
    password: str


class RedeemIn(BaseModel):
    code: str


class CouponIn(BaseModel):
    code: str = ""
    duration_days: int = 30     # 0 = lifetime
    max_uses: int = 1
    note: str = ""


class AccessIn(BaseModel):
    extend_days: int | None = None   # add N days from current access/now
    set_until: str | None = None     # ISO date; set exact expiry
    lifetime: bool | None = None     # grant lifetime
    revoke: bool | None = None       # remove access now


# ── auth router ──────────────────────────────────────────────────────────────
auth_router = APIRouter(prefix="/api/auth", tags=["auth"])


@auth_router.post("/register")
def register(body: RegisterIn):
    email = body.email.lower().strip()
    if not _EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="Email inválido")
    if len(body.password) < 8:
        raise HTTPException(status_code=400, detail="La contraseña debe tener al menos 8 caracteres")
    if _get_user_by_email(email) is not None:
        raise HTTPException(status_code=409, detail="Ese email ya está registrado")
    with engine.begin() as conn:
        res = conn.execute(insert(users).values(
            email=email, name=body.name.strip()[:255],
            password_hash=hash_password(body.password),
            access_until=None, is_admin=False, active=True,
            created_at=datetime.utcnow(),
        ))
        uid = res.inserted_primary_key[0]
    row = _get_user_by_id(uid)
    token = make_token({"sub": uid, "email": email, "adm": False})
    return {"token": token, "user": _user_public(row)}


@auth_router.post("/login")
def login(body: LoginIn):
    row = _get_user_by_email(body.email)
    if row is None or not verify_password(body.password, row.password_hash):
        raise HTTPException(status_code=401, detail="Email o contraseña incorrectos")
    if not row.active:
        raise HTTPException(status_code=403, detail="Cuenta desactivada")
    token = make_token({"sub": row.id, "email": row.email, "adm": bool(row.is_admin)})
    return {"token": token, "user": _user_public(row)}


@auth_router.get("/me")
def me(user=Depends(current_user)):
    return {"user": _user_public(user)}


# ── coupon redemption ────────────────────────────────────────────────────────
coupon_router = APIRouter(prefix="/api/coupons", tags=["coupons"])


@coupon_router.post("/redeem")
def redeem(body: RedeemIn, user=Depends(current_user)):
    code = body.code.strip().upper()
    if not code:
        raise HTTPException(status_code=400, detail="Ingresa un cupón")
    with engine.begin() as conn:
        cp = conn.execute(select(coupons).where(coupons.c.code == code)).first()
        if cp is None or not cp.active:
            raise HTTPException(status_code=404, detail="Cupón inválido o inactivo")
        if cp.uses >= cp.max_uses:
            raise HTTPException(status_code=409, detail="Este cupón ya alcanzó su límite de usos")
        # one redemption per user per coupon
        already = conn.execute(select(redemptions).where(
            (redemptions.c.user_id == user.id) & (redemptions.c.coupon_id == cp.id)
        )).first()
        if already is not None:
            raise HTTPException(status_code=409, detail="Ya canjeaste este cupón")

        now = datetime.utcnow()
        if cp.duration_days and cp.duration_days > 0:
            base = user.access_until if (user.access_until and user.access_until > now) else now
            if base >= LIFETIME:
                granted = LIFETIME
            else:
                granted = base + timedelta(days=int(cp.duration_days))
        else:
            granted = LIFETIME  # 0 days = lifetime

        conn.execute(update(users).where(users.c.id == user.id).values(access_until=granted))
        conn.execute(update(coupons).where(coupons.c.id == cp.id).values(uses=cp.uses + 1))
        conn.execute(insert(redemptions).values(
            user_id=user.id, coupon_id=cp.id, code=code,
            granted_until=granted, redeemed_at=now,
        ))
    row = _get_user_by_id(user.id)
    return {"user": _user_public(row),
            "granted_until": None if granted >= LIFETIME else granted.isoformat(),
            "lifetime": granted >= LIFETIME}


# ── admin router ─────────────────────────────────────────────────────────────
admin_router = APIRouter(prefix="/api/admin", tags=["admin"])


def _gen_code(n: int = 10) -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(n))


@admin_router.get("/students")
def list_students(_admin=Depends(require_admin)):
    with engine.connect() as conn:
        rows = conn.execute(select(users).order_by(users.c.created_at.desc())).fetchall()
    return {"students": [_user_public(r) for r in rows]}


@admin_router.post("/students/{uid}/access")
def set_access(uid: int, body: AccessIn, _admin=Depends(require_admin)):
    row = _get_user_by_id(uid)
    if row is None:
        raise HTTPException(status_code=404, detail="Alumno no encontrado")
    now = datetime.utcnow()
    if body.revoke:
        new_until = None
    elif body.lifetime:
        new_until = LIFETIME
    elif body.extend_days is not None:
        base = row.access_until if (row.access_until and row.access_until > now) else now
        new_until = base + timedelta(days=int(body.extend_days))
    elif body.set_until:
        try:
            new_until = datetime.fromisoformat(body.set_until.replace("Z", ""))
        except ValueError:
            raise HTTPException(status_code=400, detail="Fecha inválida (usa AAAA-MM-DD)")
    else:
        raise HTTPException(status_code=400, detail="Nada que cambiar")
    with engine.begin() as conn:
        conn.execute(update(users).where(users.c.id == uid).values(access_until=new_until))
    return {"user": _user_public(_get_user_by_id(uid))}


@admin_router.post("/students/{uid}/toggle")
def toggle_student(uid: int, _admin=Depends(require_admin)):
    row = _get_user_by_id(uid)
    if row is None:
        raise HTTPException(status_code=404, detail="Alumno no encontrado")
    if row.is_admin:
        raise HTTPException(status_code=400, detail="No puedes desactivar una cuenta admin")
    with engine.begin() as conn:
        conn.execute(update(users).where(users.c.id == uid).values(active=not row.active))
    return {"user": _user_public(_get_user_by_id(uid))}


def _coupon_public(r) -> dict:
    return {
        "id": r.id, "code": r.code, "duration_days": r.duration_days,
        "lifetime": r.duration_days == 0,
        "max_uses": r.max_uses, "uses": r.uses,
        "remaining": max(r.max_uses - r.uses, 0),
        "active": bool(r.active), "note": r.note,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


@admin_router.get("/coupons")
def list_coupons(_admin=Depends(require_admin)):
    with engine.connect() as conn:
        rows = conn.execute(select(coupons).order_by(coupons.c.created_at.desc())).fetchall()
    return {"coupons": [_coupon_public(r) for r in rows]}


@admin_router.post("/coupons")
def create_coupon(body: CouponIn, _admin=Depends(require_admin)):
    code = (body.code or _gen_code()).strip().upper()
    if body.max_uses < 1:
        raise HTTPException(status_code=400, detail="max_uses debe ser al menos 1")
    if body.duration_days < 0:
        raise HTTPException(status_code=400, detail="duration_days no puede ser negativo")
    with engine.begin() as conn:
        exists = conn.execute(select(coupons).where(coupons.c.code == code)).first()
        if exists is not None:
            raise HTTPException(status_code=409, detail="Ese código ya existe")
        res = conn.execute(insert(coupons).values(
            code=code, duration_days=int(body.duration_days),
            max_uses=int(body.max_uses), uses=0, active=True,
            note=body.note.strip()[:255], created_at=datetime.utcnow(),
        ))
        cid = res.inserted_primary_key[0]
    with engine.connect() as conn:
        row = conn.execute(select(coupons).where(coupons.c.id == cid)).first()
    return {"coupon": _coupon_public(row)}


@admin_router.post("/coupons/{cid}/toggle")
def toggle_coupon(cid: int, _admin=Depends(require_admin)):
    with engine.connect() as conn:
        row = conn.execute(select(coupons).where(coupons.c.id == cid)).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Cupón no encontrado")
    with engine.begin() as conn:
        conn.execute(update(coupons).where(coupons.c.id == cid).values(active=not row.active))
    with engine.connect() as conn:
        row = conn.execute(select(coupons).where(coupons.c.id == cid)).first()
    return {"coupon": _coupon_public(row)}
