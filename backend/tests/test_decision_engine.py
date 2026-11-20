"""Table-driven tests for every branch of decide() (C-4), including boundaries."""
from datetime import datetime, timedelta

import pytest

from backend.services.decision_engine import DecisionInputs, decide
from backend.services.rain_pause import evaluate

NOW = datetime(2026, 12, 1, 6, 30)


def inputs(**kw):
    base = dict(now=NOW, mean_vwc=35.0, active_probes={"S1": 35.0, "S2": 35.0, "S3": 35.0}, watering_in_progress=False,
                last_watering_end=None, phase="cold_start", predicted_vwc=None, threshold=30.0, probe_min=22.0,
                soak_sec=1800, max_sec=180, rain_active=False, rain_stale=False)
    base.update(kw)
    return DecisionInputs(**base)


CASES = [
    ("moist", {}, "none", "moist_enough"),
    ("already watering", {"watering_in_progress": True, "mean_vwc": 10.0}, "none", "already_watering"),
    ("all faulty", {"active_probes": {}, "mean_vwc": None}, "none", "sensor_fault_schedule"),
    ("in soak", {"mean_vwc": 20.0, "last_watering_end": NOW - timedelta(seconds=1799)}, "none", "soak"),
    ("soak just ended", {"mean_vwc": 20.0, "active_probes": {"S1": 20.0}, "last_watering_end": NOW - timedelta(seconds=1800)},
     "water", "cold_start_threshold"),
    ("cold start below", {"mean_vwc": 29.9, "active_probes": {"S1": 29.9}}, "water", "cold_start_threshold"),
    ("threshold equality", {"mean_vwc": 30.0, "active_probes": {"S1": 30.0}}, "none", "moist_enough"),
    ("one dry probe", {"mean_vwc": 34.0, "active_probes": {"S1": 21.9, "S2": 40.0, "S3": 40.1}}, "water", "probe_below_min"),
    ("probe at minimum", {"mean_vwc": 34.0, "active_probes": {"S1": 22.0, "S2": 40.0, "S3": 40.0}}, "none", "moist_enough"),
    ("predictive below", {"phase": "predictive", "predicted_vwc": 29.0}, "water", "predicted_below_threshold"),
    ("predictive above even if now dry", {"phase": "predictive", "predicted_vwc": 31.0, "mean_vwc": 29.0,
                                          "active_probes": {"S1": 29.0}}, "none", "moist_enough"),
    ("prediction unavailable, dry", {"phase": "predictive", "mean_vwc": 25.0, "active_probes": {"S1": 25.0}}, "water",
     "prediction_unavailable"),
    ("prediction unavailable, moist", {"phase": "predictive"}, "none", "prediction_unavailable"),
    ("rain pause", {"mean_vwc": 25.0, "active_probes": {"S1": 25.0}, "rain_active": True}, "none", "rain_pause"),
    ("rain pause blocks dry probe", {"active_probes": {"S1": 15.0, "S2": 45.0}, "rain_active": True}, "none", "rain_pause"),
    ("forecast stale waters", {"mean_vwc": 25.0, "active_probes": {"S1": 25.0}, "rain_stale": True}, "water", "forecast_stale"),
    ("stale forecast, moist", {"rain_stale": True}, "none", "moist_enough"),
]


@pytest.mark.parametrize("name,kw,action,reason", CASES, ids=[c[0] for c in CASES])
def test_decide(name, kw, action, reason):
    d = decide(inputs(**kw))
    assert (d.action, d.reason) == (action, reason)
    if action == "water":
        assert d.duration_s == 180


class S:
    def __init__(self, h, pop, mm):
        self.forecast_for, self.pop_pct, self.rain_3h_mm = NOW + timedelta(hours=h), pop, mm


@pytest.mark.parametrize("steps,expected", [
    ([S(1, 70, 2.0)], True),                       # exactly 70% and exactly 2.0 mm
    ([S(1, 69.9, 5.0)], False),
    ([S(1, 90, 1.99)], False),
    ([S(1, 80, 1.0), S(4, 20, 1.0)], True),         # chance = max, rain = sum
    ([S(1, 80, 1.0), S(6.5, 90, 5.0)], False),      # outside the 6 h window
    ([S(6, 75, 2.5)], True),                        # window end inclusive
    ([], False),
])
def test_rain_rule(steps, expected):
    active, *_ = evaluate(steps, NOW, 70, 2.0, 6)
    assert active is expected
