"""User accounts: password hashing and the users table (SCRUM-40)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import threading
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

USERNAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{2,31}$")
MIN_PASSWORD = 8
MAX_PASSWORD = 128

# scrypt parameters (OWASP: N=2^17, r=8, p=1). Stored with each hash so they can change later.
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**17, 8, 1
_MAXMEM = 256 * 1024 * 1024


class UserExists(ValueError):
    pass


class InvalidCredentials(ValueError):
    pass


@dataclass(frozen=True)
class User:
    id: str
    username: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def hash_password(password: str, *, n: int = SCRYPT_N, r: int = SCRYPT_R, p: int = SCRYPT_P) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p, maxmem=_MAXMEM, dklen=32)
    return f"scrypt${n}${r}${p}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = _unb64(digest)
        actual = hashlib.scrypt(
            password.encode(),
            salt=_unb64(salt),
            n=int(n),
            r=int(r),
            p=int(p),
            maxmem=_MAXMEM,
            dklen=len(expected),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


# Checked when the username is unknown, so a login takes as long either way.
_DUMMY_HASH = hash_password(secrets.token_urlsafe(16), n=2**14)


def validate_new_account(username: str, password: str) -> str | None:
    """Why the username or password cannot be used, or None."""
    if not USERNAME.match(username):
        return (
            "Username must be 3 to 32 characters: letters, digits, dot, dash or underscore, "
            "starting with a letter or digit."
        )
    if not MIN_PASSWORD <= len(password) <= MAX_PASSWORD:
        return f"Password must be {MIN_PASSWORD} to {MAX_PASSWORD} characters."
    if password.lower() == username.lower():
        return "Password must not be the same as the username."
    return None


class UserStore(Protocol):
    def create(self, username: str, password: str) -> User: ...

    def authenticate(self, username: str, password: str) -> User: ...


class MemoryUserStore:
    """For tests and running without Postgres."""

    def __init__(self, scrypt_n: int = SCRYPT_N) -> None:
        self._users: dict[str, tuple[User, str]] = {}
        self._lock = threading.Lock()
        self._n = scrypt_n

    def create(self, username: str, password: str) -> User:
        key = username.lower()
        hashed = hash_password(password, n=self._n)
        with self._lock:
            if key in self._users:
                raise UserExists(username)
            user = User(uuid.uuid4().hex, username)
            self._users[key] = (user, hashed)
        return user

    def authenticate(self, username: str, password: str) -> User:
        found = self._users.get(username.lower())
        if found is None:
            verify_password(password, _DUMMY_HASH)
            raise InvalidCredentials(username)
        user, hashed = found
        if not verify_password(password, hashed):
            raise InvalidCredentials(username)
        return user


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS users_username ON users (lower(username));
"""


class PostgresUserStore:
    def __init__(self, database_url: str) -> None:
        self._url = database_url
        self._ready = False

    def _connect(self) -> Any:
        import psycopg
        from psycopg.rows import dict_row

        conn = psycopg.connect(self._url, connect_timeout=5, row_factory=dict_row)
        if not self._ready:
            conn.execute(SCHEMA)
            conn.commit()
            self._ready = True
        return conn

    def create(self, username: str, password: str) -> User:
        import psycopg

        user = User(uuid.uuid4().hex, username)
        try:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO users (id, username, password_hash, created_at) "
                    "VALUES (%s, %s, %s, %s)",
                    (user.id, username, hash_password(password), user.created_at),
                )
        except psycopg.errors.UniqueViolation:
            raise UserExists(username) from None
        return user

    def authenticate(self, username: str, password: str) -> User:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, username, password_hash, created_at FROM users "
                "WHERE lower(username) = lower(%s)",
                (username,),
            ).fetchone()
        if row is None:
            verify_password(password, _DUMMY_HASH)
            raise InvalidCredentials(username)
        if not verify_password(password, row["password_hash"]):
            raise InvalidCredentials(username)
        return User(row["id"], row["username"], row["created_at"])
