"""Sign in / out, current user, password change, re-authentication, preferences."""
from __future__ import annotations

from typing import Literal

from flask import Blueprint, g, jsonify, request
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..db import db
from ..errors import ApiError
from ..models import User
from ..security import (
    check_password_policy,
    client_ip,
    csrf_token,
    dummy_verify,
    end_session,
    hash_password,
    login_required,
    login_throttle_state,
    mark_reauth,
    record_login_attempt,
    start_session,
    verify_password,
)
from ..services.audit import audit
from ..timeutil import iso, utcnow

bp = Blueprint("auth", __name__, url_prefix="/api/v1/auth")


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=200)


class PasswordIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=1, max_length=200)


class ReauthIn(BaseModel):
    password: str = Field(min_length=1, max_length=200)


class PrefsIn(BaseModel):
    language: Literal["en", "fil"] | None = None
    theme: Literal["auto", "light", "dark"] | None = None


def user_public(u: User) -> dict:
    return {
        "id": u.user_id,
        "full_name": u.full_name,
        "username": u.username,
        "role": u.role,
        "language": u.language,
        "theme": u.theme or "auto",
        "last_login_at": iso(u.last_login_at),
        "is_active": u.is_active,
        "created_at": iso(u.created_at),
    }


@bp.post("/login")
def login():
    g.commit_on_error = True  # keep the failed-attempt record
    body = LoginIn.model_validate(request.get_json(silent=True) or {})
    username = body.username.strip().lower()
    ip = client_ip()
    now = utcnow()
    throttle = login_throttle_state(username, ip, now)
    if throttle == "rate_limited":
        raise ApiError(429, "rate_limited", "Too many tries. Wait one minute and try again.")
    if throttle == "locked":
        audit("auth.locked", f"user:{username}", user_id=None)
        raise ApiError(429, "locked", "This account is locked for 15 minutes after many wrong passwords. Ask a manager if you need help.")
    user = db().scalars(select(User).where(User.username == username)).first()
    ok = False
    if user is None:
        dummy_verify()
    else:
        ok = verify_password(user.password_hash, body.password) and user.is_active
    record_login_attempt(username, ip, ok, now)
    if not ok:
        audit("auth.login_failed", f"user:{username}", user_id=user.user_id if user else None)
        raise ApiError(401, "bad_credentials", "Wrong username or password.")
    user.last_login_at = now  # type: ignore[union-attr]
    token = start_session(user)  # type: ignore[arg-type]
    audit("auth.login", f"user:{user.user_id}", user_id=user.user_id)  # type: ignore[union-attr]
    return jsonify({"user": user_public(user), "csrf": token})  # type: ignore[arg-type]


@bp.post("/logout")
@login_required
def logout():
    audit("auth.logout", f"user:{g.user.user_id}")
    end_session()
    return jsonify({"ok": True})


@bp.get("/me")
def me():
    from ..security import load_current_user

    user = load_current_user()
    if user is None:
        return jsonify({"user": None, "csrf": None})
    return jsonify({"user": user_public(user), "csrf": csrf_token()})


@bp.post("/password")
@login_required
def change_password():
    body = PasswordIn.model_validate(request.get_json(silent=True) or {})
    if not verify_password(g.user.password_hash, body.current_password):
        raise ApiError(403, "bad_credentials", "Your current password is not correct.", {"current_password": "wrong"})
    check_password_policy(body.new_password)
    g.user.password_hash = hash_password(body.new_password)
    g.user.password_changed_at = utcnow()
    audit("auth.password_changed", f"user:{g.user.user_id}")
    token = start_session(g.user)
    return jsonify({"ok": True, "csrf": token})


@bp.post("/reauth")
@login_required
def reauth():
    g.commit_on_error = True
    body = ReauthIn.model_validate(request.get_json(silent=True) or {})
    if not verify_password(g.user.password_hash, body.password):
        audit("auth.reauth_failed", f"user:{g.user.user_id}")
        raise ApiError(403, "bad_credentials", "That password is not correct.")
    mark_reauth()
    return jsonify({"ok": True})


@bp.patch("/preferences")
@login_required
def preferences():
    body = PrefsIn.model_validate(request.get_json(silent=True) or {})
    if body.language:
        g.user.language = body.language
    if body.theme:
        g.user.theme = body.theme
    return jsonify({"user": user_public(g.user)})
