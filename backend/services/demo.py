"""Demo mode (GK_DEMO_MODE=true): a virtual Box B node that lives inside the API.

Purpose: a Vercel preview that works with no hardware, for the thesis defense and
for beta testers. It is NOT the device simulator (tools/device_simulator.py signs
real HTTP requests like the firmware); it writes the same tables directly.

On every dashboard status call `tick(now)`:
  * delivers and executes pending Start/Stop commands after ~1.5 s,
  * finishes watering cycles (valve 500 ms before pump, pump off then valve),
  * generates the 30-minute readings that are due (soil dries by day, wets
    with rain and watering) and runs the real decision engine on each,
  * runs the 06:00 / 16:00 schedule when all probes are faulty,
  * keeps an offline buffer and syncs it when the node "comes back".
The demo controls (GET/POST /api/v1/demo) change faults, connectivity, power and rain.
"""
from __future__ import annotations

import math
import random
import uuid
from datetime import datetime, timedelta
from typing import Any

from flask import current_app
from sqlalchemy import func, select

from ..db import db
from ..models import (
    ActuationEvent,
    AppState,
    Device,
    DeviceCommand,
    DeviceStatusPeriod,
    MLModel,
    PowerStateTransition,
    SensorLog,
    User,
    WeatherForecast,
)
from ..timeutil import floor_half_hour, iso, parse_iso, to_manila, utcnow
from .device_service import ProbeIn, ReadingIn, store_reading, touch_device
from .settings_service import PROBES, current_settings, set_system_value

DEMO_DEVICE = "gk-node-01"
DEMO_PASSWORD = "gardekalinga-demo"
DEMO_USERS = [
    ("manager", "Maria Santos (demo manager)", "manager"),
    ("caretaker", "Jun dela Cruz (demo caretaker)", "caretaker"),
    ("leader", "Ate Lorna Reyes (demo leader)", "leader"),
]
HISTORY_DAYS = 17
PROBE_DRY = {"S1": 1.0, "S2": 1.1, "S3": 0.93}  # S2 gets the most afternoon sun
PROBE_WET = {"S1": 1.0, "S2": 0.96, "S3": 1.04}


# ------------------------------------------------------------------ state
def _get_state() -> dict[str, Any] | None:
    row = db().get(AppState, "demo")
    return dict(row.value_json) if row else None


def _put_state(state: dict[str, Any]) -> None:
    s = db()
    row = s.get(AppState, "demo")
    if row is None:
        s.add(AppState(key="demo", value_json=state, updated_at=utcnow()))
    else:
        row.value_json = dict(state)
        row.updated_at = utcnow()


def public_state() -> dict[str, Any]:
    st = _get_state() or {}
    return {
        "faults": st.get("faults", {p: False for p in PROBES}),
        "offline": st.get("offline", False),
        "power": st.get("power", "solar"),
        "force_rain": bool(st.get("force_rain_until") and parse_iso(st["force_rain_until"]) > utcnow()),
        "buffered": len(st.get("buffer", [])),
        "soil": st.get("soil"),
    }


# ------------------------------------------------------------------ physics
def _evaporation(slot: datetime, temp_c: float) -> float:
    h = to_manila(slot).hour + to_manila(slot).minute / 60
    sun = max(0.0, math.sin((h - 6) / 12 * math.pi))  # 0 at night, 1 at noon
    return 0.1 + 0.62 * sun * (1 + (temp_c - 29) * 0.04)


def _raw_from_vwc(vwc: float, cal: dict) -> int:
    frac = (vwc - cal["vwc_dry"]) / (cal["vwc_sat"] - cal["vwc_dry"])
    return int(round(cal["adc_dry"] - frac * (cal["adc_dry"] - cal["adc_sat"])))


def _supply(source: str, slot: datetime, rng: random.Random) -> float:
    if source == "adapter":
        return round(12.0 + rng.uniform(-0.04, 0.04), 2)
    h = to_manila(slot).hour
    if 8 <= h <= 15:
        return round(13.4 + rng.uniform(-0.15, 0.2), 2)
    if 16 <= h <= 19:
        return round(12.9 + rng.uniform(-0.1, 0.1), 2)
    return round(12.4 - (h if h < 8 else 0) * 0.08 + rng.uniform(-0.05, 0.05), 2)


# ------------------------------------------------------------------ seeding
def ensure_seeded(now: datetime) -> bool:
    s = db()
    if _get_state() is not None:
        return False
    from ..security import hash_password

    # Users (demo only; real deployments create the first manager from the CLI).
    if s.scalar(select(func.count()).select_from(User)) == 0:
        pw = hash_password(DEMO_PASSWORD)
        for username, name, role in DEMO_USERS:
            s.add(User(full_name=name, username=username, password_hash=pw, role=role, created_at=now - timedelta(days=HISTORY_DAYS + 1),
                       is_active=True, language=None, theme="auto"))
    if s.get(Device, DEMO_DEVICE) is None:
        from ..device_auth import encrypt_secret, new_device_secret

        s.add(Device(device_id=DEMO_DEVICE, name="Box B (virtual demo node)", key_encrypted=encrypt_secret(new_device_secret()),
                     key_rotated_at=now, created_at=now - timedelta(days=HISTORY_DAYS), fw_version="1.0.0-demo",
                     last_state_json={"p": 0, "v": 0, "src": "solar", "sv": 13.2, "m": "online", "w": 0, "rem": 0, "s": 1}))
    s.flush()
    start = floor_half_hour(now - timedelta(days=HISTORY_DAYS))
    current_settings()
    set_system_value(deployment_started_at=start, power_setup="hybrid")
    s.add(DeviceStatusPeriod(device_id=DEMO_DEVICE, status="online", started_at=start))
    state = {
        "faults": {p: False for p in PROBES},
        "offline": False,
        "power": "solar",
        "soil": {"S1": 34.0, "S2": 32.5, "S3": 35.5},
        "last_slot": iso(start - timedelta(minutes=30)),
        "last_forecast": None,
        "watering": None,
        "buffer": [],
        "force_rain_until": None,
        "model_loaded": False,
        "seeded_at": iso(now),
    }
    _put_state(state)
    s.flush()
    _advance(now, state, history=True)
    _put_state(state)
    # Daily water use (Equation 8) for the seeded history.
    from .jobs import compute_daily_water

    st = current_settings()
    day = to_manila(start).date()
    while day <= to_manila(now).date():
        compute_daily_water(day.isoformat(), st.flow_rate_lpm)
        day += timedelta(days=1)
    return True


def _load_demo_model(now: datetime) -> None:
    """Attach the bundled demo model (trained offline by tools/make_demo_model.py with scikit-learn)."""
    import json
    import os
    import zlib

    s = db()
    if s.scalar(select(func.count()).select_from(MLModel)) > 0:
        return
    path = os.path.join(os.path.dirname(__file__), "ml", "demo_model.json.z")
    if not os.path.exists(path):
        return
    blob = open(path, "rb").read()
    meta = json.loads(zlib.decompress(blob).decode()).get("meta", {})
    m = meta.get("metrics", {})
    s.add(
        MLModel(
            model_version=meta.get("version", "rf-demo"),
            trained_at=now,
            rows=int(meta.get("rows", 0)),
            date_from=now - timedelta(days=HISTORY_DAYS),
            date_to=now - timedelta(days=HISTORY_DAYS - 14),
            mae=float(m.get("mae", 0)),
            rmse=float(m.get("rmse", 0)),
            baseline_mae=float(m.get("baseline_mae", 0)),
            baseline_rmse=float(m.get("baseline_rmse", 0)),
            is_active=bool(meta.get("beats_baseline")),
            notes="Demo model trained with scikit-learn on simulated data (tools/make_demo_model.py).",
            metadata_json={k: v for k, v in meta.items() if k != "held_out"} | {"held_out": meta.get("held_out", [])[:200]},
            artifact=blob,
        )
    )
    s.flush()


# ------------------------------------------------------------------ main loop
def tick(now: datetime) -> None:
    if not current_app.config["GK"].demo_mode:
        return
    if ensure_seeded(now):
        return
    state = _get_state()
    if state is None:
        return
    _advance(now, state, history=False)
    _put_state(state)


def _device() -> Device:
    return db().get(Device, DEMO_DEVICE)  # type: ignore[return-value]


def _advance(now: datetime, state: dict[str, Any], history: bool) -> None:
    from .decision_engine import run_for_reading
    from .weather import step_time, synthetic_forecast, synthetic_step

    s = db()
    dev = _device()
    st = current_settings()
    rng = random.Random(int(now.timestamp()))

    # Commands first (live only): delivery ~1.0 s, execution ack ~1.6 s.
    if not history and not state.get("offline"):
        _process_commands(now, state, dev)

    last_slot = parse_iso(state["last_slot"])
    slot = last_slot + timedelta(minutes=30)  # type: ignore[operator]
    deploy_start = st.deployment_started_at or slot
    max_slots = 48 * (HISTORY_DAYS + 1)
    n = 0
    while slot <= now and n < max_slots:
        n += 1
        srng = random.Random(int(slot.timestamp()))
        # Forecast batches every 3 h (hourly in OWM mode; 3 h keeps the demo DB small).
        lf = parse_iso(state.get("last_forecast")) if state.get("last_forecast") else None
        if lf is None or slot - lf >= timedelta(hours=3 if history else 1):
            rain_until = parse_iso(state["force_rain_until"]) if state.get("force_rain_until") else None
            for row in synthetic_forecast(st.garden_lat, slot, force_rain_until=rain_until, steps=12 if history else 40):
                s.add(row)
            state["last_forecast"] = iso(slot)
            if not history:
                from .weather import _set_state

                _set_state("forecast_status", {"ok": True, "source": "demo", "retrieved_at": iso(slot), "steps": 40, "last_error": None})
        if history and slot >= deploy_start + timedelta(days=st.cold_start_days) and not state.get("model_loaded"):
            s.flush()
            _load_demo_model(slot)
            state["model_loaded"] = True

        # Weather acts on the soil.
        forced = bool(state.get("force_rain_until") and parse_iso(state["force_rain_until"]) >= slot)
        wx = synthetic_step(step_time(slot), st.garden_lat, forced)
        for p in PROBES:
            v = state["soil"][p]
            v -= _evaporation(slot, wx["temperature_c"]) * PROBE_DRY[p] * srng.uniform(0.8, 1.2)
            v += (wx["rain_3h_mm"] / 6.0) * 1.1 * PROBE_WET[p]
            if v > 37.0:  # drainage above field capacity
                v -= (v - 37.0) * 0.12
            state["soil"][p] = round(max(9.0, min(46.0, v)), 2)

        # Power: on some nights the battery falls to 11.6 V and Box A changes over.
        _power_step(slot, state, dev, srng, history)

        reading = _reading_for(slot, state, st, srng)
        if state.get("offline") and not history:
            state.setdefault("buffer", []).append(reading.model_dump())
            _offline_failsafe(slot, state, st)
        else:
            log, created = store_reading(dev, reading, slot, synced=False, time_unsynced=False)
            if created:
                dev.last_state_json = {**(dev.last_state_json or {}), "p": 0, "v": 0}
                saved_state = dict(dev.last_state_json)
                if state.get("watering"):
                    dev.last_state_json = {**saved_state, "p": 1, "v": 1}
                row, d = run_for_reading(log, current_settings(), dev, slot)
                dev.last_state_json = saved_state
                if d.action == "water" and d.duration_s:
                    _begin_watering(slot + timedelta(seconds=4), state, d.duration_s, "auto", decision_id=row.decision_id, now=now)
            if log.active_probe_count == 0:
                _fault_schedule(slot, state, st, now)
        state["last_slot"] = iso(slot)
        slot += timedelta(minutes=30)
        s.flush()

    # Finish a cycle whose time is up.
    w = state.get("watering")
    if w and parse_iso(w["start"]) + timedelta(seconds=w["duration"]) <= now:  # type: ignore[operator]
        _finish_watering(state, parse_iso(w["start"]) + timedelta(seconds=w["duration"]), "completed")  # type: ignore[operator]

    # Live node state (what the 3-second poll would report).
    if not history and not state.get("offline"):
        touch_device(dev, now)
        w = state.get("watering")
        rem = 0
        if w:
            rem = max(0, int((parse_iso(w["start"]) + timedelta(seconds=w["duration"]) - now).total_seconds()))  # type: ignore[operator]
        valve = bool(w)
        pump = bool(w) and (now - parse_iso(w["start"])).total_seconds() >= 0.5  # type: ignore[operator]
        code = {"auto": 1, "manual": 2, "offline_failsafe": 3, "sensor_fault_schedule": 4}.get((w or {}).get("source", ""), 0)
        prev = dev.last_state_json or {}
        dev.last_state_json = {
            "p": int(pump), "v": int(valve), "src": state.get("power", "solar"),
            "sv": _supply(state.get("power", "solar"), now, rng), "m": "online" if any(not f for f in state["faults"].values()) else "sensor_fault",
            "w": code, "rem": rem, "s": current_settings().setting_id, "at": iso(now),
            "since": (w or {}).get("start"), "read_now": prev.get("read_now"),
        }
    elif history:
        dev.last_seen_at = now
        touch_device(dev, now)


def _reading_for(slot: datetime, state: dict, st, rng: random.Random) -> ReadingIn:
    cal = st.calibration_json
    probes = []
    for p in PROBES:
        if state["faults"].get(p):
            probes.append(ProbeIn(id=p, raw=rng.choice([38, 61, 4095]), vwc=None, fault=True))
        else:
            v = state["soil"][p] + rng.uniform(-0.25, 0.25)
            probes.append(ProbeIn(id=p, raw=_raw_from_vwc(v, cal[p]), vwc=round(v, 2), fault=False))
    good = [pr.vwc for pr in probes if not pr.fault and pr.vwc is not None]
    return ReadingIn(
        reading_uuid=str(uuid.uuid5(uuid.NAMESPACE_URL, f"demo-{iso(slot)}")),
        recorded_at=iso(slot),
        probes=probes,
        spatial_mean_vwc=round(sum(good) / len(good), 2) if good else None,
        active_probe_count=len(good),
        supply_v=_supply(state.get("power", "solar"), slot, rng),
        power_source=state.get("power", "solar"),
        control_mode="online" if good else "sensor_fault",
        settings_version=st.setting_id,
        fw="1.0.0-demo",
    )


def _power_step(slot: datetime, state: dict, dev: Device, rng: random.Random, history: bool) -> None:
    if not history:
        return  # live changes come from the demo controls
    local = to_manila(slot)
    day_no = int(slot.timestamp() // 86400)
    if day_no % 3 == 0 and local.hour == 3 and local.minute == 30 and state["power"] == "solar":
        _transition(slot, state, dev, "solar", "adapter", round(11.58 + rng.uniform(-0.02, 0.01), 2))
    elif local.hour == 9 and local.minute == 0 and state["power"] == "adapter":
        _transition(slot, state, dev, "adapter", "solar", round(12.84 + rng.uniform(0, 0.08), 2))


def _transition(at: datetime, state: dict, dev: Device, frm: str, to: str, volts: float) -> None:
    state["power"] = to
    db().add(PowerStateTransition(occurred_at=at, from_source=frm, to_source=to, battery_voltage=volts,
                                  event_uuid=str(uuid.uuid4()), device_id=dev.device_id))


def _begin_watering(start: datetime, state: dict, duration: int, source: str, decision_id=None, command_id=None, user_id=None, now=None) -> None:
    if state.get("watering"):
        return
    state["watering"] = {"start": iso(start), "duration": int(duration), "source": source, "decision_id": decision_id,
                         "command_id": command_id, "user_id": user_id}
    if now is not None and start + timedelta(seconds=duration) <= now:
        _finish_watering(state, start + timedelta(seconds=duration), "completed")


def _finish_watering(state: dict, pump_off: datetime, reason: str) -> None:
    w = state.get("watering")
    if not w:
        return
    start = parse_iso(w["start"])
    rng = random.Random(int(start.timestamp()))  # type: ignore[union-attr]
    interlock = 500 + rng.randint(-4, 6)
    gap = 100 + rng.randint(-3, 4)
    pump_on = start + timedelta(milliseconds=interlock)  # type: ignore[operator]
    if pump_off < pump_on:
        pump_off = pump_on
    secs = (pump_off - pump_on).total_seconds()
    db().add(
        ActuationEvent(
            user_id=w.get("user_id"), trigger_source=w["source"], valve_open_at=start, pump_on_at=pump_on, pump_off_at=pump_off,
            duration_sec=round(secs, 2), event_uuid=str(uuid.uuid4()), device_id=DEMO_DEVICE, command_id=w.get("command_id"),
            decision_id=w.get("decision_id"), valve_closed_at=pump_off + timedelta(milliseconds=gap), interlock_ms=interlock,
            close_gap_ms=gap, ended_reason=reason,
        )
    )
    for p in PROBES:
        state["soil"][p] = round(min(46.0, state["soil"][p] + 0.047 * secs * PROBE_WET[p]), 2)
    state["watering"] = None


def _process_commands(now: datetime, state: dict, dev: Device) -> None:
    s = db()
    cmds = list(s.scalars(select(DeviceCommand).where(DeviceCommand.device_id == DEMO_DEVICE,
                                                      DeviceCommand.status.in_(("pending", "delivered")),
                                                      DeviceCommand.expires_at > now).order_by(DeviceCommand.command_id)))
    for c in cmds:
        age = (now - c.created_at).total_seconds()
        if age >= 1.0 and c.delivered_at is None:
            c.delivered_at = c.created_at + timedelta(milliseconds=1000 + (c.command_id * 137) % 600)
            c.status = "delivered"
        if age >= 1.6 and c.delivered_at is not None:
            c.acked_at = c.delivered_at + timedelta(milliseconds=420)
            if c.op == "start":
                if state.get("watering"):
                    c.status, c.result_json = "rejected", {"reason": "already_watering"}
                else:
                    c.status = "executed"
                    _begin_watering(c.acked_at, state, c.duration_sec or 60, "manual", command_id=c.command_id, user_id=c.requested_by)
            elif c.op == "stop":
                c.status = "executed"
                if state.get("watering"):
                    _finish_watering(state, c.acked_at, "manual_stop")
            elif c.op == "read_now":
                c.status = "executed"
                st = current_settings()
                rd = _reading_for(now, state, st, random.Random(int(now.timestamp())))
                dev.last_state_json = {**(dev.last_state_json or {}), "read_now": {
                    "at": iso(now), "probes": [p.model_dump() for p in rd.probes]}}
            else:
                c.status, c.result_json = "rejected", {"reason": "unsupported"}


def _offline_failsafe(slot: datetime, state: dict, st) -> None:
    """While 'offline' the node decides from its own readings (FR-FS-01)."""
    good = [state["soil"][p] for p in PROBES if not state["faults"].get(p)]
    if not good or state.get("watering"):
        return
    last_end = state.get("offline_last_end")
    if last_end and slot < parse_iso(last_end) + timedelta(seconds=st.soak_interval_sec):  # type: ignore[operator]
        return
    mean = sum(good) / len(good)
    if mean < st.moisture_threshold or min(good) < st.probe_min_vwc:
        _begin_watering(slot + timedelta(seconds=3), state, st.max_actuation_sec, "offline_failsafe", now=slot + timedelta(minutes=30))
        state["offline_last_end"] = iso(slot + timedelta(seconds=3 + st.max_actuation_sec))


def _fault_schedule(slot: datetime, state: dict, st, now: datetime) -> None:
    """FR-FS-03: 06:00 (60%) and 16:00 (40%) when all probes are faulty."""
    local = to_manila(slot)
    hhmm = local.strftime("%H:%M")
    if hhmm not in (st.fault_am_time, st.fault_pm_time):
        return
    share = st.fault_am_share if hhmm == st.fault_am_time else 1 - st.fault_am_share
    total_s = share * st.daily_water_l / st.flow_rate_lpm * 60
    t = slot + timedelta(seconds=2)
    while total_s > 0.5:
        run = min(total_s, st.max_actuation_sec)
        state["watering"] = None
        _begin_watering(t, state, int(round(run)), "sensor_fault_schedule", now=now)
        total_s -= run
        t += timedelta(seconds=run + st.soak_interval_sec)


# ------------------------------------------------------------------ controls
def apply_action(action: str, value: Any, now: datetime) -> dict[str, Any]:
    from .audit import audit

    state = _get_state()
    if state is None:
        ensure_seeded(now)
        state = _get_state() or {}
    dev = _device()
    if action == "fault":
        probe = str(value.get("probe")) if isinstance(value, dict) else ""
        if probe in PROBES:
            state["faults"][probe] = bool(value.get("on"))
    elif action == "offline":
        going_offline = bool(value)
        if going_offline and not state.get("offline"):
            state["offline"] = True
            dev.last_seen_at = now - timedelta(seconds=current_app.config["GK"].offline_after_s + 1)
        elif not going_offline and state.get("offline"):
            state["offline"] = False
            _sync_buffer(now, state, dev)
    elif action == "power":
        to = "adapter" if value == "adapter" else "solar"
        if state.get("power") != to:
            _transition(now, state, dev, state.get("power", "solar"), to, 11.58 if to == "adapter" else 12.86)
    elif action == "rain":
        state["force_rain_until"] = iso(now + timedelta(hours=6)) if value else None
        from .weather import _set_state, synthetic_forecast

        st = current_settings()
        for row in synthetic_forecast(st.garden_lat, now, force_rain_until=parse_iso(state["force_rain_until"]) if value else None):
            db().add(row)
        state["last_forecast"] = iso(now)
        _set_state("forecast_status", {"ok": True, "source": "demo", "retrieved_at": iso(now), "steps": 40, "last_error": None})
    elif action == "dry":
        for p in PROBES:
            state["soil"][p] = round(random.uniform(17.5, 21.5), 2)
        # Take a reading right away so the change shows and the engine decides.
        state["last_slot"] = iso(now - timedelta(minutes=30))
    elif action == "reset":
        state["faults"] = {p: False for p in PROBES}
        state["force_rain_until"] = None
        # Replace any forced-rain forecast with a normal one right away.
        from .weather import _set_state, synthetic_forecast

        for row in synthetic_forecast(current_settings().garden_lat, now):
            db().add(row)
        state["last_forecast"] = iso(now)
        _set_state("forecast_status", {"ok": True, "source": "demo", "retrieved_at": iso(now), "steps": 40, "last_error": None})
        if state.get("offline"):
            state["offline"] = False
            _sync_buffer(now, state, dev)
    else:
        from ..errors import ApiError

        raise ApiError(422, "unknown_action", "Unknown demo action.")
    _put_state(state)
    audit("demo." + action, "demo", None, {"value": value})
    db().flush()
    tick(now)
    return public_state()


def _sync_buffer(now: datetime, state: dict, dev: Device) -> None:
    for r in state.get("buffer", []):
        rd = ReadingIn(**r)
        rd.control_mode = "offline_failsafe" if rd.control_mode == "online" else rd.control_mode
        store_reading(dev, rd, now, synced=True, time_unsynced=False)
    state["buffer"] = []
    touch_device(dev, now)


def latest_forecast_age(now: datetime) -> timedelta | None:
    last = db().scalar(select(func.max(WeatherForecast.retrieved_at)))
    return None if last is None else now - last


def readings_count() -> int:
    return db().scalar(select(func.count()).select_from(SensorLog)) or 0
