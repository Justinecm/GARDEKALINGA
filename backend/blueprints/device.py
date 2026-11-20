"""Device API /api/device/v1/* (HMAC-signed, BUILD_PROMPT C-3), plus the
compatibility API /api/sensors/* used by the original 1-probe sketch."""
from __future__ import annotations

import hmac
import json
from datetime import timedelta

from flask import Blueprint, current_app, g, jsonify, request
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..db import db
from ..device_auth import decrypt_secret, device_auth_required
from ..errors import ApiError
from ..models import Device, DeviceCommand
from ..services import device_service as ds
from ..services.decision_engine import decision_to_device, run_for_reading
from ..services.settings_service import current_settings
from ..timeutil import floor_half_hour, iso, utcnow

bp = Blueprint("device", __name__, url_prefix="/api/device/v1")


def _cheap_jobs(now):
    from ..services.jobs import run_due

    run_due(now, ("expire_commands", "purge_nonces"))


@bp.post("/readings")
@device_auth_required
def readings():
    now = utcnow()
    body = ds.ReadingIn.model_validate(request.get_json(silent=True) or {})
    resp = ds.ingest_live_reading(g.device_ctx.device, body, now, g.device_ctx.time_unsynced)
    return jsonify(resp)


@bp.get("/poll")
@device_auth_required
def poll():
    now = utcnow()
    _cheap_jobs(now)
    resp = ds.poll(g.device_ctx.device, request.args.to_dict(), now)
    if g.device_ctx.time_unsynced:
        resp["tu"] = 1
    return current_app.response_class(json.dumps(resp, separators=(",", ":")), mimetype="application/json")


@bp.post("/commands/<int:command_id>/ack")
@device_auth_required
def ack(command_id: int):
    body = ds.AckIn.model_validate(request.get_json(silent=True) or {})
    return jsonify(ds.ack(g.device_ctx.device, command_id, body, utcnow()))


@bp.post("/events")
@device_auth_required
def events():
    now = utcnow()
    payload = request.get_json(silent=True) or {}
    items = payload.get("events") if isinstance(payload, dict) and "events" in payload else [payload]
    stored = 0
    for item in items:
        stored += int(ds.store_event(g.device_ctx.device, ds.EventIn.model_validate(item), now))
    ds.touch_device(g.device_ctx.device, now)
    return jsonify({"ok": True, "stored": stored, "server_time": iso(now)})


@bp.post("/sync")
@device_auth_required
def sync():
    body = ds.SyncIn.model_validate(request.get_json(silent=True) or {})
    return jsonify(ds.sync(g.device_ctx.device, body, utcnow()))


@bp.get("/settings")
@device_auth_required
def settings():
    from ..services.settings_service import to_device

    return jsonify({"server_time": iso(utcnow()), "settings": to_device(current_settings())})


# --------------------------------------------------------------------------------------
# Compatibility API for the original sketch_nov20a.ino (ENABLE_WIFI true).
# Off unless GK_LEGACY_DEVICE_API=true. Authenticates with X-Device-Key = device secret.
legacy_bp = Blueprint("legacy_device", __name__, url_prefix="/api/sensors")

LEGACY_STATE = {
    # sketch state -> (valve, pump)
    "IDLE": (0, 0),
    "VALVE_OPENING": (1, 0),
    "RUNNING": (1, 1),
    "STOPPING": (1, 0),
    "PUMP_STOPPING": (1, 0),
}


class LegacyReadings(BaseModel):
    soil_moisture: float | None = Field(default=None, ge=0, le=100)
    raw_adc: int | None = Field(default=None, ge=0, le=4095)
    supply_v: float | None = None


class LegacyIrrigation(BaseModel):
    state: str = Field(default="IDLE", max_length=20)
    mode: str = Field(default="AUTO", max_length=20)
    remaining_s: int | None = None


class LegacyIn(BaseModel):
    device_id: str = Field(max_length=40)
    readings: LegacyReadings
    irrigation: LegacyIrrigation | None = None


def _legacy_device(device_id: str | None) -> Device:
    if not current_app.config["GK"].legacy_device_api:
        raise ApiError(404, "not_found", "The compatibility API is turned off (GK_LEGACY_DEVICE_API).")
    key = request.headers.get("X-Device-Key", "")
    dev = db().get(Device, device_id or "")
    if dev is None or not key:
        raise ApiError(401, "device_unknown", "Unknown device or missing X-Device-Key.")
    if not hmac.compare_digest(key.encode(), decrypt_secret(dev.key_encrypted).encode()):
        raise ApiError(401, "device_bad_key", "Wrong device key.")
    return dev


@legacy_bp.post("/readings")
def legacy_readings():
    body = LegacyIn.model_validate(request.get_json(silent=True) or {})
    dev = _legacy_device(body.device_id)
    now = utcnow()
    probe = current_app.config.get("GK_LEGACY_PROBE", "S3")  # GPIO32 is S3 in the paper's pin map
    irr = body.irrigation or LegacyIrrigation()
    valve, pump = LEGACY_STATE.get(irr.state.upper(), (0, 0))
    mode = irr.mode.upper()
    prev = dict(dev.last_state_json or {})
    dev.last_state_json = {
        "p": pump, "v": valve, "src": prev.get("src", "adapter"), "sv": body.readings.supply_v, "m": "online",
        "w": (2 if mode == "MANUAL_ON" else 1) if (valve or pump) else 0, "rem": irr.remaining_s or 0, "s": prev.get("s", 0),
        "at": iso(now), "legacy": {"state": irr.state, "mode": mode, "soil_moisture": body.readings.soil_moisture},
        "since": prev.get("since") if (prev.get("p") or prev.get("v")) and (valve or pump) else (iso(now) if valve or pump else None),
    }
    ds.touch_device(dev, now)
    # The sketch reports every 15 s; keep one stored reading per 30-minute slot.
    slot = floor_half_hour(now)
    uuid = f"legacy-{dev.device_id}-{slot.strftime('%Y%m%d%H%M')}"
    sm = body.readings.soil_moisture
    reading = ds.ReadingIn(
        reading_uuid=uuid, recorded_at=iso(now),
        probes=[ds.ProbeIn(id=probe, raw=body.readings.raw_adc, vwc=sm, fault=sm is None)],
        supply_v=body.readings.supply_v, power_source="adapter", control_mode="online", fw="legacy-1probe",
    )
    log, created = ds.store_reading(dev, reading, now, synced=False, time_unsynced=False)
    decision = None
    if created:
        row, _d = run_for_reading(log, current_settings(), dev, now)
        decision = decision_to_device(row)
    return jsonify({"ok": True, "server_time": iso(now), "stored": created, "decision": decision})


@legacy_bp.get("/commands")
def legacy_commands():
    dev = _legacy_device(request.args.get("device_id"))
    now = utcnow()
    ds.touch_device(dev, now)
    cmds = ds.pending_commands(dev, now)
    return jsonify({"t": now.replace(microsecond=0).isoformat() + "Z", "cmd": cmds})


@legacy_bp.post("/commands/<int:command_id>/ack")
def legacy_ack(command_id: int):
    dev = _legacy_device(request.args.get("device_id"))
    return jsonify(ds.ack(dev, command_id, ds.AckIn.model_validate(request.get_json(silent=True) or {}), utcnow()))


@legacy_bp.post("/events")
def legacy_events():
    dev = _legacy_device(request.args.get("device_id"))
    now = utcnow()
    stored = int(ds.store_event(dev, ds.EventIn.model_validate(request.get_json(silent=True) or {}), now))
    return jsonify({"ok": True, "stored": stored})


__all__ = ["bp", "legacy_bp", "DeviceCommand", "select", "timedelta"]
