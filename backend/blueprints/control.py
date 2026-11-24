"""Manual override: Start / Stop watering (Tier 2). Caretakers and managers only."""
from __future__ import annotations

from flask import Blueprint, g, jsonify, request
from pydantic import BaseModel, Field

from ..db import db
from ..errors import ApiError
from ..models import DeviceCommand
from ..security import roles_required
from ..services.commands import command_view, create_start, create_stop
from ..services.device_service import primary_device
from ..timeutil import utcnow

bp = Blueprint("control", __name__, url_prefix="/api/v1")


class StartIn(BaseModel):
    duration_s: int = Field(ge=10, le=3600)


@bp.post("/watering/start")
@roles_required("caretaker", "manager")
def start():
    body = StartIn.model_validate(request.get_json(silent=True) or {})
    now = utcnow()
    cmd = create_start(primary_device(), g.user, body.duration_s, now)
    return jsonify({"command": command_view(cmd, now)}), 202


@bp.post("/watering/stop")
@roles_required("caretaker", "manager")
def stop():
    now = utcnow()
    cmd = create_stop(primary_device(), g.user, now)
    return jsonify({"command": command_view(cmd, now)}), 202


@bp.get("/commands/<int:command_id>")
@roles_required("caretaker", "manager")
def get_command(command_id: int):
    now = utcnow()
    cmd = db().get(DeviceCommand, command_id)
    if cmd is None:
        raise ApiError(404, "not_found", "No such command.")
    return jsonify({"command": command_view(cmd, now)})
