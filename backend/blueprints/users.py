"""User management (manager). No self-registration."""
from __future__ import annotations

from typing import Literal

from flask import Blueprint, g, jsonify, request
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from ..db import db
from ..errors import ApiError
from ..models import User
from ..security import check_password_policy, hash_password, recent_auth_required, roles_required
from ..services.audit import audit
from ..timeutil import utcnow
from .auth import user_public

bp = Blueprint("users", __name__, url_prefix="/api/v1")


class UserIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)
    username: str = Field(min_length=3, max_length=64, pattern=r"^[a-zA-Z0-9._-]+$")
    role: Literal["caretaker", "manager", "leader"]
    password: str = Field(min_length=1, max_length=200)
    language: Literal["en", "fil"] | None = None


class UserPatch(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=120)
    role: Literal["caretaker", "manager", "leader"] | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, max_length=200)


@bp.get("/users")
@roles_required("manager")
def list_users():
    rows = list(db().scalars(select(User).order_by(User.full_name)))
    return jsonify({"items": [user_public(u) for u in rows]})


@bp.post("/users")
@roles_required("manager")
@recent_auth_required
def create_user():
    body = UserIn.model_validate(request.get_json(silent=True) or {})
    username = body.username.lower()
    if db().scalars(select(User).where(User.username == username)).first():
        raise ApiError(409, "username_taken", "That username is already used.", {"username": "taken"})
    check_password_policy(body.password)
    u = User(full_name=body.full_name.strip(), username=username, password_hash=hash_password(body.password), role=body.role,
             created_at=utcnow(), is_active=True, language=body.language, theme="auto")
    db().add(u)
    db().flush()
    audit("user.create", f"user:{u.user_id}", None, {"username": username, "role": body.role})
    return jsonify({"user": user_public(u)}), 201


@bp.patch("/users/<int:user_id>")
@roles_required("manager")
@recent_auth_required
def patch_user(user_id: int):
    body = UserPatch.model_validate(request.get_json(silent=True) or {})
    u = db().get(User, user_id)
    if u is None:
        raise ApiError(404, "not_found", "No such user.")
    before = {"full_name": u.full_name, "role": u.role, "is_active": u.is_active}
    # Never leave the garden without an active manager.
    if u.role == "manager" and ((body.role and body.role != "manager") or body.is_active is False):
        managers = db().scalar(select(func.count()).select_from(User).where(User.role == "manager", User.is_active.is_(True)))
        if managers <= 1:
            raise ApiError(409, "last_manager", "This is the only active manager. Add another manager first.")
    if body.full_name:
        u.full_name = body.full_name.strip()
    if body.role:
        u.role = body.role
    if body.is_active is not None:
        if u.user_id == g.user.user_id and body.is_active is False:
            raise ApiError(409, "self_deactivate", "You cannot deactivate your own account.")
        u.is_active = body.is_active
    if body.password:
        check_password_policy(body.password)
        u.password_hash = hash_password(body.password)
        u.password_changed_at = utcnow()
    after = {"full_name": u.full_name, "role": u.role, "is_active": u.is_active, "password_reset": bool(body.password)}
    audit("user.update", f"user:{u.user_id}", before, after)
    return jsonify({"user": user_public(u)})
