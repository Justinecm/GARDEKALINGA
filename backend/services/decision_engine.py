"""Decision engine (BUILD_PROMPT C-4, FR-CTL-01..08).

Four-tier priority, highest first:
  1. bounded maximum watering time (enforced on the node; the backend clamps every duration)
  2. authenticated manual override (bypasses this module entirely)
  3. online predictive control (this module): cold-start threshold, then Random Forest, with rain pause
  4. offline edge fail-safe (firmware)

`decide()` is a pure function so every branch has a table-driven test.
`run_for_reading()` gathers the inputs from the database and logs the decision.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select

from ..db import db
from ..models import ActuationEvent, ControlDecision, Device, MLPrediction, SensorLog, SystemSettings
from ..timeutil import iso
from . import rain_pause as rp
from .settings_service import phase_info


@dataclass
class DecisionInputs:
    now: datetime
    mean_vwc: float | None
    active_probes: dict[str, float]
    watering_in_progress: bool
    last_watering_end: datetime | None
    phase: str
    predicted_vwc: float | None
    threshold: float
    probe_min: float
    soak_sec: int
    max_sec: int
    rain_active: bool = False
    rain_stale: bool = False


@dataclass
class Decision:
    action: str  # "water" | "none"
    reason: str
    duration_s: int | None = None
    details: dict[str, Any] = field(default_factory=dict)


def decide(i: DecisionInputs) -> Decision:
    if i.watering_in_progress:
        return Decision("none", "already_watering")
    if len(i.active_probes) == 0 or i.mean_vwc is None:
        # All probes faulty: the node runs the 06:00 / 16:00 schedule itself (FR-FS-03).
        return Decision("none", "sensor_fault_schedule")
    if i.last_watering_end is not None:
        soak_end = i.last_watering_end + timedelta(seconds=i.soak_sec)
        if i.now < soak_end:
            return Decision("none", "soak", details={"soak_ends_at": iso(soak_end), "remaining_s": int((soak_end - i.now).total_seconds())})

    dry = sorted(p for p, v in i.active_probes.items() if v < i.probe_min)
    if i.phase == "cold_start":
        need, reason = i.mean_vwc < i.threshold, "cold_start_threshold"
    elif i.predicted_vwc is None:
        need, reason = i.mean_vwc < i.threshold, "prediction_unavailable"
    else:
        need, reason = i.predicted_vwc < i.threshold, "predicted_below_threshold"
    if dry and not need:
        need, reason = True, "probe_below_min"

    details: dict[str, Any] = {"dry_probes": dry}
    if need:
        if i.rain_stale:
            details["need_reason"] = reason
            details["rain_pause"] = "not_applied_forecast_stale"
            return Decision("water", "forecast_stale", i.max_sec, details)
        if i.rain_active:
            details["need_reason"] = reason
            return Decision("none", "rain_pause", None, details)
        return Decision("water", reason, i.max_sec, details)
    if reason == "prediction_unavailable":
        return Decision("none", "prediction_unavailable", None, details)
    return Decision("none", "moist_enough", None, details)


# ---------------------------------------------------------------------------- DB glue
def device_is_watering(device: Device | None) -> bool:
    st = (device.last_state_json or {}) if device else {}
    return bool(st.get("p") or st.get("v"))


def last_watering_end(device_id: str | None) -> datetime | None:
    s = db()
    q = select(func.max(func.coalesce(ActuationEvent.valve_closed_at, ActuationEvent.pump_off_at)))
    if device_id:
        q = q.where(ActuationEvent.device_id == device_id)
    return s.scalar(q)


def active_model_exists() -> bool:
    from ..models import MLModel

    return db().scalar(select(func.count()).select_from(MLModel).where(MLModel.is_active.is_(True))) > 0


def run_for_reading(log: SensorLog, st: SystemSettings, device: Device | None, now: datetime) -> tuple[ControlDecision, Decision]:
    """Decide for one live reading and write control_decisions (FR-CTL-07)."""
    s = db()
    model_active = active_model_exists()
    phase = phase_info(st, now, model_active)["name"]

    prediction: MLPrediction | None = None
    if phase == "predictive":
        from .ml import inference

        prediction = inference.prediction_for_reading(log, now)

    rain = rp.rain_pause(now, st.rain_pop_pct, st.rain_mm, st.rain_window_h)
    vwc = log.probe_vwc_json or {}
    faults = log.probe_fault_json or {}
    active = {p: float(v) for p, v in vwc.items() if v is not None and not faults.get(p)}
    inputs = DecisionInputs(
        now=now,
        mean_vwc=log.spatial_mean_vwc,
        active_probes=active,
        watering_in_progress=device_is_watering(device),
        last_watering_end=last_watering_end(log.device_id),
        phase=phase,
        predicted_vwc=prediction.predicted_vwc if prediction else None,
        threshold=st.moisture_threshold,
        probe_min=st.probe_min_vwc,
        soak_sec=st.soak_interval_sec,
        max_sec=st.max_actuation_sec,
        rain_active=rain.active,
        rain_stale=rain.stale,
    )
    d = decide(inputs)
    # Tier 1 clamp: the backend never issues more than max_actuation_sec.
    if d.duration_s is not None:
        d.duration_s = min(d.duration_s, st.max_actuation_sec)

    row = ControlDecision(
        log_id=log.log_id,
        action=d.action,
        reason_code=d.reason,
        phase=phase,
        inputs_json={
            "mean_vwc": inputs.mean_vwc,
            "active_probes": active,
            "threshold": inputs.threshold,
            "probe_min": inputs.probe_min,
            "predicted_vwc": inputs.predicted_vwc,
            "model_version": prediction.model_version if prediction else None,
            "watering_in_progress": inputs.watering_in_progress,
            "last_watering_end": iso(inputs.last_watering_end),
            "soak_sec": inputs.soak_sec,
            "rain": {
                "active": rain.active,
                "stale": rain.stale,
                "pop_max": rain.pop_max,
                "rain_mm": rain.rain_mm,
                "rule": {"pop_pct": st.rain_pop_pct, "rain_mm": st.rain_mm, "window_h": st.rain_window_h},
                "retrieved_at": rain.retrieved_at,
                "steps": rain.steps,
            },
            **d.details,
        },
        settings_version=st.setting_id,
        duration_sec=d.duration_s,
        created_at=now,
    )
    s.add(row)
    s.flush()
    if prediction is not None:
        prediction.decision = d.action
    return row, d


def decision_to_device(row: ControlDecision) -> dict[str, Any]:
    return {"id": row.decision_id, "action": row.action, "duration_s": row.duration_sec or 0, "reason": row.reason_code}
