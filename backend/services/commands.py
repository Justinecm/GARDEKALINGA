"""Manual override (Tier 2): Start / Stop commands from the dashboard (FR-UI-05/06, FR-COM-05)."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from flask import current_app
from sqlalchemy import select, update

from ..db import db
from ..errors import ApiError
from ..models import Device, DeviceCommand, SensorLog, User
from ..timeutil import iso
from .audit import audit
from .device_service import is_online
from .settings_service import current_settings

STILL_WAITING_S = 6


def _cfg():
    return current_app.config["GK"]


def latest_reading(device_id: str | None) -> SensorLog | None:
    q = select(SensorLog).order_by(SensorLog.recorded_at.desc()).limit(1)
    if device_id:
        q = q.where(SensorLog.device_id == device_id)
    return db().scalars(q).first()


def start_blocked_reason(device: Device | None, now: datetime) -> str | None:
    if device is None:
        return "no_device"
    if not is_online(device, now, _cfg().offline_after_s):
        return "offline"
    st = device.last_state_json or {}
    if int(st.get("w") or 0) == 4:
        return "fault_schedule"
    if st.get("p") or st.get("v"):
        return "already_running"
    pending = db().scalars(
        select(DeviceCommand).where(
            DeviceCommand.device_id == device.device_id,
            DeviceCommand.op == "start",
            DeviceCommand.status.in_(("pending", "delivered")),
            DeviceCommand.expires_at > now,
        )
    ).first()
    if pending is not None:
        return "already_running"
    return None


def create_start(device: Device | None, user: User, duration_s: int, now: datetime) -> DeviceCommand:
    reason = start_blocked_reason(device, now)
    if reason:
        messages = {
            "no_device": "No controller is registered yet.",
            "offline": "The controller is offline, so it cannot receive the command.",
            "fault_schedule": "All sensors have a problem and the twice-a-day schedule is running.",
            "already_running": "Watering is already running.",
        }
        raise ApiError(409, f"start_blocked_{reason}", messages[reason])
    st = current_settings()
    # Tier 1: never more than max_actuation_sec.
    duration = max(10, min(int(duration_s), st.max_actuation_sec))
    cmd = DeviceCommand(
        device_id=device.device_id,  # type: ignore[union-attr]
        op="start",
        duration_sec=duration,
        requested_by=user.user_id,
        created_at=now,
        expires_at=now + timedelta(seconds=_cfg().command_ttl_s),
        status="pending",
    )
    db().add(cmd)
    db().flush()
    audit("watering.start", f"command:{cmd.command_id}", None, {"duration_s": duration, "requested_s": duration_s})
    return cmd


def create_stop(device: Device | None, user: User, now: datetime) -> DeviceCommand:
    if device is None:
        raise ApiError(409, "start_blocked_no_device", "No controller is registered yet.")
    s = db()
    # A Stop cancels any Start that has not reached the node yet.
    s.execute(
        update(DeviceCommand)
        .where(DeviceCommand.device_id == device.device_id, DeviceCommand.op == "start", DeviceCommand.status == "pending")
        .values(status="cancelled")
    )
    cmd = DeviceCommand(
        device_id=device.device_id,
        op="stop",
        duration_sec=None,
        requested_by=user.user_id,
        created_at=now,
        expires_at=now + timedelta(seconds=_cfg().command_ttl_s),
        status="pending",
    )
    s.add(cmd)
    s.flush()
    audit("watering.stop", f"command:{cmd.command_id}")
    return cmd


def create_read_now(device: Device, user: User, now: datetime) -> DeviceCommand:
    cmd = DeviceCommand(
        device_id=device.device_id,
        op="read_now",
        requested_by=user.user_id,
        created_at=now,
        expires_at=now + timedelta(seconds=_cfg().command_ttl_s),
        status="pending",
    )
    db().add(cmd)
    db().flush()
    audit("device.read_now", f"command:{cmd.command_id}")
    return cmd


def command_view(cmd: DeviceCommand, now: datetime) -> dict[str, Any]:
    age = (now - cmd.created_at).total_seconds()
    phase = cmd.status
    if cmd.status in ("pending", "delivered") and cmd.expires_at <= now:
        phase = "expired"
    if phase == "pending":
        phase = "sending" if age < STILL_WAITING_S else "still_waiting"
    latency = None
    if cmd.acked_at:
        latency = round((cmd.acked_at - cmd.created_at).total_seconds(), 2)
    return {
        "id": cmd.command_id,
        "op": cmd.op,
        "duration_s": cmd.duration_sec,
        "status": cmd.status,
        "phase": phase,  # sending | still_waiting | delivered | executed | rejected | expired | cancelled
        "created_at": iso(cmd.created_at),
        "delivered_at": iso(cmd.delivered_at),
        "acked_at": iso(cmd.acked_at),
        "latency_s": latency,
        "reason": (cmd.result_json or {}).get("reason"),
        "requested_by": cmd.requested_by,
    }
