"""Inline inference (FR-ML-08, FR-ML-09) and live accuracy."""
from __future__ import annotations

import math
from datetime import datetime, timedelta

from sqlalchemy import select

from ...db import db
from ...models import MLModel, MLPrediction, SensorLog
from ...timeutil import floor_hour
from . import forest_runtime
from .dataset import live_row

H = timedelta(hours=1)


def active_model() -> MLModel | None:
    return db().scalars(select(MLModel).where(MLModel.is_active.is_(True)).limit(1)).first()


def prediction_for_reading(log: SensorLog, now: datetime) -> MLPrediction | None:
    """Predict the mean VWC of [h, h+1) at the :00 reading; reuse it at :30."""
    model = active_model()
    if model is None or model.artifact is None:
        return None
    h = floor_hour(log.recorded_at)
    s = db()
    existing = s.scalars(
        select(MLPrediction).where(MLPrediction.target_at == h, MLPrediction.model_version == model.model_version).limit(1)
    ).first()
    if existing is not None:
        return existing
    row = live_row(h, log.device_id)
    if row is None:
        return None  # decision engine logs prediction_unavailable
    forest = forest_runtime.load(model.model_version, model.artifact)
    value = forest.predict_one(row.features)
    pred = MLPrediction(
        log_id=log.log_id,
        forecast_id=row.forecast_id,
        predicted_vwc=round(value, 3),
        decision=None,
        model_version=model.model_version,
        created_at=now,
        target_at=h,
        baseline_vwc=row.features["mean_vwc"],
    )
    s.add(pred)
    s.flush()
    return pred


def fill_actuals(now: datetime) -> int:
    """Hourly job: store the observed mean of each finished target hour."""
    s = db()
    pending = list(
        s.scalars(select(MLPrediction).where(MLPrediction.actual_vwc.is_(None), MLPrediction.target_at <= now - H).limit(500))
    )
    n = 0
    for p in pending:
        vals = [
            v
            for (v,) in s.execute(
                select(SensorLog.spatial_mean_vwc).where(
                    SensorLog.recorded_at >= p.target_at,
                    SensorLog.recorded_at < p.target_at + H,  # type: ignore[operator]
                    SensorLog.spatial_mean_vwc.is_not(None),
                )
            )
        ]
        if vals:
            p.actual_vwc = round(sum(vals) / len(vals), 3)
            n += 1
        elif p.target_at and p.target_at < now - 3 * H:
            p.actual_vwc = None  # leave empty: no readings for that hour
    return n


def live_accuracy(model_version: str | None = None, since: datetime | None = None) -> dict:
    s = db()
    q = select(MLPrediction.predicted_vwc, MLPrediction.actual_vwc, MLPrediction.baseline_vwc).where(
        MLPrediction.actual_vwc.is_not(None)
    )
    if model_version:
        q = q.where(MLPrediction.model_version == model_version)
    if since:
        q = q.where(MLPrediction.created_at >= since)
    rows = list(s.execute(q))
    if not rows:
        return {"n": 0, "mae": None, "rmse": None, "baseline_mae": None, "baseline_rmse": None}
    n = len(rows)
    err = [p - a for p, a, _b in rows]
    berr = [(b if b is not None else a) - a for _p, a, b in rows]
    return {
        "n": n,
        "mae": round(sum(abs(e) for e in err) / n, 3),
        "rmse": round(math.sqrt(sum(e * e for e in err) / n), 3),
        "baseline_mae": round(sum(abs(e) for e in berr) / n, 3),
        "baseline_rmse": round(math.sqrt(sum(e * e for e in berr) / n), 3),
    }
