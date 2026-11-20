"""Model card, retraining and activation (FR-ML-05..07, FR-UI-10)."""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, jsonify
from sqlalchemy import select

from ..db import db
from ..errors import ApiError
from ..models import AppState, MLModel
from ..security import login_required, roles_required
from ..services.audit import audit
from ..services.decision_engine import active_model_exists
from ..services.ml.inference import live_accuracy
from ..services.ml.train import TrainingUnavailable, activate, sklearn_available, train_model
from ..services.settings_service import current_settings, phase_info
from ..timeutil import iso, utcnow

bp = Blueprint("model", __name__, url_prefix="/api/v1")


def model_public(m: MLModel, with_held_out: bool = False) -> dict:
    meta = m.metadata_json or {}
    d = {
        "version": m.model_version, "trained_at": iso(m.trained_at), "rows": m.rows, "date_from": iso(m.date_from),
        "date_to": iso(m.date_to), "mae": m.mae, "rmse": m.rmse, "baseline_mae": m.baseline_mae, "baseline_rmse": m.baseline_rmse,
        "beats_baseline": m.mae < m.baseline_mae and m.rmse < m.baseline_rmse, "is_active": m.is_active, "notes": m.notes,
        "features": meta.get("features"), "params": meta.get("params"), "train_rows": meta.get("train_rows"),
        "test_rows": meta.get("test_rows"),
    }
    if with_held_out:
        d["held_out"] = meta.get("held_out", [])
    return d


@bp.get("/model")
@login_required
def get_model():
    now = utcnow()
    rows = list(db().scalars(select(MLModel).order_by(MLModel.trained_at.desc())))
    active = next((m for m in rows if m.is_active), None)
    st = current_settings()
    req = db().get(AppState, "retrain_request")
    return jsonify({
        "active": model_public(active, with_held_out=True) if active else None,
        "versions": [model_public(m) for m in rows],
        "live": live_accuracy(active.model_version if active else None, since=now - timedelta(days=7)) if active else None,
        "phase": phase_info(st, now, active_model_exists()),
        "trainer_available": sklearn_available(),
        "retrain_requested_at": (req.value_json or {}).get("at") if req else None,
    })


@bp.post("/model/retrain")
@roles_required("manager")
def retrain():
    now = utcnow()
    audit("model.retrain_requested", "ml_models")
    if not sklearn_available():
        # Vercel functions do not ship scikit-learn: queue for the training job.
        s = db()
        row = s.get(AppState, "retrain_request")
        if row is None:
            s.add(AppState(key="retrain_request", value_json={"at": iso(now)}, updated_at=now))
        else:
            row.value_json, row.updated_at = {"at": iso(now)}, now
        return jsonify({"queued": True, "message": "Retraining is queued. The training job (worker or GitHub Action) picks it up."}), 202
    try:
        m = train_model(now, notes="manual retrain")
    except TrainingUnavailable as e:
        raise ApiError(409, "training_unavailable", str(e)) from e
    from ..services.jobs import _phase_sync

    _phase_sync(now)
    audit("model.trained", f"model:{m.model_version}", None, {"active": m.is_active, "mae": m.mae, "rmse": m.rmse})
    return jsonify({"model": model_public(m)}), 201


@bp.post("/model/<version>/activate")
@roles_required("manager")
def activate_version(version: str):
    m = db().get(MLModel, version)
    if m is None:
        raise ApiError(404, "not_found", "No such model version.")
    if not (m.mae < m.baseline_mae and m.rmse < m.baseline_rmse):
        raise ApiError(409, "does_not_beat_baseline", "This model is not better than guessing 'same as now', so it cannot be used.")
    activate(m)
    from ..services.jobs import _phase_sync

    _phase_sync(utcnow())
    audit("model.activate", f"model:{version}")
    return jsonify({"model": model_public(m)})
