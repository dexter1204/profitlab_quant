"""Database layer for accounts, coupons and access control.

Database-agnostic via SQLAlchemy Core. Pick the backend with DATABASE_URL:

    MySQL (SiteGround / any):
        mysql+pymysql://user:password@host:3306/dbname
    Postgres (Neon / Supabase / RDS):
        postgresql+psycopg2://user:password@host:5432/dbname
    SQLite (local dev / tests — the default):
        sqlite:///./profitlab.db

The three tables:
    users        registered accounts (email + password hash, access window)
    coupons      redeemable codes (duration + max uses)
    redemptions  audit log of which user redeemed which coupon when
"""

from __future__ import annotations

import os
from datetime import datetime

from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey, Integer, MetaData, String, Table,
    Text, create_engine, func,
)

# Far-future sentinel for "lifetime" access (keeps the schema to one column).
LIFETIME = datetime(2099, 12, 31)

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./profitlab.db")

# MySQL/Postgres connections can drop while idle; pre_ping + recycle keep the
# pool healthy on a long-lived Render service.
_engine_kwargs: dict = {"pool_pre_ping": True, "future": True}
if DATABASE_URL.startswith("sqlite"):
    _engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    _engine_kwargs["pool_recycle"] = 280

engine = create_engine(DATABASE_URL, **_engine_kwargs)
metadata = MetaData()

users = Table(
    "users", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("email", String(255), unique=True, nullable=False, index=True),
    Column("name", String(255), nullable=False, default=""),
    Column("password_hash", String(255), nullable=False),
    Column("access_until", DateTime, nullable=True),   # None = no access yet
    Column("is_admin", Boolean, nullable=False, default=False),
    Column("active", Boolean, nullable=False, default=True),
    Column("created_at", DateTime, nullable=False, default=datetime.utcnow),
)

coupons = Table(
    "coupons", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("code", String(64), unique=True, nullable=False, index=True),
    Column("duration_days", Integer, nullable=False, default=30),  # 0 = lifetime
    Column("max_uses", Integer, nullable=False, default=1),
    Column("uses", Integer, nullable=False, default=0),
    Column("active", Boolean, nullable=False, default=True),
    Column("note", String(255), nullable=False, default=""),
    Column("created_at", DateTime, nullable=False, default=datetime.utcnow),
)

redemptions = Table(
    "redemptions", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("user_id", Integer, ForeignKey("users.id"), nullable=False, index=True),
    Column("coupon_id", Integer, ForeignKey("coupons.id"), nullable=False, index=True),
    Column("code", String(64), nullable=False, default=""),
    Column("granted_until", DateTime, nullable=True),
    Column("redeemed_at", DateTime, nullable=False, default=datetime.utcnow),
)


def init_db() -> None:
    """Create tables if they don't exist. Safe to call on every startup."""
    metadata.create_all(engine)


def has_access(row) -> bool:
    """True if the user row currently has an active, non-expired access window."""
    if row is None:
        return False
    au = row["access_until"] if isinstance(row, dict) else row.access_until
    return au is not None and au > datetime.utcnow()
