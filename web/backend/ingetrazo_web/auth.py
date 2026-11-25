"""Accounts, sessions and document ownership.

Off by default: on a single machine, bound to loopback, there is one implicit user and
nothing changes. Turn it on by creating users (``python -m web.backend users add NAME``)
or by setting ``INGETRAZO_WEB_AUTH=1``; from then on every API request needs a
credential, each document and job belongs to the user who made it, and other users get
``404`` for it (its existence is not revealed). Administrators see everything and are
the only ones who can change the shared component categories.

Credentials
- A user is given one random **access token** when created (shown once, stored only as a
  salted hash). The browser trades it for a session cookie (``POST /api/v1/auth/login``);
  scripts send it as ``Authorization: Bearer <token>``.
- The cookie is an HMAC-signed ``name.expiry`` pair (key kept beside the data, mode 0600),
  ``HttpOnly`` and ``SameSite=Strict``, and ``Secure`` when ``INGETRAZO_WEB_SECURE_COOKIES=1``
  (set it when serving over TLS). Unsafe requests that carry an ``Origin`` header from
  another site are refused, so a page on another site cannot act with the cookie.
- Failed logins are throttled per client address.

This is deliberately small: no passwords, e-mail or password reset, no per-user quotas.
Run behind TLS (a reverse proxy) before exposing it beyond a trusted network.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .errors import error_body

COOKIE = "ingetrazo_session"
SESSION_SECONDS = 12 * 3600
LOGIN_ATTEMPTS = 8                  # per address per minute
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}
_NAME = re.compile(r"[A-Za-z0-9_.\-@]{1,64}")
_DOCUMENT_PATH = re.compile(r"^/api/v1/documents/(?P<id>[0-9a-fA-F-]{36})(?:/|$)")
_JOB_PATH = re.compile(r"^/api/v1/jobs/(?P<id>[0-9a-fA-F-]{36})(?:/|$)")
# Only these may be read without a credential (the page itself is public: it shows the sign-in box).
_OPEN = ("/api/v1/health", "/api/v1/auth/")


@dataclass(frozen=True)
class User:
    name: str
    role: str = "user"

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


LOCAL = User("local", "admin")        # the implicit user when authentication is off


class Users:
    """The accounts file (``users.json`` in the data folder)."""

    def __init__(self, root: Path) -> None:
        self.path = Path(root) / "users.json"

    def _read(self) -> list[dict[str, Any]]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8")).get("users", [])
        except (OSError, ValueError):
            return []

    def _write(self, users: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        part = self.path.with_suffix(".part")
        part.write_text(json.dumps({"users": users}, indent=2), encoding="utf-8")
        os.chmod(part, 0o600)
        part.replace(self.path)

    @staticmethod
    def _hash(salt: str, token: str) -> str:
        return hashlib.sha256(f"{salt}:{token}".encode()).hexdigest()

    def names(self) -> list[dict[str, str]]:
        return [{"name": item["name"], "role": item.get("role", "user")} for item in self._read()]

    def any(self) -> bool:
        return bool(self._read())

    def add(self, name: str, role: str = "user", *, rotate: bool = False) -> str:
        """Create a user (or, with ``rotate``, give an existing one a new token); returns the token."""
        if not _NAME.fullmatch(name):
            raise ValueError("A user name is 1-64 letters, digits or . _ - @")
        if role not in {"user", "admin"}:
            raise ValueError("role must be user or admin")
        users = self._read()
        existing = next((item for item in users if item["name"] == name), None)
        if existing and not rotate:
            raise ValueError(f"The user {name!r} already exists (use `token` to issue a new token)")
        if rotate and not existing:
            raise ValueError(f"There is no user {name!r}")
        token = secrets.token_urlsafe(32)
        salt = secrets.token_hex(8)
        record = {"name": name, "role": existing["role"] if existing else role, "salt": salt,
                  "token_hash": self._hash(salt, token), "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        self._write([item for item in users if item["name"] != name] + [record])
        return token

    def remove(self, name: str) -> bool:
        users = self._read()
        kept = [item for item in users if item["name"] != name]
        if len(kept) == len(users):
            return False
        self._write(kept)
        return True

    def verify(self, token: str) -> User | None:
        found = None
        for item in self._read():                     # compare against every user: no early exit to time
            if hmac.compare_digest(self._hash(item["salt"], token), item["token_hash"]):
                found = User(item["name"], item.get("role", "user"))
        return found

    def get(self, name: str) -> User | None:
        item = next((item for item in self._read() if item["name"] == name), None)
        return User(item["name"], item.get("role", "user")) if item else None


class Auth:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.users = Users(self.root)
        self._key: bytes | None = None
        self._attempts: dict[str, list[float]] = {}
        self.secure_cookies = os.environ.get("INGETRAZO_WEB_SECURE_COOKIES") == "1"

    @property
    def enabled(self) -> bool:
        flag = os.environ.get("INGETRAZO_WEB_AUTH")
        if flag in {"0", "off"}:
            return False
        return flag == "1" or self.users.any()

    def _secret(self) -> bytes:
        if self._key is None:
            path = self.root / "session.key"
            if not path.is_file():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(secrets.token_bytes(32))
                os.chmod(path, 0o600)
            self._key = path.read_bytes()
        return self._key

    def _sign(self, payload: str) -> str:
        return hmac.new(self._secret(), payload.encode(), hashlib.sha256).hexdigest()

    def session_for(self, user: User) -> str:
        payload = f"{user.name}.{int(time.time()) + SESSION_SECONDS}"
        return f"{payload}.{self._sign(payload)}"

    def user_from_cookie(self, value: str | None) -> User | None:
        if not value:
            return None
        payload, _, signature = value.rpartition(".")
        if not hmac.compare_digest(signature, self._sign(payload)):
            return None
        name, _, expiry = payload.rpartition(".")
        if not expiry.isdigit() or int(expiry) < time.time():
            return None
        return self.users.get(name)                  # a removed user's session stops working at once

    def user_from_request(self, request: Request) -> User | None:
        header = request.headers.get("authorization", "")
        if header.lower().startswith("bearer "):
            return self.users.verify(header[7:].strip())
        return self.user_from_cookie(request.cookies.get(COOKIE))

    def throttled(self, address: str) -> bool:
        now = time.monotonic()
        recent = [stamp for stamp in self._attempts.get(address, []) if now - stamp < 60]
        recent.append(now)
        self._attempts[address] = recent
        if len(self._attempts) > 1000:                # forget addresses that went quiet
            self._attempts = {key: [s for s in value if now - s < 60] for key, value in self._attempts.items()
                              if any(now - s < 60 for s in value)}
        return len(recent) > LOGIN_ATTEMPTS


def _deny(status: int, message: str, code: str | None = None) -> JSONResponse:
    body = error_body(status, message)
    if code:
        body["detail"]["code"] = code
    return JSONResponse(body, status_code=status)


def current_user(request: Request) -> User:
    return getattr(request.state, "user", LOCAL)


def can_see(user: User, owner: str | None) -> bool:
    """Whether ``user`` may open something owned by ``owner`` (``None``: made before accounts existed)."""
    return user.is_admin or (owner is not None and owner == user.name)


def register_auth(app: FastAPI, store, jobs) -> Auth:
    auth = Auth(store.root)
    app.state.auth = auth

    @app.middleware("http")
    async def authenticate(request: Request, call_next):
        path = request.url.path
        request.state.user = LOCAL
        if not auth.enabled or not path.startswith("/api/") or any(path.startswith(prefix) for prefix in _OPEN):
            return await call_next(request)
        user = auth.user_from_request(request)
        if user is None:
            if not auth.users.any():
                return _deny(401, "Authentication is on but no user exists yet: run `python -m web.backend users add NAME --admin`.", "no_users")
            return _deny(401, "Sign in to use the service.", "unauthorized")
        if request.method in UNSAFE and request.headers.get("origin") and not request.headers.get("authorization"):
            origin = urlsplit(request.headers["origin"]).netloc
            if origin != request.headers.get("host"):
                return _deny(403, "This request came from another site and was refused.", "forbidden")
        request.state.user = user
        for pattern, owner_of in ((_DOCUMENT_PATH, store.owner_of), (_JOB_PATH, jobs.owner_of)):
            match = pattern.match(path)
            if match:
                owner = owner_of(match.group("id").lower())
                if owner is not False and not can_see(user, owner):
                    # indistinguishable from "does not exist"
                    return _deny(404, "Job not found." if pattern is _JOB_PATH else "Document not found.")
        return await call_next(request)

    @app.get("/api/v1/auth/me")
    def me(request: Request):
        if not auth.enabled:
            return {"auth_required": False, "authenticated": True, "user": LOCAL.name, "role": LOCAL.role}
        user = auth.user_from_request(request)
        return {"auth_required": True, "authenticated": user is not None,
                **({"user": user.name, "role": user.role} if user else {})}

    @app.post("/api/v1/auth/login")
    async def login(request: Request):
        if not auth.enabled:
            return JSONResponse({"auth_required": False, "authenticated": True, "user": LOCAL.name, "role": LOCAL.role})
        address = request.client.host if request.client else "?"
        if auth.throttled(address):
            return _deny(429, "Too many sign-in attempts; wait a minute.")
        try:
            token = (await request.json()).get("token")
        except ValueError:
            token = None
        user = auth.users.verify(token) if isinstance(token, str) and 8 <= len(token) <= 200 else None
        if user is None:
            return _deny(401, "That access token is not valid.", "invalid_token")
        response = JSONResponse({"auth_required": True, "authenticated": True, "user": user.name, "role": user.role})
        response.set_cookie(COOKIE, auth.session_for(user), max_age=SESSION_SECONDS, httponly=True,
                            samesite="strict", secure=auth.secure_cookies, path="/")
        return response

    @app.post("/api/v1/auth/logout")
    def logout():
        response = JSONResponse({"authenticated": False})
        response.delete_cookie(COOKIE, path="/")
        return response

    return auth
