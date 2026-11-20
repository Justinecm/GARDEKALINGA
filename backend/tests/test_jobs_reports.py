from datetime import datetime, timedelta

from backend.db import SessionLocal
from backend.models import ActuationEvent
from backend.services.jobs import _last_local_boundary, compute_daily_water
from backend.timeutil import manila_to_utc


def test_local_boundaries():
    now = datetime(2026, 11, 22, 17, 5)  # Mon 01:05 Manila (Sunday 17:05 UTC)
    assert _last_local_boundary(now, 0, 15) == datetime(2026, 11, 22, 16, 15)
    assert _last_local_boundary(now, 1, 0, weekday=6) == datetime(2026, 11, 21, 17, 0)  # Sunday 01:00 Manila


def test_daily_water_equation_8(app):
    s = SessionLocal()
    start = manila_to_utc(datetime(2026, 11, 20, 6, 0))
    for i in range(3):
        s.add(ActuationEvent(trigger_source="auto", pump_on_at=start + timedelta(hours=i), duration_sec=120))
    s.commit()
    row = compute_daily_water("2026-11-20", 1.5)
    assert row.pump_seconds == 360 and row.litres == 9.0 and row.runs == 3


def test_cron_requires_secret(client):
    assert client.get("/api/cron/due").status_code == 401
    r = client.get("/api/cron/expire_commands", headers={"Authorization": "Bearer cron-test"})
    assert r.status_code == 200


def test_test_bench_tc14(client, login):
    csrf = login()
    for v, t in ((3.0, 120), (3.05, 120), (2.95, 120), (3.0, 121), (3.02, 119)):
        r = client.post("/api/v1/test-records", json={"tc_number": 14, "inputs": {"volume_l": v, "time_s": t}}, headers={"X-CSRF-Token": csrf})
        assert r.status_code == 201
    summ = client.get("/api/v1/test-records?tc=14").json["summary"]["14"]
    assert summ["within_10pct"] is True and abs(summ["mean_flow_lpm"] - 1.5) < 0.05
    csv = client.get("/api/v1/test-records/14.csv")
    assert csv.status_code == 200 and b"flow_lpm" in csv.data


def test_demo_mode_runs(tmp_path, monkeypatch):
    from backend.app import create_app

    monkeypatch.delenv("DATABASE_URL", raising=False)
    a = create_app({"DATABASE_URL": f"sqlite:///{tmp_path / 'demo.db'}", "GK_DEMO_MODE": "true", "SECRET_KEY": "x"})
    with a.app_context():
        c = a.test_client()
        r = c.post("/api/v1/auth/login", json={"username": "manager", "password": "gardekalinga-demo"})
        assert r.status_code == 200
        st = c.get("/api/v1/status").json
        assert st["demo"] is True and st["reading"] is not None and st["device"]["online"] is True
        h = {"X-CSRF-Token": r.json["csrf"]}
        assert c.post("/api/v1/demo", json={"action": "fault", "value": {"probe": "S2", "on": True}}, headers=h).status_code == 200
        SessionLocal.remove()
