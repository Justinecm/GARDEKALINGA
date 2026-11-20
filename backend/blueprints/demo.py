"""Demo controls (only when GK_DEMO_MODE=true)."""
from __future__ import annotations

from typing import Any, Literal

from flask import Blueprint, current_app, jsonify, request
from pydantic import BaseModel

from ..errors import ApiError
from ..security import login_required
from ..services import demo as demo_service
from ..timeutil import utcnow

bp = Blueprint("demo", __name__, url_prefix="/api/v1/demo")


class DemoAction(BaseModel):
    action: Literal["fault", "offline", "power", "rain", "dry", "reset"]
    value: Any = None


def _enabled():
    if not current_app.config["GK"].demo_mode:
        raise ApiError(404, "not_found", "Demo mode is off.")


@bp.get("")
@login_required
def get_state():
    _enabled()
    return jsonify(demo_service.public_state())


@bp.post("")
@login_required
def post_action():
    _enabled()
    body = DemoAction.model_validate(request.get_json(silent=True) or {})
    return jsonify(demo_service.apply_action(body.action, body.value, utcnow()))
