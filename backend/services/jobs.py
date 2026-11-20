"""Scheduled jobs (BUILD_PROMPT C-5).

The same job functions run from three places:
  * the Docker worker (worker/run.py, APScheduler, exact times),
  * Vercel Cron (GET /api/cron/<job>, see vercel.json),
  * the opportunistic runner: device polls and dashboard status calls run any job
    that is due. On Vercel this keeps the system working even on the Hobby plan,
    whose cron jobs may only run once a day.
Every job is idempotent, so a double run is harmless.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Callable

from flask import current_app
from sqlalchemy import func, select

from ..db import db
from ..models import ActuationEvent, DailyWaterUse, JobRun, SensorLog
from ..timeutil import MANILA, iso, manila_to_utc, to_manila
from . import device_service
from .audit import audit

log = logging.getLogger("gardekalinga.jobs")


def _last_local_boundary(now: datetime, hh: int, mm: int, weekday: int | None = None) -> datetime:
    """Most recent Asia/Manila hh:mm (optionally on a weekday, Mon=0) at or before now, in UTC."""
    local = to_manila(now)
    cand = local.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if weekday is None:
        if cand > local:
            cand -= timedelta(days=1)
    else:
        cand -= timedelta(days=(cand.weekday() - weekday) % 7)
        if cand > local:
            cand -= timedelta(days=7)
    return manila_to_utc(cand.replace(tzinfo=None))


def _hourly_boundary(now: datetime, minute: int) -> datetime:
    b = now.replace(minute=minute, second=0, microsecond=0)
    return b if b <= now else b - timedelta(hours=1)


# ---------------------------------------------------------------- job bodies
def job_expire_commands(now: datetime) -> str:
    return f"expired {device_service.expire_commands(now)}"


def job_mark_offline(now: datetime) -> str:
    return f"marked {device_service.mark_offline(now, current_app.config['GK'].offline_after_s)}"


def job_purge_nonces(now: datetime) -> str:
    from ..device_auth import purge_nonces

    return f"purged {purge_nonces()}"


def job_fetch_forecast(now: datetime) -> str:
    from .weather import refresh_forecast

    st = refresh_forecast(now)
    return "ok" if st.get("ok") else "error: " + str(st.get("last_error"))


def job_fill_actuals(now: datetime) -> str:
    from .ml.inference import fill_actuals

    return f"filled {fill_actuals(now)}"


def compute_daily_water(day_local: str, flow_lpm: float) -> DailyWaterUse:
    """Equation 8: daily water use = flow rate x total pump-on time that day."""
    s = db()
    start_local = datetime.strptime(day_local, "%Y-%m-%d")
    start, end = manila_to_utc(start_local), manila_to_utc(start_local + timedelta(days=1))
    rows = list(
        s.execute(
            select(ActuationEvent.duration_sec).where(ActuationEvent.pump_on_at >= start, ActuationEvent.pump_on_at < end)
        )
    )
    secs = float(sum((d or 0.0) for (d,) in rows))
    litres = round(flow_lpm * secs / 60.0, 3)
    row = s.get(DailyWaterUse, day_local)
    if row is None:
        row = DailyWaterUse(day=day_local, pump_seconds=secs, litres=litres, flow_rate_lpm=flow_lpm, runs=len(rows), computed_at=now_utc())
        s.add(row)
    else:
        row.pump_seconds, row.litres, row.flow_rate_lpm, row.runs, row.computed_at = secs, litres, flow_lpm, len(rows), now_utc()
    return row


def now_utc() -> datetime:
    from ..timeutil import utcnow

    return utcnow()


def job_daily_water(now: datetime) -> str:
    from .settings_service import current_settings, set_system_value

    st = current_settings()
    local_today = to_manila(now).date()
    for back in range(1, 4):  # recompute the last 3 days (late offline syncs)
        compute_daily_water((local_today - timedelta(days=back)).isoformat(), st.flow_rate_lpm)
    db().flush()
    msg = "computed"
    if st.daily_water_mode == "auto":
        # FR-FS-04: 7-day average once 3 days of normal operation exist.
        s = db()
        days = list(s.scalars(select(DailyWaterUse).order_by(DailyWaterUse.day.desc()).limit(7)))
        normal = []
        for d in days:
            start = manila_to_utc(datetime.strptime(d.day, "%Y-%m-%d"))
            good = s.scalar(
                select(func.count()).select_from(SensorLog).where(
                    SensorLog.recorded_at >= start,
                    SensorLog.recorded_at < start + timedelta(days=1),
                    SensorLog.active_probe_count > 0,
                )
            )
            if (good or 0) >= 24:
                normal.append(d.litres)
        if len(normal) >= 3:
            avg = round(sum(normal) / len(normal), 2)
            if avg > 0 and abs(avg - st.daily_water_l) >= 0.05:
                set_system_value(daily_water_l=avg)
                msg += f"; daily_water_l={avg}"
    return msg


def job_train_check(now: datetime) -> str:
    """Daily 00:30: first training at the end of day 14 (FR-ML-07)."""
    from ..models import MLModel
    from .ml.train import TrainingUnavailable, sklearn_available, train_model
    from .settings_service import current_settings

    st = current_settings()
    if st.deployment_started_at is None or now < st.deployment_started_at + timedelta(days=st.cold_start_days):
        return "cold start not finished"
    if db().scalar(select(func.count()).select_from(MLModel)) > 0:
        return "already trained"
    if not sklearn_available():
        return "needs trainer (scikit-learn not installed here)"
    try:
        m = train_model(now, notes="first training at end of cold start")
        _phase_sync(now)
        return f"trained {m.model_version} active={m.is_active}"
    except TrainingUnavailable as e:
        return f"skipped: {e}"


def job_weekly_retrain(now: datetime) -> str:
    from .ml.train import TrainingUnavailable, sklearn_available, train_model

    if not sklearn_available():
        return "needs trainer (scikit-learn not installed here)"
    try:
        m = train_model(now, notes="weekly retrain")
        _phase_sync(now)
        return f"trained {m.model_version} active={m.is_active}"
    except TrainingUnavailable as e:
        return f"skipped: {e}"


def _phase_sync(now: datetime) -> None:
    """Store the operating phase in system_settings when it changes (FR-CTL-08)."""
    from .decision_engine import active_model_exists
    from .settings_service import current_settings, phase_info, set_system_value

    st = current_settings()
    name = phase_info(st, now, active_model_exists())["name"]
    if name != st.operating_phase:
        set_system_value(operating_phase=name)
        audit("phase.change", "system_settings", {"phase": st.operating_phase}, {"phase": name})


def job_phase_sync(now: datetime) -> str:
    _phase_sync(now)
    return "ok"


def job_fault_watchdog(now: datetime) -> str:
    """06:20 / 16:20: alert if the fault-schedule run did not happen while all probes are faulty."""
    from .commands import latest_reading

    last = latest_reading(None)
    if last is None or last.active_probe_count > 0:
        return "probes ok"
    s = db()
    ran = s.scalar(
        select(func.count()).select_from(ActuationEvent).where(
            ActuationEvent.trigger_source == "sensor_fault_schedule",
            ActuationEvent.valve_open_at >= now - timedelta(minutes=35),
        )
    )
    if ran:
        return "schedule ran"
    audit("alert.fault_schedule_missed", "device", None, {"checked_at": iso(now)})
    return "ALERT: fault schedule run missing"


JOBS: dict[str, tuple[Callable[[datetime], str], Callable[[datetime], datetime]]] = {
    "expire_commands": (job_expire_commands, lambda n: n - timedelta(seconds=10)),
    "mark_offline": (job_mark_offline, lambda n: n - timedelta(seconds=5)),
    "purge_nonces": (job_purge_nonces, lambda n: n - timedelta(minutes=10)),
    "fetch_forecast": (job_fetch_forecast, lambda n: _hourly_boundary(n, 50)),
    "fill_actuals": (job_fill_actuals, lambda n: _hourly_boundary(n, 40)),
    "phase_sync": (job_phase_sync, lambda n: _hourly_boundary(n, 5)),
    "daily_water": (job_daily_water, lambda n: _last_local_boundary(n, 0, 15)),
    "train_check": (job_train_check, lambda n: _last_local_boundary(n, 0, 30)),
    "weekly_retrain": (job_weekly_retrain, lambda n: _last_local_boundary(n, 1, 0, weekday=6)),
    "fault_watchdog_am": (job_fault_watchdog, lambda n: _last_local_boundary(n, 6, 20)),
    "fault_watchdog_pm": (job_fault_watchdog, lambda n: _last_local_boundary(n, 16, 20)),
}

# Jobs that are cheap enough to run inline from a request.
OPPORTUNISTIC = ("expire_commands", "mark_offline", "purge_nonces", "fetch_forecast", "fill_actuals", "phase_sync",
                 "daily_water", "fault_watchdog_am", "fault_watchdog_pm", "train_check")


def run_job(name: str, now: datetime) -> str:
    fn, _due = JOBS[name]
    s = db()
    row = s.get(JobRun, name)
    if row is None:
        row = JobRun(job_name=name)
        s.add(row)
    row.last_run_at = now
    try:
        with s.begin_nested():
            msg = fn(now)
        row.last_ok_at, row.last_status, row.last_message = now, "ok", msg[:255]
    except Exception as e:  # keep the request alive; report in job_runs
        log.exception("job %s failed", name)
        row.last_status, row.last_message = "error", f"{type(e).__name__}: {e}"[:255]
        msg = row.last_message
    return msg


def run_due(now: datetime, names: tuple[str, ...] = OPPORTUNISTIC) -> dict[str, str]:
    s = db()
    runs = {r.job_name: r for r in s.scalars(select(JobRun).where(JobRun.job_name.in_(names)))}
    out = {}
    for name in names:
        _fn, boundary = JOBS[name]
        b = boundary(now)
        last = runs.get(name)
        retry_failed = (
            name == "fetch_forecast" and last is not None and last.last_status == "error"
            and last.last_run_at is not None and now - last.last_run_at >= timedelta(minutes=10)
        )
        if retry_failed or last is None or last.last_run_at is None or last.last_run_at < b:
            if name.startswith("fault_watchdog") and (last is None or last.last_run_at is None) and now - b > timedelta(hours=1):
                # First run long after the slot: just record it, no stale alert.
                row = last or JobRun(job_name=name)
                row.last_run_at = now
                s.add(row)
                continue
            out[name] = run_job(name, now)
    return out


__all__ = ["JOBS", "run_due", "run_job", "compute_daily_water", "MANILA"]
