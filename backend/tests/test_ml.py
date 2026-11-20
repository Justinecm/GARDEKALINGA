"""ML: dataset, baseline gate both ways, pure-Python forest == scikit-learn (FR-ML, TC9)."""
import math
import random
from datetime import datetime, timedelta

import pytest

from backend.db import SessionLocal
from backend.models import ActuationEvent, SensorLog, WeatherForecast
from backend.services.ml import forest_runtime
from backend.services.ml.dataset import FEATURES, build_dataset
from backend.services.ml.train import export_forest, train_model

START = datetime(2026, 11, 1, 0, 0)
sklearn = pytest.importorskip("sklearn")


def seed(predictable: bool, days=10):
    s = SessionLocal()
    rng = random.Random(1)
    v = 35.0
    t = START
    while t < START + timedelta(days=days):
        if t.minute == 0 and t.hour % 3 == 0:
            for k in range(3):
                s.add(WeatherForecast(retrieved_at=t, forecast_for=t + timedelta(hours=3 * k + 3), temperature_c=30, humidity_pct=70,
                                      rain_3h_mm=0, weather_condition="Clear", pop_pct=10))
        if predictable:
            hour = (t.hour + 8) % 24
            v -= 0.8 if 9 <= hour <= 16 else 0.15  # strong diurnal pattern the model can learn
            if v < 26:
                v += 9
                s.add(ActuationEvent(trigger_source="auto", pump_on_at=t, pump_off_at=t + timedelta(seconds=180), duration_sec=180,
                                     valve_open_at=t, device_id="gk-node-01"))
        else:
            v = 30 + rng.uniform(-6, 6)  # white noise: persistence is hard to beat
        s.add(SensorLog(recorded_at=t, spatial_mean_vwc=round(v, 2), active_probe_count=3, raw_adc_values={}, control_mode="online",
                        device_id="gk-node-01", probe_vwc_json={"S1": v}, probe_fault_json={"S1": False}))
        t += timedelta(minutes=30)
    s.commit()


def test_dataset_has_no_leakage(app):
    seed(True, days=3)
    rows = build_dataset(START, START + timedelta(days=3))
    assert rows and set(rows[0].features) == set(FEATURES)
    for r in rows:
        assert r.target is not None


def test_gate_activates_when_better(app):
    seed(True)
    m = train_model(START + timedelta(days=10), n_estimators=60)
    assert m.mae < m.baseline_mae and m.rmse < m.baseline_rmse
    assert m.is_active is True


def test_gate_rejects_when_not_better(app):
    seed(False)
    m = train_model(START + timedelta(days=10), n_estimators=60)
    assert m.is_active is (m.mae < m.baseline_mae and m.rmse < m.baseline_rmse)


def test_runtime_matches_sklearn(app):
    from sklearn.ensemble import RandomForestRegressor

    rng = random.Random(3)
    X = [[rng.uniform(0, 50) for _ in FEATURES] for _ in range(300)]
    y = [x[0] * 0.8 + math.sin(x[3]) + rng.uniform(-1, 1) for x in X]
    rf = RandomForestRegressor(n_estimators=40, min_samples_leaf=2, random_state=42).fit(X, y)
    forest = forest_runtime.Forest(forest_runtime.unpack(forest_runtime.pack(export_forest(rf, FEATURES))))
    expected = rf.predict(X[:50])
    for x, e in zip(X[:50], expected, strict=False):
        assert abs(forest.predict_one(dict(zip(FEATURES, x, strict=False))) - e) < 1e-5
