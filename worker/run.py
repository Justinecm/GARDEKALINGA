"""Scheduler for the Docker deployment (BUILD_PROMPT C-5). One instance only.

Runs the same idempotent jobs as Vercel Cron, at their exact Asia/Manila times,
plus the training jobs that need scikit-learn (not available on Vercel).
"""
from __future__ import annotations

import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from apscheduler.schedulers.blocking import BlockingScheduler  # noqa: E402

from backend.app import create_app  # noqa: E402
from backend.db import SessionLocal  # noqa: E402
from backend.services.jobs import run_job  # noqa: E402
from backend.timeutil import utcnow  # noqa: E402

log = logging.getLogger("gardekalinga.worker")
logging.getLogger("apscheduler").setLevel(logging.WARNING)
app = create_app()


def job(name: str):
    def _run():
        with app.app_context():
            try:
                msg = run_job(name, utcnow())
                SessionLocal().commit()
                if name not in ("mark_offline", "expire_commands"):
                    log.info("%s: %s", name, msg)
            except Exception:  # pragma: no cover
                SessionLocal().rollback()
                log.exception("job %s failed", name)
            finally:
                SessionLocal.remove()

    return _run


def retrain_if_requested():
    from backend.models import AppState
    from backend.services.jobs import _phase_sync
    from backend.services.ml.train import TrainingUnavailable, train_model

    with app.app_context():
        s = SessionLocal()
        try:
            if s.get(AppState, "retrain_request") is None:
                return
            try:
                m = train_model(utcnow(), notes="manager request")
                log.info("retrained %s active=%s", m.model_version, m.is_active)
            except TrainingUnavailable as e:
                log.info("retrain skipped: %s", e)
            s.delete(s.get(AppState, "retrain_request"))
            _phase_sync(utcnow())
            s.commit()
        finally:
            SessionLocal.remove()


def main() -> None:
    tz = "Asia/Manila"
    sch = BlockingScheduler(timezone=tz)
    sch.add_job(job("mark_offline"), "interval", seconds=5)
    sch.add_job(job("expire_commands"), "interval", seconds=10)
    sch.add_job(job("purge_nonces"), "interval", minutes=10)
    sch.add_job(job("fetch_forecast"), "cron", minute=50)
    sch.add_job(job("fill_actuals"), "cron", minute=40)
    sch.add_job(job("phase_sync"), "cron", minute=5)
    sch.add_job(job("daily_water"), "cron", hour=0, minute=15)
    sch.add_job(job("train_check"), "cron", hour=0, minute=30)
    sch.add_job(job("weekly_retrain"), "cron", day_of_week="sun", hour=1, minute=0)
    sch.add_job(job("fault_watchdog_am"), "cron", hour=6, minute=20)
    sch.add_job(job("fault_watchdog_pm"), "cron", hour=16, minute=20)
    sch.add_job(retrain_if_requested, "interval", minutes=2)
    log.info("worker started")
    sch.start()


if __name__ == "__main__":
    main()
