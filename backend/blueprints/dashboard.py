"""Read-only dashboard data: status, readings, forecast, predictions, logs."""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from flask import Blueprint, current_app, g, jsonify, request
from sqlalchemy import func, select

from ..db import db
from ..models import (
    ActuationEvent,
    ControlDecision,
    DeviceEvent,
    DeviceStatusPeriod,
    MLPrediction,
    PowerStateTransition,
    SensorLog,
    User,
    WeatherForecast,
)
from ..security import login_required
from ..services import jobs, rain_pause
from ..services.settings_service import PROBES, current_settings
from ..services.status import build_status
from ..timeutil import floor_hour, iso, manila_day, utcnow
from ._common import int_arg, time_range

bp = Blueprint("dashboard", __name__, url_prefix="/api/v1")


def _housekeeping(now):
    cfg = current_app.config["GK"]
    if cfg.demo_mode:
        from ..services import demo

        demo.tick(now)
    jobs.run_due(now)


@bp.get("/status")
@login_required
def status():
    now = utcnow()
    _housekeeping(now)
    db().flush()
    return jsonify(build_status(now, g.user.role))


@bp.get("/readings")
@login_required
def readings():
    frm, to = time_range(24)
    bucket = request.args.get("bucket", "auto")
    span = to - frm
    if bucket == "auto":
        bucket = "raw" if span <= timedelta(days=3) else ("hour" if span <= timedelta(days=14) else "day")
    s = db()
    rows = list(
        s.scalars(select(SensorLog).where(SensorLog.recorded_at >= frm, SensorLog.recorded_at <= to).order_by(SensorLog.recorded_at))
    )
    points = []
    if bucket == "raw":
        for r in rows:
            vwc = r.probe_vwc_json or {}
            points.append({"t": iso(r.recorded_at), "mean": r.spatial_mean_vwc, **{p: vwc.get(p) for p in PROBES},
                           "supply_v": r.supply_voltage, "source": r.power_source, "synced": r.synced_offline,
                           "active": r.active_probe_count, "mode": r.control_mode,
                           "raw": r.raw_adc_values, "faults": r.probe_fault_json})
    else:
        groups: dict = defaultdict(list)
        for r in rows:
            key = floor_hour(r.recorded_at) if bucket == "hour" else manila_day(r.recorded_at)
            groups[key].append(r)
        for key, grp in groups.items():
            def avg(vals):
                vals = [v for v in vals if v is not None]
                return round(sum(vals) / len(vals), 2) if vals else None

            t = iso(key) if bucket == "hour" else key + "T00:00:00+08:00"
            points.append({"t": t, "mean": avg([r.spatial_mean_vwc for r in grp]),
                           **{p: avg([(r.probe_vwc_json or {}).get(p) for r in grp]) for p in PROBES},
                           "supply_v": avg([r.supply_voltage for r in grp]), "n": len(grp)})
    events = list(
        s.scalars(select(ActuationEvent).where(ActuationEvent.valve_open_at >= frm, ActuationEvent.valve_open_at <= to)
                  .order_by(ActuationEvent.valve_open_at))
    )
    st = current_settings()
    return jsonify({
        "from": iso(frm), "to": iso(to), "bucket": bucket, "points": points,
        "watering": [_event_public(e) for e in events],
        "threshold": st.moisture_threshold, "probe_min": st.probe_min_vwc,
    })


def _event_public(e: ActuationEvent, users: dict | None = None) -> dict:
    return {
        "id": e.event_id, "source": e.trigger_source, "user_id": e.user_id,
        "user": (users or {}).get(e.user_id) if e.user_id else None,
        "valve_open_at": iso(e.valve_open_at), "pump_on_at": iso(e.pump_on_at), "pump_off_at": iso(e.pump_off_at),
        "valve_closed_at": iso(e.valve_closed_at), "duration_s": e.duration_sec, "interlock_ms": e.interlock_ms,
        "close_gap_ms": e.close_gap_ms, "ended_reason": e.ended_reason, "command_id": e.command_id,
        "decision_id": e.decision_id, "prediction_id": e.prediction_id,
    }


@bp.get("/forecast")
@login_required
def forecast():
    now = utcnow()
    st = current_settings()
    retrieved, batch = rain_pause.latest_batch(now)
    rp = rain_pause.rain_pause(now, st.rain_pop_pct, st.rain_mm, st.rain_window_h)
    hours = int_arg("hours", 24, 3, 120)
    steps = [b for b in batch if now - timedelta(hours=3) <= b.forecast_for <= now + timedelta(hours=hours)]
    from ..services.weather import forecast_status

    return jsonify({
        "retrieved_at": iso(retrieved),
        "stale": rp.stale,
        "status": forecast_status(),
        "rain_pause": rp.as_dict() | {"rule": {"pop_pct": st.rain_pop_pct, "rain_mm": st.rain_mm, "window_h": st.rain_window_h}},
        "steps": [{"id": b.forecast_id, "for": iso(b.forecast_for), "condition": b.weather_condition, "temperature_c": b.temperature_c,
                   "humidity_pct": b.humidity_pct, "pop_pct": b.pop_pct, "rain_3h_mm": b.rain_3h_mm} for b in steps],
    })


@bp.get("/forecast/history")
@login_required
def forecast_history():
    frm, to = time_range(24 * 7)
    s = db()
    rows = list(s.scalars(select(WeatherForecast).where(WeatherForecast.retrieved_at >= frm, WeatherForecast.retrieved_at <= to)
                          .order_by(WeatherForecast.retrieved_at.desc(), WeatherForecast.forecast_for).limit(2000)))
    return jsonify({"items": [{"id": r.forecast_id, "retrieved_at": iso(r.retrieved_at), "for": iso(r.forecast_for),
                               "condition": r.weather_condition, "temperature_c": r.temperature_c, "humidity_pct": r.humidity_pct,
                               "pop_pct": r.pop_pct, "rain_3h_mm": r.rain_3h_mm} for r in rows]})


@bp.get("/predictions")
@login_required
def predictions():
    frm, to = time_range(48)
    rows = list(db().scalars(select(MLPrediction).where(MLPrediction.target_at >= frm, MLPrediction.target_at <= to)
                             .order_by(MLPrediction.target_at)))
    return jsonify({"items": [{"id": p.prediction_id, "target_at": iso(p.target_at), "predicted_vwc": p.predicted_vwc,
                               "actual_vwc": p.actual_vwc, "baseline_vwc": p.baseline_vwc, "decision": p.decision,
                               "model_version": p.model_version, "created_at": iso(p.created_at)} for p in rows],
                    "threshold": current_settings().moisture_threshold})


def _user_names() -> dict:
    return {u.user_id: u.full_name for u in db().scalars(select(User))}


@bp.get("/events/watering")
@login_required
def watering_events():
    frm, to = time_range(24 * 7)
    q = select(ActuationEvent).where(ActuationEvent.valve_open_at >= frm, ActuationEvent.valve_open_at <= to)
    if request.args.get("source"):
        q = q.where(ActuationEvent.trigger_source == request.args["source"])
    rows = list(db().scalars(q.order_by(ActuationEvent.valve_open_at.desc()).limit(int_arg("limit", 500, 1, 5000))))
    names = _user_names()
    return jsonify({"items": [_event_public(e, names) for e in rows]})


@bp.get("/events/power")
@login_required
def power_events():
    frm, to = time_range(24 * 7)
    rows = list(db().scalars(select(PowerStateTransition).where(PowerStateTransition.occurred_at >= frm,
                                                                PowerStateTransition.occurred_at <= to)
                             .order_by(PowerStateTransition.occurred_at.desc())))
    boots = list(db().scalars(select(DeviceEvent).where(DeviceEvent.occurred_at >= frm, DeviceEvent.occurred_at <= to,
                                                        DeviceEvent.type == "boot").order_by(DeviceEvent.occurred_at.desc())))
    return jsonify({
        "items": [{"id": r.transition_id, "at": iso(r.occurred_at), "from": r.from_source, "to": r.to_source, "v": r.battery_voltage}
                  for r in rows],
        "boots": [{"at": iso(b.occurred_at), "reset_reason": (b.payload_json or {}).get("reset_reason"),
                   "fw": (b.payload_json or {}).get("fw")} for b in boots],
    })


@bp.get("/decisions")
@login_required
def decisions():
    frm, to = time_range(24 * 2)
    q = select(ControlDecision).where(ControlDecision.created_at >= frm, ControlDecision.created_at <= to)
    if request.args.get("reason"):
        q = q.where(ControlDecision.reason_code == request.args["reason"])
    if request.args.get("action"):
        q = q.where(ControlDecision.action == request.args["action"])
    rows = list(db().scalars(q.order_by(ControlDecision.created_at.desc()).limit(int_arg("limit", 500, 1, 5000))))
    return jsonify({"items": [{"id": d.decision_id, "at": iso(d.created_at), "action": d.action, "reason": d.reason_code,
                               "phase": d.phase, "duration_s": d.duration_sec, "settings_version": d.settings_version,
                               "inputs": d.inputs_json} for d in rows]})


@bp.get("/device/periods")
@login_required
def device_periods():
    frm, to = time_range(24 * 7)
    rows = list(db().scalars(select(DeviceStatusPeriod).where((DeviceStatusPeriod.ended_at.is_(None)) |
                                                              (DeviceStatusPeriod.ended_at >= frm),
                                                              DeviceStatusPeriod.started_at <= to)
                             .order_by(DeviceStatusPeriod.started_at.desc())))
    now = utcnow()
    return jsonify({"items": [{"id": p.period_id, "status": p.status, "started_at": iso(p.started_at), "ended_at": iso(p.ended_at),
                               "duration_s": int(((p.ended_at or now) - p.started_at).total_seconds())} for p in rows]})


@bp.get("/stats/ingestion")
@login_required
def ingestion_stats():
    """TC4 evidence: readings stored per 24 h per power source, and command latency."""
    from ..models import DeviceCommand

    frm, to = time_range(24 * 7)
    s = db()
    rows = s.execute(select(SensorLog.recorded_at, SensorLog.power_source, SensorLog.synced_offline)
                     .where(SensorLog.recorded_at >= frm, SensorLog.recorded_at <= to))
    per_day: dict = defaultdict(lambda: defaultdict(int))
    for at, src, _synced in rows:
        per_day[manila_day(at)][src or "unknown"] += 1
    cmds = list(s.scalars(select(DeviceCommand).where(DeviceCommand.created_at >= frm, DeviceCommand.created_at <= to)
                          .order_by(DeviceCommand.created_at.desc()).limit(500)))
    lat = [(c.acked_at - c.created_at).total_seconds() for c in cmds if c.acked_at]
    return jsonify({
        "days": [{"day": d, "by_source": dict(v), "total": sum(v.values()), "expected": 48} for d, v in sorted(per_day.items())],
        "commands": [{"id": c.command_id, "op": c.op, "status": c.status, "created_at": iso(c.created_at),
                      "acked_at": iso(c.acked_at),
                      "latency_s": round((c.acked_at - c.created_at).total_seconds(), 2) if c.acked_at else None} for c in cmds],
        "latency": {"n": len(lat), "max_s": round(max(lat), 2) if lat else None,
                    "within_6s": sum(1 for v in lat if v <= 6), "mean_s": round(sum(lat) / len(lat), 2) if lat else None},
        "total_readings": s.scalar(select(func.count()).select_from(SensorLog)),
    })
