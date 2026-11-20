"""Reports (manager, leader): CSV exports, daily water use, audit trail, test bench."""
from __future__ import annotations

import csv
import io
from datetime import timedelta
from typing import Any, Iterable

from flask import Blueprint, Response, g, jsonify, request
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from ..db import db
from ..errors import ApiError
from ..models import (
    ActuationEvent,
    AuditLog,
    ControlDecision,
    DailyWaterUse,
    MLPrediction,
    PowerStateTransition,
    SensorLog,
    TestRecord,
    User,
)
from ..security import roles_required
from ..services.audit import audit
from ..services.jobs import compute_daily_water
from ..services.settings_service import current_settings
from ..timeutil import iso, manila_day, to_manila, utcnow
from ._common import int_arg, time_range

bp = Blueprint("reports", __name__, url_prefix="/api/v1")


def _csv(name: str, header: list[str], rows: Iterable[list[Any]]) -> Response:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    for r in rows:
        w.writerow(["" if v is None else v for v in r])
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="gardekalinga-{name}.csv"'})


def _local(dt) -> str | None:
    return to_manila(dt).strftime("%Y-%m-%d %H:%M:%S") if dt else None


def _names() -> dict:
    return {u.user_id: u.full_name for u in db().scalars(select(User))}


@bp.get("/reports/<name>.csv")
@roles_required("manager", "leader")
def report_csv(name: str):
    frm, to = time_range(24 * 30, max_days=800)
    s = db()
    if name == "irrigation":
        names = _names()
        rows = s.scalars(select(ActuationEvent).where(ActuationEvent.valve_open_at >= frm, ActuationEvent.valve_open_at <= to)
                         .order_by(ActuationEvent.valve_open_at))
        return _csv(name, ["event_id", "trigger_source", "user", "valve_open_at_manila", "pump_on_at", "pump_off_at", "valve_closed_at",
                           "duration_s", "interlock_ms", "close_gap_ms", "ended_reason", "command_id", "decision_id"],
                    ([e.event_id, e.trigger_source, names.get(e.user_id), _local(e.valve_open_at), _local(e.pump_on_at),
                      _local(e.pump_off_at), _local(e.valve_closed_at), e.duration_sec, e.interlock_ms, e.close_gap_ms,
                      e.ended_reason, e.command_id, e.decision_id] for e in rows))
    if name == "power":
        rows = s.scalars(select(PowerStateTransition).where(PowerStateTransition.occurred_at >= frm,
                                                            PowerStateTransition.occurred_at <= to).order_by(PowerStateTransition.occurred_at))
        return _csv(name, ["transition_id", "occurred_at_manila", "from_source", "to_source", "supply_voltage"],
                    ([r.transition_id, _local(r.occurred_at), r.from_source, r.to_source, r.battery_voltage] for r in rows))
    if name == "water-use":
        rows = s.scalars(select(DailyWaterUse).order_by(DailyWaterUse.day))
        return _csv(name, ["day", "runs", "pump_seconds", "flow_rate_lpm", "litres"],
                    ([d.day, d.runs, round(d.pump_seconds, 1), d.flow_rate_lpm, d.litres] for d in rows))
    if name == "prediction-accuracy":
        rows = s.scalars(select(MLPrediction).where(MLPrediction.target_at >= frm, MLPrediction.target_at <= to)
                         .order_by(MLPrediction.target_at))
        return _csv(name, ["prediction_id", "target_hour_manila", "model_version", "predicted_vwc", "actual_vwc", "baseline_vwc",
                           "abs_error", "baseline_abs_error", "decision"],
                    ([p.prediction_id, _local(p.target_at), p.model_version, p.predicted_vwc, p.actual_vwc, p.baseline_vwc,
                      round(abs(p.predicted_vwc - p.actual_vwc), 3) if p.actual_vwc is not None else None,
                      round(abs((p.baseline_vwc or 0) - p.actual_vwc), 3) if p.actual_vwc is not None and p.baseline_vwc is not None else None,
                      p.decision] for p in rows))
    if name == "decisions":
        rows = s.scalars(select(ControlDecision).where(ControlDecision.created_at >= frm, ControlDecision.created_at <= to)
                         .order_by(ControlDecision.created_at))
        def rule(d):
            r = (d.inputs_json or {}).get("rain") or {}
            return r
        return _csv(name, ["decision_id", "at_manila", "action", "reason", "phase", "duration_s", "mean_vwc", "predicted_vwc",
                           "threshold", "rain_pop_max", "rain_mm_6h", "rain_stale", "rule_pop_pct", "rule_rain_mm", "settings_version"],
                    ([d.decision_id, _local(d.created_at), d.action, d.reason_code, d.phase, d.duration_sec,
                      (d.inputs_json or {}).get("mean_vwc"), (d.inputs_json or {}).get("predicted_vwc"), (d.inputs_json or {}).get("threshold"),
                      rule(d).get("pop_max"), rule(d).get("rain_mm"), rule(d).get("stale"), (rule(d).get("rule") or {}).get("pop_pct"),
                      (rule(d).get("rule") or {}).get("rain_mm"), d.settings_version] for d in rows))
    if name == "ingestion":
        counts: dict = {}
        for at, src in s.execute(select(SensorLog.recorded_at, SensorLog.power_source).where(SensorLog.recorded_at >= frm,
                                                                                            SensorLog.recorded_at <= to)):
            key = (manila_day(at), src or "unknown")
            counts[key] = counts.get(key, 0) + 1
        return _csv(name, ["day", "power_source", "readings_stored", "expected_if_whole_day", "meets_46_of_48"],
                    ([d, src, n, 48, "yes" if n >= 46 else "no"] for (d, src), n in sorted(counts.items())))
    if name == "readings":
        rows = s.scalars(select(SensorLog).where(SensorLog.recorded_at >= frm, SensorLog.recorded_at <= to).order_by(SensorLog.recorded_at))
        return _csv(name, ["log_id", "recorded_at_manila", "spatial_mean_vwc", "active_probe_count", "S1_vwc", "S2_vwc", "S3_vwc",
                           "S1_raw", "S2_raw", "S3_raw", "S1_fault", "S2_fault", "S3_fault", "supply_v", "power_source",
                           "control_mode", "synced_offline"],
                    ([r.log_id, _local(r.recorded_at), r.spatial_mean_vwc, r.active_probe_count,
                      *[(r.probe_vwc_json or {}).get(p) for p in ("S1", "S2", "S3")],
                      *[(r.raw_adc_values or {}).get(p) for p in ("S1", "S2", "S3")],
                      *[(r.probe_fault_json or {}).get(p) for p in ("S1", "S2", "S3")],
                      r.supply_voltage, r.power_source, r.control_mode, r.synced_offline] for r in rows))
    if name == "audit":
        names = _names()
        rows = s.scalars(select(AuditLog).where(AuditLog.at >= frm, AuditLog.at <= to).order_by(AuditLog.at))
        return _csv(name, ["audit_id", "at_manila", "user", "action", "target", "before", "after", "ip"],
                    ([a.audit_id, _local(a.at), names.get(a.user_id), a.action, a.target, a.before_json, a.after_json, a.ip] for a in rows))
    raise ApiError(404, "unknown_report", "Unknown report.")


@bp.get("/reports/water-use")
@roles_required("manager", "leader", "caretaker")
def water_use():
    """Daily water use (Equation 8). Today and yesterday are computed live."""
    st = current_settings()
    now = utcnow()
    today = to_manila(now).date()
    compute_daily_water(today.isoformat(), st.flow_rate_lpm)
    compute_daily_water((today - timedelta(days=1)).isoformat(), st.flow_rate_lpm)
    days = int_arg("days", 30, 1, 400)
    rows = list(db().scalars(select(DailyWaterUse).where(DailyWaterUse.day >= (today - timedelta(days=days)).isoformat())
                             .order_by(DailyWaterUse.day)))
    return jsonify({"items": [{"day": d.day, "litres": d.litres, "pump_seconds": d.pump_seconds, "runs": d.runs,
                               "flow_rate_lpm": d.flow_rate_lpm} for d in rows],
                    "daily_water_l": st.daily_water_l, "daily_water_mode": st.daily_water_mode, "flow_rate_lpm": st.flow_rate_lpm})


@bp.get("/audit")
@roles_required("manager", "leader")
def audit_list():
    frm, to = time_range(24 * 7)
    names = _names()
    q = select(AuditLog).where(AuditLog.at >= frm, AuditLog.at <= to)
    if request.args.get("action"):
        q = q.where(AuditLog.action.like(request.args["action"] + "%"))
    rows = list(db().scalars(q.order_by(AuditLog.at.desc()).limit(int_arg("limit", 300, 1, 2000))))
    return jsonify({"items": [{"id": a.audit_id, "at": iso(a.at), "user": names.get(a.user_id), "action": a.action,
                               "target": a.target, "before": a.before_json, "after": a.after_json} for a in rows]})


# ----------------------------------------------------------------- test bench (FR-UI-12)
class TestRecordIn(BaseModel):
    __test__ = False
    tc_number: int = Field(ge=1, le=15)
    trial_no: int | None = Field(default=None, ge=1, le=1000)
    inputs: dict[str, Any]


def compute_result(tc: int, x: dict[str, Any]) -> dict[str, Any]:
    try:
        if tc == 1:  # Eq. 5 per pair: |sensor - reference|
            diff = abs(float(x["sensor_vwc"]) - float(x["reference_vwc"]))
            return {"abs_diff": round(diff, 3)}
        if tc == 2:
            diff = abs(float(x["long_cable_vwc"]) - float(x["short_lead_vwc"]))
            return {"abs_diff": round(diff, 3)}
        if tc == 12:  # Eq. 6 switching latency
            lat = float(x.get("latency_ms") or 0)
            if x.get("switch_at_ms") is not None and x.get("cross_at_ms") is not None:
                lat = float(x["switch_at_ms"]) - float(x["cross_at_ms"])
            err = abs(float(x["switched_at_v"]) - float(x["expected_v"]))
            return {"latency_ms": round(lat, 1), "voltage_error_v": round(err, 3), "within_0_1v": err <= 0.1}
        if tc == 14:  # Eq. 7 flow rate = volume / time
            q = float(x["volume_l"]) / (float(x["time_s"]) / 60.0)
            return {"flow_lpm": round(q, 3)}
    except (KeyError, TypeError, ValueError, ZeroDivisionError) as e:
        raise ApiError(422, "validation_error", "Missing or invalid measurement.", {"inputs": str(e)}) from e
    return {}


def summarise(tc: int, rows: list[TestRecord]) -> dict[str, Any]:
    if tc in (1, 2):
        groups: dict = {}
        for r in rows:
            key = (r.inputs_json.get("sensor", "all"), r.inputs_json.get("state", "all"))
            groups.setdefault(key, []).append(r.result_json.get("abs_diff", 0.0))
        limit = 5.0 if tc == 1 else 2.0
        out = []
        for (sensor, state), diffs in sorted(groups.items()):
            mad = sum(diffs) / len(diffs)
            out.append({"sensor": sensor, "state": state, "pairs": len(diffs), "mean_abs_diff": round(mad, 3),
                        "limit": limit, "pass": mad <= limit and len(diffs) >= 10, "enough_pairs": len(diffs) >= 10})
        return {"groups": out}
    if tc == 12:
        lat = [r.result_json.get("latency_ms", 0) for r in rows]
        ok = [r.result_json.get("within_0_1v") for r in rows]
        return {"trials": len(rows), "mean_latency_ms": round(sum(lat) / len(lat), 1) if lat else None, "all_within_0_1v": all(ok) if ok else None}
    if tc == 14:
        q = [r.result_json.get("flow_lpm") for r in rows if r.result_json.get("flow_lpm")]
        if not q:
            return {"trials": 0}
        mean = sum(q) / len(q)
        spread = (max(q) - min(q)) / mean if mean else 0
        return {"trials": len(q), "mean_flow_lpm": round(mean, 3), "spread_pct": round(spread * 100, 2),
                "within_10pct": spread <= 0.10, "enough_trials": len(q) >= 5}
    return {"trials": len(rows)}


@bp.get("/test-records")
@roles_required("manager", "leader")
def list_test_records():
    tc = request.args.get("tc", type=int)
    q = select(TestRecord).order_by(TestRecord.tc_number, TestRecord.trial_no)
    if tc:
        q = q.where(TestRecord.tc_number == tc)
    rows = list(db().scalars(q))
    by_tc: dict = {}
    for r in rows:
        by_tc.setdefault(r.tc_number, []).append(r)
    return jsonify({
        "items": [{"id": r.record_id, "tc": r.tc_number, "trial": r.trial_no, "inputs": r.inputs_json, "result": r.result_json,
                   "recorded_at": iso(r.recorded_at)} for r in rows],
        "summary": {str(k): summarise(k, v) for k, v in by_tc.items()},
    })


@bp.post("/test-records")
@roles_required("manager")
def add_test_record():
    body = TestRecordIn.model_validate(request.get_json(silent=True) or {})
    result = compute_result(body.tc_number, body.inputs)
    trial = body.trial_no or (db().scalar(select(func.max(TestRecord.trial_no)).where(TestRecord.tc_number == body.tc_number)) or 0) + 1
    r = TestRecord(tc_number=body.tc_number, trial_no=trial, inputs_json=body.inputs, result_json=result,
                   recorded_by=g.user.user_id, recorded_at=utcnow())
    db().add(r)
    db().flush()
    audit("testbench.add", f"tc:{body.tc_number}", None, {"trial": trial, **result})
    return jsonify({"record": {"id": r.record_id, "tc": r.tc_number, "trial": r.trial_no, "inputs": r.inputs_json, "result": result}}), 201


@bp.get("/test-records/<int:tc>.csv")
@roles_required("manager", "leader")
def test_records_csv(tc: int):
    rows = list(db().scalars(select(TestRecord).where(TestRecord.tc_number == tc).order_by(TestRecord.trial_no)))
    keys = sorted({k for r in rows for k in r.inputs_json})
    rkeys = sorted({k for r in rows for k in r.result_json})
    return _csv(f"tc{tc}", ["trial", *keys, *rkeys, "recorded_at_manila"],
                ([r.trial_no, *[r.inputs_json.get(k) for k in keys], *[r.result_json.get(k) for k in rkeys], _local(r.recorded_at)]
                 for r in rows))
