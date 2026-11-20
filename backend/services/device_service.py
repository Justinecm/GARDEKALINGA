"""Everything the node talks to: readings, polls, commands, events, offline sync,
online/offline periods (FR-COM-01..07, FR-LOG-02)."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, update

from ..db import db
from ..errors import ApiError
from ..models import (
    ActuationEvent,
    ControlDecision,
    Device,
    DeviceCommand,
    DeviceEvent,
    DeviceStatusPeriod,
    PowerStateTransition,
    SensorLog,
)
from ..timeutil import iso, parse_iso
from .settings_service import PROBES, current_settings, set_system_value, to_device

RAW_FAULT_LOW = 205  # 5% of 0-4095 (FR-SEC-04, TC3) FIXED
RAW_FAULT_HIGH = 3890  # 95% FIXED
WATER_SOURCE_CODES = {0: None, 1: "auto", 2: "manual", 3: "offline_failsafe", 4: "sensor_fault_schedule"}


# ------------------------------------------------------------------ payloads
class ProbeIn(BaseModel):
    id: Literal["S1", "S2", "S3"]
    raw: int | None = Field(default=None, ge=0, le=4095)
    vwc: float | None = Field(default=None, ge=0, le=100)
    fault: bool = False


class ReadingIn(BaseModel):
    reading_uuid: str = Field(min_length=8, max_length=40)
    recorded_at: str | None = None
    probes: list[ProbeIn] = Field(min_length=1, max_length=3)
    spatial_mean_vwc: float | None = None
    active_probe_count: int | None = Field(default=None, ge=0, le=3)
    supply_v: float | None = Field(default=None, ge=0, le=30)
    power_source: Literal["solar", "adapter", "unknown"] = "unknown"
    control_mode: Literal["online", "offline_failsafe", "sensor_fault"] = "online"
    settings_version: int | None = None
    fw: str | None = Field(default=None, max_length=24)
    uptime_s: int | None = None
    rssi: int | None = None


class EventIn(BaseModel):
    uuid: str = Field(min_length=8, max_length=40)
    type: Literal["actuation", "power_transition", "boot", "read_now", "fault_schedule_missed", "info"]
    occurred_at: str | None = None
    # actuation
    trigger_source: Literal["auto", "manual", "offline_failsafe", "sensor_fault_schedule"] | None = None
    decision_id: int | None = None
    command_id: int | None = None
    valve_open_at: str | None = None
    pump_on_at: str | None = None
    pump_off_at: str | None = None
    valve_closed_at: str | None = None
    interlock_ms: int | None = None
    close_gap_ms: int | None = None
    duration_s: float | None = None
    ended_reason: Literal["completed", "max_cutoff", "manual_stop", "power_loss", "watchdog"] | None = None
    # power transition (aliases "from"/"to" are Python keywords)
    from_: Literal["solar", "adapter", "unknown"] | None = Field(default=None, alias="from")
    to: Literal["solar", "adapter", "unknown"] | None = None
    supply_v: float | None = None
    # boot
    reset_reason: str | None = Field(default=None, max_length=40)
    fw: str | None = Field(default=None, max_length=24)
    data: dict[str, Any] | None = None

    model_config = {"populate_by_name": True}


class SyncIn(BaseModel):
    readings: list[ReadingIn] = Field(default_factory=list, max_length=200)
    events: list[EventIn] = Field(default_factory=list, max_length=400)


class AckIn(BaseModel):
    status: Literal["executed", "rejected"]
    reason: str | None = Field(default=None, max_length=80)
    at: str | None = None

    @field_validator("reason")
    @classmethod
    def _strip(cls, v: str | None) -> str | None:
        return v.strip() if v else v


# ------------------------------------------------------------------ readings
def _normalise_probes(reading: ReadingIn) -> tuple[dict, dict, dict, float | None, int]:
    raw: dict[str, int | None] = {}
    vwc: dict[str, float | None] = {}
    fault: dict[str, bool] = {}
    for p in reading.probes:
        is_fault = p.fault or (p.raw is not None and (p.raw < RAW_FAULT_LOW or p.raw > RAW_FAULT_HIGH)) or p.vwc is None
        raw[p.id] = p.raw
        fault[p.id] = bool(is_fault)
        vwc[p.id] = None if is_fault else round(float(p.vwc), 2)  # type: ignore[arg-type]
    good = [v for v in vwc.values() if v is not None]
    mean = round(sum(good) / len(good), 2) if good else None  # Equation 2
    return raw, vwc, fault, mean, len(good)


def store_reading(device: Device, reading: ReadingIn, now: datetime, synced: bool, time_unsynced: bool) -> tuple[SensorLog, bool]:
    s = db()
    existing = s.scalars(select(SensorLog).where(SensorLog.reading_uuid == reading.reading_uuid)).first()
    if existing is not None:
        return existing, False
    raw, vwc, fault, mean, count = _normalise_probes(reading)
    recorded = parse_iso(reading.recorded_at) if reading.recorded_at and not time_unsynced else None
    if recorded is None or recorded > now + timedelta(minutes=5):
        recorded = now
    log = SensorLog(
        recorded_at=recorded,
        spatial_mean_vwc=mean,
        active_probe_count=count,
        raw_adc_values=raw,
        control_mode="sensor_fault" if count == 0 and reading.control_mode == "online" else reading.control_mode,
        device_id=device.device_id,
        reading_uuid=reading.reading_uuid,
        probe_vwc_json=vwc,
        probe_fault_json=fault,
        supply_voltage=reading.supply_v,
        power_source=reading.power_source,
        received_at=now,
        synced_offline=synced,
    )
    s.add(log)
    s.flush()
    if reading.fw:
        device.fw_version = reading.fw
    st = current_settings()
    if st.deployment_started_at is None and not synced:
        # The cold start begins with the first live reading (DECISIONS.md).
        set_system_value(deployment_started_at=recorded)
    return log, True


def ingest_live_reading(device: Device, reading: ReadingIn, now: datetime, time_unsynced: bool) -> dict[str, Any]:
    from .decision_engine import decision_to_device, run_for_reading

    touch_device(device, now)
    log, created = store_reading(device, reading, now, synced=False, time_unsynced=time_unsynced)
    s = db()
    if created:
        decision_row, _d = run_for_reading(log, current_settings(), device, now)
    else:  # retried POST: return the same decision
        decision_row = s.scalars(select(ControlDecision).where(ControlDecision.log_id == log.log_id)).first()
    st = current_settings()
    resp: dict[str, Any] = {
        "server_time": iso(now),
        "decision": decision_to_device(decision_row) if decision_row else None,
        "settings": to_device(st) if (reading.settings_version or 0) != st.setting_id else None,
    }
    if time_unsynced:
        resp["time_unsynced"] = True
    return resp


# ------------------------------------------------------------------ events
def store_event(device: Device, ev: EventIn, now: datetime) -> bool:
    s = db()
    if ev.type == "actuation":
        if s.scalars(select(ActuationEvent).where(ActuationEvent.event_uuid == ev.uuid)).first():
            return False
        user_id = None
        if ev.command_id:
            cmd = s.get(DeviceCommand, ev.command_id)
            user_id = cmd.requested_by if cmd else None
        prediction_id = None
        if ev.decision_id:
            from ..models import MLPrediction

            dec = s.get(ControlDecision, ev.decision_id)
            if dec and dec.log_id:
                pred = s.scalars(select(MLPrediction).where(MLPrediction.log_id == dec.log_id)).first()
                prediction_id = pred.prediction_id if pred else None
        valve_open = parse_iso(ev.valve_open_at)
        pump_on = parse_iso(ev.pump_on_at)
        pump_off = parse_iso(ev.pump_off_at)
        valve_closed = parse_iso(ev.valve_closed_at)
        duration = ev.duration_s
        if duration is None and pump_on and pump_off:
            duration = (pump_off - pump_on).total_seconds()
        s.add(
            ActuationEvent(
                prediction_id=prediction_id,
                user_id=user_id,
                trigger_source=ev.trigger_source or ("manual" if ev.command_id else "auto"),
                valve_open_at=valve_open,
                pump_on_at=pump_on,
                pump_off_at=pump_off,
                duration_sec=round(duration, 2) if duration is not None else None,
                event_uuid=ev.uuid,
                device_id=device.device_id,
                command_id=ev.command_id,
                decision_id=ev.decision_id,
                valve_closed_at=valve_closed,
                interlock_ms=ev.interlock_ms,
                close_gap_ms=ev.close_gap_ms,
                ended_reason=ev.ended_reason,
            )
        )
        return True
    if ev.type == "power_transition":
        if s.scalars(select(PowerStateTransition).where(PowerStateTransition.event_uuid == ev.uuid)).first():
            return False
        s.add(
            PowerStateTransition(
                occurred_at=parse_iso(ev.occurred_at) or now,
                from_source=ev.from_ or "unknown",
                to_source=ev.to or "unknown",
                battery_voltage=ev.supply_v,
                event_uuid=ev.uuid,
                device_id=device.device_id,
            )
        )
        return True
    if s.scalars(select(DeviceEvent).where(DeviceEvent.event_uuid == ev.uuid)).first():
        return False
    payload = ev.model_dump(by_alias=True, exclude_none=True)
    s.add(
        DeviceEvent(
            event_uuid=ev.uuid,
            device_id=device.device_id,
            type=ev.type,
            occurred_at=parse_iso(ev.occurred_at) or now,
            payload_json=payload,
        )
    )
    if ev.type == "boot" and ev.fw:
        device.fw_version = ev.fw
    if ev.type == "read_now" and ev.data:
        state = dict(device.last_state_json or {})
        state["read_now"] = {"at": iso(now), **ev.data}
        device.last_state_json = state
    return True


def sync(device: Device, body: SyncIn, now: datetime) -> dict[str, Any]:
    """Offline buffer upload (FR-COM-06). Idempotent; no new decisions."""
    touch_device(device, now)
    stored_r = 0
    for r in body.readings:
        _log, created = store_reading(device, r, now, synced=True, time_unsynced=False)
        stored_r += int(created)
    stored_e = sum(int(store_event(device, e, now)) for e in body.events)
    st = current_settings()
    return {
        "server_time": iso(now),
        "accepted": {"readings": stored_r, "events": stored_e},
        "duplicates": {"readings": len(body.readings) - stored_r, "events": len(body.events) - stored_e},
        "settings": to_device(st),
    }


# ------------------------------------------------------------------ poll and commands
def touch_device(device: Device, now: datetime) -> None:
    device.last_seen_at = now
    s = db()
    open_p = s.scalars(
        select(DeviceStatusPeriod)
        .where(DeviceStatusPeriod.device_id == device.device_id, DeviceStatusPeriod.ended_at.is_(None))
        .order_by(DeviceStatusPeriod.started_at.desc())
        .limit(1)
    ).first()
    if open_p is None or open_p.status == "offline":
        if open_p is not None:
            open_p.ended_at = now
        s.add(DeviceStatusPeriod(device_id=device.device_id, status="online", started_at=now))


def poll(device: Device, args: dict[str, str], now: datetime) -> dict[str, Any]:
    touch_device(device, now)

    def _num(key: str, cast=float, default=None):
        try:
            return cast(args.get(key)) if args.get(key) not in (None, "") else default
        except (TypeError, ValueError):
            return default

    prev = dict(device.last_state_json or {})
    state = {
        **{k: v for k, v in prev.items() if k in ("read_now",)},
        "p": _num("p", int, 0),
        "v": _num("v", int, 0),
        "src": (args.get("src") or "unknown")[:10],
        "sv": _num("sv", float),
        "m": (args.get("m") or "online")[:20],
        "w": _num("w", int, 0),
        "rem": _num("rem", int, 0),
        "s": _num("s", int, 0),
        "at": iso(now),
    }
    if state["p"] or state["v"]:
        state["since"] = prev.get("since") if (prev.get("p") or prev.get("v")) else iso(now)
    device.last_state_json = state

    out = pending_commands(device, now)
    st = current_settings()
    resp: dict[str, Any] = {"t": now.replace(microsecond=0).isoformat() + "Z", "s": st.setting_id}
    if out:
        resp["cmd"] = out
    return resp


def pending_commands(device: Device, now: datetime) -> list[dict[str, Any]]:
    """Commands waiting for this node; marks them delivered (FR-COM-05)."""
    s = db()
    cmds = list(
        s.scalars(
            select(DeviceCommand)
            .where(
                DeviceCommand.device_id == device.device_id,
                DeviceCommand.status.in_(("pending", "delivered")),
                DeviceCommand.expires_at > now,
            )
            .order_by(DeviceCommand.command_id)
            .limit(3)
        )
    )
    out = []
    for c in cmds:
        if c.delivered_at is None:
            c.delivered_at = now
            c.status = "delivered"
        item: dict[str, Any] = {"id": c.command_id, "op": c.op}
        if c.duration_sec:
            item["d"] = c.duration_sec
        out.append(item)
    return out


def ack(device: Device, command_id: int, body: AckIn, now: datetime) -> dict[str, Any]:
    s = db()
    cmd = s.get(DeviceCommand, command_id)
    if cmd is None or cmd.device_id != device.device_id:
        raise ApiError(404, "command_not_found", "No such command for this device.")
    if cmd.acked_at is None:
        cmd.acked_at = now
        cmd.status = body.status
        cmd.result_json = {"reason": body.reason, "device_at": body.at}
        if cmd.delivered_at is None:
            cmd.delivered_at = now
    return {"ok": True, "status": cmd.status}


def is_online(device: Device | None, now: datetime, offline_after_s: int) -> bool:
    return bool(device and device.last_seen_at and (now - device.last_seen_at).total_seconds() <= offline_after_s)


def mark_offline(now: datetime, offline_after_s: int) -> int:
    """Job: close the online period of nodes that stopped polling (FR-COM-07)."""
    s = db()
    n = 0
    for dev in s.scalars(select(Device)):
        if dev.last_seen_at is None or (now - dev.last_seen_at).total_seconds() <= offline_after_s:
            continue
        open_p = s.scalars(
            select(DeviceStatusPeriod)
            .where(DeviceStatusPeriod.device_id == dev.device_id, DeviceStatusPeriod.ended_at.is_(None))
            .limit(1)
        ).first()
        if open_p is not None and open_p.status == "online":
            cut = dev.last_seen_at + timedelta(seconds=offline_after_s)
            open_p.ended_at = cut
            s.add(DeviceStatusPeriod(device_id=dev.device_id, status="offline", started_at=cut))
            n += 1
    return n


def expire_commands(now: datetime) -> int:
    res = db().execute(
        update(DeviceCommand)
        .where(DeviceCommand.status.in_(("pending", "delivered")), DeviceCommand.expires_at <= now)
        .values(status="expired")
    )
    return res.rowcount or 0


def primary_device() -> Device | None:
    return db().scalars(select(Device).order_by(Device.created_at).limit(1)).first()


__all__ = [
    "AckIn",
    "EventIn",
    "PROBES",
    "ReadingIn",
    "SyncIn",
    "WATER_SOURCE_CODES",
    "ack",
    "pending_commands",
    "expire_commands",
    "ingest_live_reading",
    "is_online",
    "mark_offline",
    "poll",
    "primary_device",
    "store_event",
    "sync",
    "touch_device",
]
