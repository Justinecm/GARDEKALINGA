"""Settings (manager): every save is a new version, logged and pushed to the node."""
from __future__ import annotations

from flask import Blueprint, g, jsonify, request
from sqlalchemy import select

from ..db import db
from ..errors import ApiError
from ..models import SystemSettings, User
from ..security import login_required, recent_auth_required, roles_required
from ..services.audit import audit
from ..services.settings_service import FIELD_SPECS, current_settings, save_new_version, to_public
from ._common import int_arg

bp = Blueprint("settings", __name__, url_prefix="/api/v1")


@bp.get("/settings")
@login_required
def get_settings():
    st = current_settings()
    return jsonify({"settings": to_public(st), "fields": FIELD_SPECS})


@bp.post("/settings")
@roles_required("manager")
@recent_auth_required
def post_settings():
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        raise ApiError(422, "validation_error", "Send a JSON object.")
    note = body.pop("note", None)
    before = to_public(current_settings())
    row = save_new_version(body, g.user.user_id, note=str(note)[:255] if note else None)
    after = to_public(row)
    changed = {k: after[k] for k in after if k not in ("version", "updated_at", "updated_by", "change_note") and after[k] != before.get(k)}
    audit("settings.save", f"settings:{row.setting_id}", {k: before.get(k) for k in changed}, changed)
    return jsonify({"settings": after, "changed": list(changed)})


@bp.get("/settings/history")
@login_required
def settings_history():
    rows = list(db().scalars(select(SystemSettings).order_by(SystemSettings.setting_id.desc()).limit(int_arg("limit", 50, 1, 500))))
    names = {u.user_id: u.full_name for u in db().scalars(select(User))}
    out = []
    for i, r in enumerate(rows):
        pub = to_public(r)
        prev = to_public(rows[i + 1]) if i + 1 < len(rows) else None
        changed = [] if prev is None else [k for k in pub if k not in ("version", "updated_at", "updated_by", "change_note")
                                           and pub[k] != prev.get(k)]
        out.append({"version": r.setting_id, "updated_at": pub["updated_at"], "updated_by": names.get(r.updated_by) if r.updated_by else None,
                    "note": r.change_note, "changed": {k: pub[k] for k in changed}})
    return jsonify({"items": out})
