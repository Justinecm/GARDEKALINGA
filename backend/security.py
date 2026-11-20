"""Passwords, sessions, CSRF and role checks for the dashboard API.

- Argon2id password hashes, minimum 10 characters (C-9).
- Signed, HttpOnly, SameSite=Strict session cookie; 7-day rolling, 30-day absolute.
- CSRF token (X-CSRF-Token header) on every unsafe request.
- Role checks happen on the server for every route; the UI only hides.
- Managers re-enter their password for settings, user and device changes when
  their last password entry is older than 15 minutes.
"""
from __future__ import annotations

import hmac
import secrets
from datetime import datetime, timedelta
from functools import wraps
from typing import Callable

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from flask import g, request, session
from sqlalchemy import func, select

from .db import db
from .errors import ApiError
from .models import LoginAttempt, User
from .timeutil import utcnow

_hasher = PasswordHasher()  # argon2id defaults (RFC 9106 low-memory profile)

MIN_PASSWORD_LEN = 10
ABSOLUTE_SESSION = timedelta(days=30)
REAUTH_WINDOW = timedelta(minutes=15)
LOGIN_RATE_PER_MIN = 5
LOCKOUT_FAILURES = 10
LOCKOUT_WINDOW = timedelta(minutes=15)
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}

# A hash of a random password so that unknown usernames cost the same time.
_DUMMY_HASH = _hasher.hash(secrets.token_hex(16))


def hash_password(pw: str) -> str:
    return _hasher.hash(pw)


def verify_password(pw_hash: str, pw: str) -> bool:
    try:
        return _hasher.verify(pw_hash, pw)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def check_password_policy(pw: str) -> None:
    if len(pw) < MIN_PASSWORD_LEN:
        raise ApiError(422, "weak_password", f"Use at least {MIN_PASSWORD_LEN} characters.", {"password": "too_short"})


def client_ip() -> str:
    # Vercel and Caddy put the client address first in X-Forwarded-For.
    fwd = request.headers.get("X-Forwarded-For", "")
    if fwd:
        return fwd.split(",")[0].strip()[:64]
    return (request.remote_addr or "unknown")[:64]


# ------------------------------------------------------------------ login throttling
def login_throttle_state(username: str, ip: str, now: datetime) -> str | None:
    """Return "rate_limited", "locked" or None."""
    s = db()
    recent = s.scalar(
        select(func.count())
        .select_from(LoginAttempt)
        .where(LoginAttempt.ip == ip, LoginAttempt.username == username, LoginAttempt.at > now - timedelta(minutes=1))
    )
    if (recent or 0) >= LOGIN_RATE_PER_MIN:
        return "rate_limited"
    fails = s.scalar(
        select(func.count())
        .select_from(LoginAttempt)
        .where(LoginAttempt.username == username, LoginAttempt.success.is_(False), LoginAttempt.at > now - LOCKOUT_WINDOW)
    )
    if (fails or 0) >= LOCKOUT_FAILURES:
        return "locked"
    return None


def record_login_attempt(username: str, ip: str, success: bool, now: datetime) -> None:
    db().add(LoginAttempt(username=username[:64], ip=ip, success=success, at=now))


# ------------------------------------------------------------------ sessions
def start_session(user: User) -> str:
    """Rotate the session at login and return the new CSRF token."""
    session.clear()
    now = utcnow()
    token = secrets.token_urlsafe(32)
    session.permanent = True
    session["uid"] = user.user_id
    session["iat"] = now.timestamp()
    session["auth_at"] = now.timestamp()
    session["csrf"] = token
    return token


def end_session() -> None:
    session.clear()


def mark_reauth() -> None:
    session["auth_at"] = utcnow().timestamp()


def csrf_token() -> str | None:
    return session.get("csrf")


def load_current_user() -> User | None:
    uid = session.get("uid")
    if not uid:
        return None
    iat = session.get("iat", 0)
    now = utcnow()
    if now.timestamp() - float(iat) > ABSOLUTE_SESSION.total_seconds():
        session.clear()
        return None
    user = db().get(User, int(uid))
    if user is None or not user.is_active:
        session.clear()
        return None
    # A password change ends every older session.
    if user.password_changed_at and user.password_changed_at.timestamp() > float(iat) + 1:
        session.clear()
        return None
    return user


def _check_csrf() -> None:
    if request.method in UNSAFE:
        sent = request.headers.get("X-CSRF-Token", "")
        expected = session.get("csrf", "")
        if not expected or not hmac.compare_digest(sent, expected):
            raise ApiError(403, "csrf_failed", "Your session expired. Please reload the page and sign in again.")


def login_required(fn: Callable) -> Callable:
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = load_current_user()
        if user is None:
            raise ApiError(401, "not_authenticated", "Please sign in.")
        _check_csrf()
        g.user = user
        return fn(*args, **kwargs)

    return wrapper


def roles_required(*roles: str) -> Callable:
    def deco(fn: Callable) -> Callable:
        @wraps(fn)
        @login_required
        def wrapper(*args, **kwargs):
            if g.user.role not in roles:
                raise ApiError(403, "forbidden", "Your account cannot do this.")
            return fn(*args, **kwargs)

        return wrapper

    return deco


def recent_auth_required(fn: Callable) -> Callable:
    """Use after roles_required: asks for the password again after 15 minutes."""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        auth_at = float(session.get("auth_at", 0))
        if utcnow().timestamp() - auth_at > REAUTH_WINDOW.total_seconds():
            raise ApiError(401, "reauth_required", "Please enter your password again to make this change.")
        return fn(*args, **kwargs)

    return wrapper


def dummy_verify() -> None:
    verify_password(_DUMMY_HASH, "not-the-password")
