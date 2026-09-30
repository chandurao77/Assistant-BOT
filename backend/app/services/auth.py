"""User authentication service — JWT tokens + user store (SQLite or PostgreSQL)."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import aiosqlite
import bcrypt
import json
import jwt

from app.config import Settings

logger = logging.getLogger(__name__)

_USER_SCHEMA_SQLITE = """
CREATE TABLE IF NOT EXISTS users (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    email      TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password   TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""

_USER_SCHEMA_PG = """
CREATE TABLE IF NOT EXISTS users (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    email      TEXT NOT NULL UNIQUE,
    password   TEXT NOT NULL,
    role       TEXT NOT NULL DEFAULT 'user',
    allowed_spaces TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);
"""


class AuthService:
    """Handles user registration, login, and JWT token management."""

    def __init__(self, settings: Settings, db_path: str, *, pg_pool=None) -> None:
        self._secret = settings.jwt_secret
        self._algorithm = settings.jwt_algorithm
        self._expire_hours = settings.jwt_expire_hours
        self._db_path = db_path
        self._pg_pool = pg_pool

    @property
    def _is_pg(self) -> bool:
        return self._pg_pool is not None

    @classmethod
    async def create(cls, settings: Settings, db_path: str, *, database_url: str | None = None) -> "AuthService":
        pg_pool = None
        if database_url:
            import asyncpg
            dsn = database_url.replace("postgresql+asyncpg://", "postgresql://")
            pg_pool = await asyncpg.create_pool(dsn, min_size=1, max_size=5)
            async with pg_pool.acquire() as conn:
                await conn.execute(_USER_SCHEMA_PG)
                # Migrations handled by schema defaults
            logger.info("AuthService ready (PostgreSQL)")
        else:
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
            async with aiosqlite.connect(db_path) as db:
                await db.executescript(_USER_SCHEMA_SQLITE)
                for col, default in [("role", "'user'"), ("allowed_spaces", "'[]'")]:
                    try:
                        await db.execute(f"ALTER TABLE users ADD COLUMN {col} TEXT NOT NULL DEFAULT {default}")
                        await db.commit()
                        logger.info("Migrated users table: added %s column", col)
                    except Exception:
                        pass
                await db.commit()
            logger.info("AuthService ready at %s", db_path)
        return cls(settings, db_path, pg_pool=pg_pool)

    # ── Password hashing ──────────────────────────────────────────────────

    @staticmethod
    def _hash_password(password: str) -> str:
        return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

    @staticmethod
    def _verify_password(password: str, hashed: str) -> bool:
        return bcrypt.checkpw(password.encode(), hashed.encode())

    # ── JWT ───────────────────────────────────────────────────────────────

    def create_token(self, user_id: str, email: str, name: str, role: str = "user", allowed_spaces: list[str] | None = None) -> str:
        payload = {
            "sub": user_id,
            "email": email,
            "name": name,
            "role": role,
            "allowed_spaces": allowed_spaces or [],
            "exp": datetime.now(timezone.utc) + timedelta(hours=self._expire_hours),
            "iat": datetime.now(timezone.utc),
        }
        return jwt.encode(payload, self._secret, algorithm=self._algorithm)

    def decode_token(self, token: str) -> dict | None:
        try:
            return jwt.decode(token, self._secret, algorithms=[self._algorithm])
        except jwt.ExpiredSignatureError:
            logger.debug("JWT token expired")
            return None
        except jwt.InvalidTokenError:
            logger.debug("Invalid JWT token")
            return None

    # ── User CRUD ─────────────────────────────────────────────────────────

    async def register(self, name: str, email: str, password: str) -> dict | None:
        """Create a new user. Returns user dict or None if email exists."""
        user_id = str(uuid.uuid4())
        hashed = self._hash_password(password)
        now = datetime.now(timezone.utc).isoformat()
        try:
            if self._is_pg:
                async with self._pg_pool.acquire() as conn:
                    await conn.execute(
                        "INSERT INTO users (id, name, email, password, role, allowed_spaces, created_at) VALUES ($1, $2, $3, $4, $5, $6, $7)",
                        user_id, name.strip(), email.strip().lower(), hashed, "user", "[]", now,
                    )
            else:
                async with aiosqlite.connect(self._db_path) as db:
                    await db.execute(
                        "INSERT INTO users (id, name, email, password, role, allowed_spaces, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (user_id, name.strip(), email.strip().lower(), hashed, "user", "[]", now),
                    )
                    await db.commit()
        except (aiosqlite.IntegrityError, Exception) as exc:
            if "unique" in str(exc).lower() or "integrity" in str(exc).lower() or isinstance(exc, aiosqlite.IntegrityError):
                return None
            raise
        return {"id": user_id, "name": name.strip(), "email": email.strip().lower(), "role": "user", "allowed_spaces": []}

    async def authenticate(self, email: str, password: str) -> dict | None:
        """Verify credentials. Returns user dict or None."""
        if self._is_pg:
            async with self._pg_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT id, name, email, password, role, allowed_spaces FROM users WHERE LOWER(email) = $1",
                    email.strip().lower(),
                )
        else:
            async with aiosqlite.connect(self._db_path) as db:
                async with db.execute(
                    "SELECT id, name, email, password, role, allowed_spaces FROM users WHERE email = ?",
                    (email.strip().lower(),),
                ) as cur:
                    row = await cur.fetchone()
        if not row:
            return None
        row_pw = row[3] if isinstance(row, (tuple, list)) else row["password"]
        if not self._verify_password(password, row_pw):
            return None
        if isinstance(row, (tuple, list)):
            return {"id": row[0], "name": row[1], "email": row[2], "role": row[4], "allowed_spaces": json.loads(row[5] or "[]")}
        return {"id": row["id"], "name": row["name"], "email": row["email"], "role": row["role"], "allowed_spaces": json.loads(row["allowed_spaces"] or "[]")}

    async def get_user_by_id(self, user_id: str) -> dict | None:
        if self._is_pg:
            async with self._pg_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT id, name, email, role, allowed_spaces FROM users WHERE id = $1", user_id,
                )
        else:
            async with aiosqlite.connect(self._db_path) as db:
                async with db.execute(
                    "SELECT id, name, email, role, allowed_spaces FROM users WHERE id = ?", (user_id,)
                ) as cur:
                    row = await cur.fetchone()
        if not row:
            return None
        if isinstance(row, (tuple, list)):
            return {"id": row[0], "name": row[1], "email": row[2], "role": row[3], "allowed_spaces": json.loads(row[4] or "[]")}
        return {"id": row["id"], "name": row["name"], "email": row["email"], "role": row["role"], "allowed_spaces": json.loads(row["allowed_spaces"] or "[]")}

    async def update_user_role(self, user_id: str, role: str, allowed_spaces: list[str] | None = None) -> bool:
        """Admin endpoint: set user role and allowed spaces."""
        spaces_json = json.dumps(allowed_spaces or [])
        if self._is_pg:
            async with self._pg_pool.acquire() as conn:
                result = await conn.execute(
                    "UPDATE users SET role = $1, allowed_spaces = $2 WHERE id = $3",
                    role, spaces_json, user_id,
                )
                return result.split()[-1] != "0"
        else:
            async with aiosqlite.connect(self._db_path) as db:
                cur = await db.execute(
                    "UPDATE users SET role = ?, allowed_spaces = ? WHERE id = ?",
                    (role, spaces_json, user_id),
                )
                await db.commit()
            return cur.rowcount > 0

    async def get_user_by_email(self, email: str) -> dict | None:
        """Look up a user by email address."""
        if self._is_pg:
            async with self._pg_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT id, name, email, role, allowed_spaces FROM users WHERE LOWER(email) = $1",
                    email.strip().lower(),
                )
        else:
            async with aiosqlite.connect(self._db_path) as db:
                async with db.execute(
                    "SELECT id, name, email, role, allowed_spaces FROM users WHERE email = ?",
                    (email.strip().lower(),),
                ) as cur:
                    row = await cur.fetchone()
        if not row:
            return None
        if isinstance(row, (tuple, list)):
            return {"id": row[0], "name": row[1], "email": row[2], "role": row[3], "allowed_spaces": json.loads(row[4] or "[]")}
        return {"id": row["id"], "name": row["name"], "email": row["email"], "role": row["role"], "allowed_spaces": json.loads(row["allowed_spaces"] or "[]")}

    async def create_sso_user(self, user_id: str, name: str, email: str, allowed_spaces: list[str] | None = None) -> dict:
        """Create a user provisioned via SSO (no password)."""
        now = datetime.now(timezone.utc).isoformat()
        spaces_json = json.dumps(allowed_spaces or [])
        dummy_hash = self._hash_password(uuid.uuid4().hex)
        if self._is_pg:
            async with self._pg_pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO users (id, name, email, password, role, allowed_spaces, created_at) VALUES ($1, $2, $3, $4, $5, $6, $7)",
                    user_id, name.strip(), email.strip().lower(), dummy_hash, "user", spaces_json, now,
                )
        else:
            async with aiosqlite.connect(self._db_path) as db:
                await db.execute(
                    "INSERT INTO users (id, name, email, password, role, allowed_spaces, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (user_id, name.strip(), email.strip().lower(), dummy_hash, "user", spaces_json, now),
                )
                await db.commit()
        return {"id": user_id, "name": name.strip(), "email": email.strip().lower(), "role": "user", "allowed_spaces": allowed_spaces or []}

    async def close(self) -> None:
        """Close database connections."""
        if self._pg_pool:
            await self._pg_pool.close()
