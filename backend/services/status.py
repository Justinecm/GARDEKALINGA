"""GET /api/v1/status: everything the Garden screen needs in one call (FR-UI-01..03)."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from flask import current_app
from sqlalchemy import select

from ..db import db
from ..models import ControlDecision, Device, DeviceCommand, MLPrediction, PowerStateTransition
from ..timeutil import floor_hour, iso
from . import rain_pause as rp
from .commands import command_view, latest_reading, start_blocked_reason
from .decision_engine import last_watering_end
from .device_service import WATER_SOURCE_CODES, is_online, primary_device
from .ml.inference import active_model
from .settings_service import PROBES, current_settings, phase_info
from .weather import forecast_status

GETTING_DRY_MARGIN = 3.0  # % VWC above the threshold where "getting dry" starts (DECISIONS.md)


def probe_level(vwc: float | None, fault: bool, threshold: float, pmin: float) -> str:
    if fault or vwc is None:
        return "critical"
    if vwc < pmin:
        return "serious"
    if vwc < threshold + GETTING_DRY_MARGIN:
        return "warning"
    return "good"


def build_status(now: datetime, user_role: str) -> dict[str, Any]:
    cfg = current_app.config["GK"]
    st = current_settings()
    device: Device | None = primary_device()
    online = is_online(device, now, cfg.offline_after_s)
    state = (device.last_state_json or {}) if device else {}
    log = latest_reading(device.device_id if device else None)
    model = active_model()
    phase = phase_info(st, now, model is not None)

    # ---- reading
    reading = None
    if log is not None:
        vwc = log.probe_vwc_json or {}
        faults = log.probe_fault_json or {}
        raws = log.raw_adc_values or {}
        cal = st.calibration_json or {}
        probes = []
        for p in PROBES:
            installed = p in vwc or p in raws
            probes.append(
                {
                    "id": p,
                    "installed": installed,
                    "vwc": vwc.get(p),
                    "raw": raws.get(p),
                    "fault": bool(faults.get(p)) if installed else False,
                    "level": probe_level(vwc.get(p), bool(faults.get(p)), st.moisture_threshold, st.probe_min_vwc)
                    if installed
                    else "none",
                    "calibrated_at": (cal.get(p) or {}).get("calibrated_at"),
                }
            )
        reading = {
            "log_id": log.log_id,
            "recorded_at": iso(log.recorded_at),
            "mean": log.spatial_mean_vwc,
            "active_count": log.active_probe_count,
            "probes": probes,
            "supply_v": log.supply_voltage,
            "power_source": log.power_source,
            "control_mode": log.control_mode,
            "synced_offline": log.synced_offline,
        }

    # ---- overall status code
    if log is None:
        code, level = "no_readings", "none"
    elif log.active_probe_count == 0 or log.spatial_mean_vwc is None:
        code, level = "sensor_fault", "critical"
    else:
        levels = [p["level"] for p in reading["probes"] if p["installed"] and not p["fault"]]  # type: ignore[index]
        mean = log.spatial_mean_vwc
        if "serious" in levels:
            code, level = "below_minimum", "serious"
        elif mean < st.moisture_threshold + GETTING_DRY_MARGIN:
            code, level = "getting_dry", "warning"
        else:
            code, level = "moist_enough", "good"
    if device is not None and not online:
        code_offline = True
    else:
        code_offline = False

    # ---- watering (state-synchronised: from what the node reports)
    w_code = int(state.get("w") or 0)
    watering_active = bool(state.get("p") or state.get("v")) and online
    s = db()
    pending_cmd = None
    if device is not None:
        c = s.scalars(
            select(DeviceCommand)
            .where(DeviceCommand.device_id == device.device_id, DeviceCommand.created_at > now - timedelta(seconds=90))
            .order_by(DeviceCommand.command_id.desc())
            .limit(1)
        ).first()
        if c is not None:
            pending_cmd = command_view(c, now)

    # ---- soak
    last_end = last_watering_end(device.device_id if device else None)
    soak = {"active": False, "remaining_s": 0, "ends_at": None, "last_watering_end": iso(last_end)}
    if last_end is not None:
        ends = last_end + timedelta(seconds=st.soak_interval_sec)
        if now < ends and not watering_active:
            soak = {"active": True, "remaining_s": int((ends - now).total_seconds()), "ends_at": iso(ends), "last_watering_end": iso(last_end)}

    # ---- decision, rain pause, prediction, weather
    dec = s.scalars(select(ControlDecision).order_by(ControlDecision.decision_id.desc()).limit(1)).first()
    rain = rp.rain_pause(now, st.rain_pop_pct, st.rain_mm, st.rain_window_h)
    retrieved, batch = rp.latest_batch(now)
    upcoming = [b for b in batch if b.forecast_for >= now - timedelta(hours=1)]
    weather_now = None
    if upcoming:
        b = upcoming[0]
        weather_now = {"for": iso(b.forecast_for), "condition": b.weather_condition, "temperature_c": b.temperature_c,
                       "humidity_pct": b.humidity_pct, "pop_pct": b.pop_pct, "rain_3h_mm": b.rain_3h_mm}
    pred = s.scalars(
        select(MLPrediction).where(MLPrediction.target_at >= floor_hour(now) - timedelta(hours=1)).order_by(MLPrediction.prediction_id.desc()).limit(1)
    ).first()

    last_tr = s.scalars(select(PowerStateTransition).order_by(PowerStateTransition.occurred_at.desc()).limit(1)).first()
    source = state.get("src") if online and state.get("src") else (reading or {}).get("power_source")
    if (source in (None, "unknown")) and st.power_setup == "adapter_only":
        # Box A not installed yet: the 12 V adapter (about 12.0 V) is the only source (FR-PWR-02).
        source = "adapter"
    supply_v = state.get("sv") if online and state.get("sv") is not None else (reading or {}).get("supply_v")

    next_check = None
    if log is not None:
        next_check = log.recorded_at + timedelta(minutes=30)
        while next_check < now - timedelta(minutes=5):
            next_check += timedelta(minutes=30)

    return {
        "server_time": iso(now),
        "status": {"code": code, "level": level, "offline": code_offline},
        "device": None
        if device is None
        else {
            "id": device.device_id,
            "name": device.name,
            "online": online,
            "last_seen_at": iso(device.last_seen_at),
            "fw": device.fw_version,
            "mode": state.get("m"),
            "read_now": state.get("read_now"),
        },
        "reading": reading,
        "next_check_at": iso(next_check),
        "phase": phase,
        "decision": None
        if dec is None
        else {
            "id": dec.decision_id,
            "action": dec.action,
            "reason": dec.reason_code,
            "created_at": iso(dec.created_at),
            "duration_s": dec.duration_sec,
            "need_reason": (dec.inputs_json or {}).get("need_reason"),
        },
        "rain_pause": rain.as_dict() | {"rule": {"pop_pct": st.rain_pop_pct, "rain_mm": st.rain_mm, "window_h": st.rain_window_h}},
        "soak": soak,
        "watering": {
            "active": watering_active,
            "pump": bool(state.get("p")) if online else False,
            "valve": bool(state.get("v")) if online else False,
            "source": WATER_SOURCE_CODES.get(w_code),
            "remaining_s": int(state.get("rem") or 0) if watering_active else 0,
            "since": state.get("since") if watering_active else None,
            "command": pending_cmd,
            "start_blocked": start_blocked_reason(device, now) if user_role != "leader" else "role",
            "last_known": {"pump": bool(state.get("p")), "valve": bool(state.get("v")), "at": state.get("at")},
        },
        "power": {
            "source": source or "unknown",
            "supply_v": supply_v,
            "setup": st.power_setup,
            "last_transition": None
            if last_tr is None
            else {"at": iso(last_tr.occurred_at), "from": last_tr.from_source, "to": last_tr.to_source, "v": last_tr.battery_voltage},
        },
        "prediction": None
        if pred is None
        else {"predicted_vwc": pred.predicted_vwc, "target_at": iso(pred.target_at), "model_version": pred.model_version,
              "baseline_vwc": pred.baseline_vwc},
        "weather_now": weather_now,
        "forecast": {"retrieved_at": iso(retrieved), "status": forecast_status()},
        "settings": {
            "version": st.setting_id,
            "moisture_threshold": st.moisture_threshold,
            "probe_min_vwc": st.probe_min_vwc,
            "max_actuation_sec": st.max_actuation_sec,
            "soak_interval_sec": st.soak_interval_sec,
            "power_setup": st.power_setup,
        },
    }
