"""Device administration (manager): register, rotate key, read now."""
from __future__ import annotations

import re

from flask import Blueprint, g, jsonify, request
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..db import db
from ..device_auth import encrypt_secret, new_device_secret
from ..errors import ApiError
from ..models import Device
from ..security import login_required, recent_auth_required, roles_required
from ..services.audit import audit
from ..services.commands import command_view, create_read_now
from ..services.device_service import is_online
from ..timeutil import iso, utcnow

bp = Blueprint("admin", __name__, url_prefix="/api/v1")
ID_RE = re.compile(r"^[a-zA-Z0-9_-]{3,40}$")


class DeviceIn(BaseModel):
    device_id: str = Field(min_length=3, max_length=40)
    name: str = Field(default="Box B field controller", max_length=80)


def device_public(d: Device) -> dict:
    from flask import current_app

    return {"id": d.device_id, "name": d.name, "fw": d.fw_version, "last_seen_at": iso(d.last_seen_at),
            "key_rotated_at": iso(d.key_rotated_at), "online": is_online(d, utcnow(), current_app.config["GK"].offline_after_s),
            "state": d.last_state_json}


def register_device(device_id: str, name: str) -> tuple[Device, str]:
    if not ID_RE.match(device_id):
        raise ApiError(422, "validation_error", "Use 3–40 letters, digits, - or _.", {"device_id": "invalid"})
    if db().get(Device, device_id):
        raise ApiError(409, "device_exists", "A device with this id already exists. Rotate its key instead.")
    secret = new_device_secret()
    now = utcnow()
    d = Device(device_id=device_id, name=name, key_encrypted=encrypt_secret(secret), key_rotated_at=now, created_at=now)
    db().add(d)
    db().flush()
    return d, secret


@bp.get("/devices")
@login_required
def list_devices():
    return jsonify({"items": [device_public(d) for d in db().scalars(select(Device).order_by(Device.created_at))]})


@bp.post("/devices")
@roles_required("manager")
@recent_auth_required
def create_device():
    body = DeviceIn.model_validate(request.get_json(silent=True) or {})
    d, secret = register_device(body.device_id, body.name)
    audit("device.register", f"device:{d.device_id}")
    return jsonify({"device": device_public(d), "secret": secret,
                    "note": "Copy this secret into the controller's setup page now. It is shown only once."}), 201


@bp.post("/devices/<device_id>/rotate-key")
@roles_required("manager")
@recent_auth_required
def rotate(device_id: str):
    d = db().get(Device, device_id)
    if d is None:
        raise ApiError(404, "not_found", "No such device.")
    secret = new_device_secret()
    d.key_encrypted = encrypt_secret(secret)
    d.key_rotated_at = utcnow()
    audit("device.rotate_key", f"device:{device_id}")
    return jsonify({"device": device_public(d), "secret": secret,
                    "note": "The old key stops working now. Enter the new secret in the controller's setup page."})


@bp.post("/devices/<device_id>/read-now")
@roles_required("manager")
def read_now(device_id: str):
    d = db().get(Device, device_id)
    if d is None:
        raise ApiError(404, "not_found", "No such device.")
    cmd = create_read_now(d, g.user, utcnow())
    return jsonify({"command": command_view(cmd, utcnow())}), 202
