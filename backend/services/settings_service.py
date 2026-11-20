"""Versioned system settings.

system_settings is insert-only: each save adds a row, the newest row is current,
and setting_id is the settings version pushed to the node.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select

from ..db import db
from ..errors import ApiError
from ..models import SystemSettings
from ..timeutil import iso, utcnow

PROBES = ("S1", "S2", "S3")

# STARTING VALUES (BUILD_PROMPT A-9 #5, FR-FS-04, FR-CTL-05). FIXED ones are marked.
DEFAULT_CALIBRATION = {
    # adc_dry / adc_sat start from the original 1-probe sketch (DRY_VALUE 3000, WET_VALUE 1300).
    p: {"adc_dry": 3000, "adc_sat": 1300, "vwc_dry": 5.0, "vwc_sat": 45.0, "calibrated_at": None}
    for p in PROBES
}

DEFAULTS: dict[str, Any] = {
    "moisture_threshold": 30.0,
    "probe_min_vwc": 22.0,
    "max_actuation_sec": 180,
    "soak_interval_sec": 1800,
    "rain_pop_pct": 70.0,
    "rain_mm": 2.0,
    "rain_window_h": 6,
    "cold_start_days": 14,
    "flow_rate_lpm": 1.5,
    "daily_water_mode": "auto",
    "fault_am_time": "06:00",
    "fault_pm_time": "16:00",
    "fault_am_share": 0.6,
    "valve_close_gap_ms": 100,
    "power_setup": "adapter_only",
    # Paradise Heights, Balut, Tondo (approximate). The group enters the exact spot.
    "garden_lat": 14.6266,
    "garden_lon": 120.9690,
}

# Field specs drive both server validation and the Settings form (unit, range, step).
FIELD_SPECS: dict[str, dict[str, Any]] = {
    "moisture_threshold": {"group": "watering", "unit": "% VWC", "min": 5, "max": 60, "step": 0.5, "type": "number"},
    "probe_min_vwc": {"group": "watering", "unit": "% VWC", "min": 5, "max": 60, "step": 0.5, "type": "number"},
    "max_actuation_sec": {"group": "watering", "unit": "s", "min": 10, "max": 600, "step": 5, "type": "integer"},
    "soak_interval_sec": {"group": "watering", "unit": "s", "min": 60, "max": 7200, "step": 60, "type": "integer"},
    "valve_close_gap_ms": {"group": "watering", "unit": "ms", "min": 0, "max": 1000, "step": 10, "type": "integer"},
    "rain_pop_pct": {"group": "rain", "unit": "%", "min": 0, "max": 100, "step": 1, "type": "number"},
    "rain_mm": {"group": "rain", "unit": "mm", "min": 0, "max": 50, "step": 0.1, "type": "number"},
    "rain_window_h": {"group": "rain", "unit": "h", "min": 1, "max": 24, "step": 1, "type": "integer"},
    "cold_start_days": {"group": "phase", "unit": "days", "min": 14, "max": 14, "step": 1, "type": "integer", "fixed": True},
    "deployment_started_at": {"group": "phase", "unit": "", "type": "datetime"},
    "flow_rate_lpm": {"group": "fault", "unit": "L/min", "min": 0.1, "max": 10, "step": 0.01, "type": "number"},
    "daily_water_mode": {"group": "fault", "unit": "", "type": "enum", "options": ["auto", "manual"]},
    "daily_water_l": {"group": "fault", "unit": "L", "min": 0.1, "max": 200, "step": 0.1, "type": "number"},
    "fault_am_time": {"group": "fault", "unit": "", "type": "time"},
    "fault_pm_time": {"group": "fault", "unit": "", "type": "time"},
    "fault_am_share": {"group": "fault", "unit": "", "min": 0.6, "max": 0.6, "step": 0.01, "type": "number", "fixed": True},
    "power_setup": {"group": "power", "unit": "", "type": "enum", "options": ["adapter_only", "hybrid"]},
    "garden_lat": {"group": "location", "unit": "°", "min": -90, "max": 90, "step": 0.0001, "type": "number"},
    "garden_lon": {"group": "location", "unit": "°", "min": -180, "max": 180, "step": 0.0001, "type": "number"},
}

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def default_daily_water_l(max_actuation_sec: int, flow_rate_lpm: float) -> float:
    """FR-FS-04 builder default: 2 x max watering time x flow rate."""
    return round(2 * max_actuation_sec * flow_rate_lpm / 60.0, 2)


def current_settings(create: bool = True) -> SystemSettings:
    s = db()
    row = s.scalars(select(SystemSettings).order_by(SystemSettings.setting_id.desc()).limit(1)).first()
    if row is None and create:
        row = SystemSettings(
            **{k: v for k, v in DEFAULTS.items()},
            operating_phase="cold_start",
            daily_water_l=default_daily_water_l(DEFAULTS["max_actuation_sec"], DEFAULTS["flow_rate_lpm"]),
            calibration_json=DEFAULT_CALIBRATION,
            updated_by=None,
            updated_at=utcnow(),
            deployment_started_at=None,
            change_note="initial starting values",
        )
        s.add(row)
        s.flush()
    return row  # type: ignore[return-value]


def _copy(row: SystemSettings) -> dict[str, Any]:
    cols = [c.key for c in SystemSettings.__table__.columns if c.key not in {"setting_id", "updated_at", "updated_by", "change_note"}]
    return {c: getattr(row, c) for c in cols}


def validate_changes(cur: SystemSettings, changes: dict[str, Any]) -> dict[str, Any]:
    errors: dict[str, str] = {}
    out: dict[str, Any] = {}
    for key, val in changes.items():
        if key == "calibration":
            continue
        spec = FIELD_SPECS.get(key)
        if spec is None:
            errors[key] = "unknown_field"
            continue
        if spec.get("fixed"):
            if val is not None and float(val) != float(getattr(cur, key)):
                errors[key] = "fixed_by_paper"
            continue
        t = spec["type"]
        try:
            if t in ("number", "integer"):
                num = float(val)
                if num < spec["min"] or num > spec["max"]:
                    errors[key] = f"range {spec['min']}–{spec['max']}"
                    continue
                out[key] = int(round(num)) if t == "integer" else round(num, 4)
            elif t == "enum":
                if val not in spec["options"]:
                    errors[key] = "invalid_option"
                    continue
                out[key] = val
            elif t == "time":
                if not isinstance(val, str) or not _TIME_RE.match(val):
                    errors[key] = "use HH:MM"
                    continue
                out[key] = val
            elif t == "datetime":
                from ..timeutil import parse_iso

                out[key] = parse_iso(val) if val else None
        except (TypeError, ValueError):
            errors[key] = "invalid_value"

    threshold = out.get("moisture_threshold", cur.moisture_threshold)
    pmin = out.get("probe_min_vwc", cur.probe_min_vwc)
    if pmin > threshold:
        errors["probe_min_vwc"] = "must be at or below the moisture threshold"

    if "calibration" in changes:
        cal = dict(cur.calibration_json or DEFAULT_CALIBRATION)
        for probe, c in (changes.get("calibration") or {}).items():
            if probe not in PROBES:
                errors[f"calibration.{probe}"] = "unknown_probe"
                continue
            try:
                adc_dry, adc_sat = int(c["adc_dry"]), int(c["adc_sat"])
                vwc_dry, vwc_sat = float(c["vwc_dry"]), float(c["vwc_sat"])
            except (KeyError, TypeError, ValueError):
                errors[f"calibration.{probe}"] = "invalid_value"
                continue
            if not (0 <= adc_sat < adc_dry <= 4095):
                errors[f"calibration.{probe}.adc_dry"] = "ADC dry must be larger than ADC saturated (0–4095)"
                continue
            if not (0 <= vwc_dry < vwc_sat <= 100):
                errors[f"calibration.{probe}.vwc_sat"] = "VWC saturated must be larger than VWC dry (0–100)"
                continue
            prev = cal.get(probe, {})
            changed = (prev.get("adc_dry"), prev.get("adc_sat"), prev.get("vwc_dry"), prev.get("vwc_sat")) != (
                adc_dry,
                adc_sat,
                vwc_dry,
                vwc_sat,
            )
            cal[probe] = {
                "adc_dry": adc_dry,
                "adc_sat": adc_sat,
                "vwc_dry": vwc_dry,
                "vwc_sat": vwc_sat,
                "calibrated_at": iso(utcnow()) if changed else prev.get("calibrated_at"),
            }
        out["calibration_json"] = cal

    if errors:
        raise ApiError(422, "validation_error", "Some settings are outside their allowed range.", errors)
    return out


def save_new_version(changes: dict[str, Any], user_id: int | None, note: str | None = None) -> SystemSettings:
    s = db()
    cur = current_settings()
    clean = validate_changes(cur, changes) if changes else {}
    data = _copy(cur)
    data.update(clean)
    if data.get("daily_water_mode") == "auto" and "daily_water_l" not in clean:
        pass  # keep the rolling value computed by the nightly job
    row = SystemSettings(**data, updated_by=user_id, updated_at=utcnow(), change_note=note)
    s.add(row)
    s.flush()
    return row


def set_system_value(**values: Any) -> SystemSettings:
    """Internal updates (phase change, rolling daily water) without range checks."""
    s = db()
    cur = current_settings()
    data = _copy(cur)
    data.update(values)
    row = SystemSettings(**data, updated_by=None, updated_at=utcnow(), change_note="system: " + ", ".join(values))
    s.add(row)
    s.flush()
    return row


def phase_info(st: SystemSettings, now: datetime, model_active: bool) -> dict[str, Any]:
    if st.deployment_started_at is None:
        return {"name": "cold_start", "day": 0, "of": st.cold_start_days, "started_at": None, "model_active": model_active, "ends_at": None}
    ends = st.deployment_started_at + timedelta(days=st.cold_start_days)
    elapsed_days = int((now - st.deployment_started_at).total_seconds() // 86400) + 1
    predictive = now >= ends and model_active
    return {
        "name": "predictive" if predictive else "cold_start",
        "day": max(1, min(elapsed_days, st.cold_start_days)) if not predictive else elapsed_days,
        "of": st.cold_start_days,
        "started_at": iso(st.deployment_started_at),
        "ends_at": iso(ends),
        "cold_start_complete": now >= ends,
        "model_active": model_active,
    }


def to_public(st: SystemSettings) -> dict[str, Any]:
    d = _copy(st)
    d["version"] = st.setting_id
    d["updated_at"] = iso(st.updated_at)
    d["updated_by"] = st.updated_by
    d["deployment_started_at"] = iso(st.deployment_started_at)
    d["calibration"] = d.pop("calibration_json")
    d["change_note"] = st.change_note
    return d


def to_device(st: SystemSettings) -> dict[str, Any]:
    """Compact settings object sent to the node when its version is behind."""
    cal = st.calibration_json or DEFAULT_CALIBRATION
    return {
        "v": st.setting_id,
        "thr": st.moisture_threshold,
        "pmin": st.probe_min_vwc,
        "max": st.max_actuation_sec,
        "soak": st.soak_interval_sec,
        "gap": st.valve_close_gap_ms,
        "flow": st.flow_rate_lpm,
        "daily_l": st.daily_water_l,
        "am": st.fault_am_time,
        "pm": st.fault_pm_time,
        "am_share": st.fault_am_share,
        "cal": {p: [cal[p]["adc_dry"], cal[p]["adc_sat"], cal[p]["vwc_dry"], cal[p]["vwc_sat"]] for p in PROBES if p in cal},
    }
