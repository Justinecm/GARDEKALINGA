"""Training (FR-ML-03..07). Needs scikit-learn (requirements-ml.txt), so it runs in
the worker, the CLI (`make train`) or the scheduled GitHub Action, never inside
the Vercel function. The trained forest is exported to JSON for forest_runtime.
"""
from __future__ import annotations

import json
import math
import os
from datetime import datetime

from sqlalchemy import func, select, update

from ...db import db
from ...models import MLModel, SensorLog
from ...timeutil import iso, utcnow
from . import forest_runtime
from .dataset import FEATURES, build_dataset

MIN_ROWS = 24


class TrainingUnavailable(RuntimeError):
    pass


def sklearn_available() -> bool:
    try:
        import sklearn  # noqa: F401

        return True
    except ImportError:
        return False


def mae(y: list[float], p: list[float]) -> float:
    return sum(abs(a - b) for a, b in zip(y, p, strict=True)) / len(y)


def rmse(y: list[float], p: list[float]) -> float:
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(y, p, strict=True)) / len(y))


def export_forest(rf, features: list[str]) -> dict:
    trees = []
    for est in rf.estimators_:
        t = est.tree_
        trees.append(
            {
                "l": [int(v) for v in t.children_left],
                "r": [int(v) for v in t.children_right],
                "f": [int(v) if v >= 0 else 0 for v in t.feature],
                "t": [float(v) for v in t.threshold],
                "v": [round(float(v), 6) for v in t.value[:, 0, 0]],
            }
        )
    return {"features": features, "trees": trees}


def train_model(now: datetime | None = None, notes: str | None = None, n_estimators: int = 300) -> MLModel:
    if not sklearn_available():
        raise TrainingUnavailable("scikit-learn is not installed here. Run training in the worker or with `make train`.")
    from sklearn.ensemble import RandomForestRegressor

    now = now or utcnow()
    s = db()
    first = s.scalar(select(func.min(SensorLog.recorded_at)))
    if first is None:
        raise TrainingUnavailable("No readings yet.")
    rows = build_dataset(first, now)
    if len(rows) < MIN_ROWS:
        raise TrainingUnavailable(f"Only {len(rows)} usable hours; need at least {MIN_ROWS}.")

    # Chronological split: train on earlier records, test on the latest 20%. Never shuffle.
    cut = int(len(rows) * 0.8)
    train, test = rows[:cut], rows[cut:]
    X_tr = [[r.features[f] for f in FEATURES] for r in train]
    y_tr = [float(r.target) for r in train]  # type: ignore[arg-type]
    X_te = [[r.features[f] for f in FEATURES] for r in test]
    y_te = [float(r.target) for r in test]  # type: ignore[arg-type]

    rf = RandomForestRegressor(n_estimators=n_estimators, min_samples_leaf=2, random_state=42, n_jobs=1)
    rf.fit(X_tr, y_tr)
    pred = [float(v) for v in rf.predict(X_te)]
    base = [r.features["mean_vwc"] for r in test]  # persistence baseline

    m_mae, m_rmse = mae(y_te, pred), rmse(y_te, pred)
    b_mae, b_rmse = mae(y_te, base), rmse(y_te, base)
    beats = m_mae < b_mae and m_rmse < b_rmse

    version = "rf-" + now.strftime("%Y%m%d-%H%M%S")
    forest = export_forest(rf, FEATURES)
    meta = {
        "version": version,
        "features": FEATURES,
        "params": {"n_estimators": n_estimators, "min_samples_leaf": 2, "random_state": 42},
        "date_from": iso(rows[0].hour),
        "date_to": iso(rows[-1].hour),
        "rows": len(rows),
        "train_rows": len(train),
        "test_rows": len(test),
        "metrics": {"mae": m_mae, "rmse": m_rmse, "baseline_mae": b_mae, "baseline_rmse": b_rmse},
        "beats_baseline": beats,
        "held_out": [
            {"hour": iso(r.hour), "actual": y, "predicted": round(p, 3), "baseline": round(b, 3)}
            for r, y, p, b in zip(test, y_te, pred, base, strict=True)
        ],
    }
    model = MLModel(
        model_version=version,
        trained_at=now,
        rows=len(rows),
        date_from=rows[0].hour,
        date_to=rows[-1].hour,
        mae=round(m_mae, 4),
        rmse=round(m_rmse, 4),
        baseline_mae=round(b_mae, 4),
        baseline_rmse=round(b_rmse, 4),
        is_active=False,
        notes=notes,
        metadata_json=meta,
        artifact=forest_runtime.pack(forest),
    )
    s.add(model)
    s.flush()
    # FR-ML-06: activate only if both MAE and RMSE beat persistence.
    if beats:
        activate(model)
    _save_joblib(rf, meta)
    return model


def activate(model: MLModel) -> None:
    s = db()
    s.execute(update(MLModel).where(MLModel.model_version != model.model_version).values(is_active=False))
    model.is_active = True


def _save_joblib(rf, meta: dict) -> None:
    """FR-ML-04: joblib + metadata JSON when a model directory is writable (Docker volume)."""
    folder = os.environ.get("GK_MODEL_DIR")
    if not folder:
        return
    try:
        import joblib

        os.makedirs(folder, exist_ok=True)
        joblib.dump(rf, os.path.join(folder, meta["version"] + ".joblib"))
        with open(os.path.join(folder, meta["version"] + ".json"), "w") as fh:
            json.dump({k: v for k, v in meta.items() if k != "held_out"}, fh, indent=2)
    except OSError:
        pass
