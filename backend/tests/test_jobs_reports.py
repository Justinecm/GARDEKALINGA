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


def test_fresh_install_has_no_mock_data(client, login):
    """No seeded users, device, readings or forecast: everything shown comes from the ESP32."""
    from sqlalchemy import func, select

    from backend.models import Device, SensorLog, User, WeatherForecast

    s = SessionLocal()
    assert s.scalar(select(func.count()).select_from(User)) == 0
    login()
    st = client.get("/api/v1/status").json
    assert "demo" not in st
    assert st["device"] is None and st["reading"] is None and st["status"]["code"] == "no_readings"
    assert s.scalar(select(func.count()).select_from(Device)) == 0
    assert s.scalar(select(func.count()).select_from(SensorLog)) == 0
    # Without OWM_API_KEY there is no forecast at all (no synthetic weather).
    assert s.scalar(select(func.count()).select_from(WeatherForecast)) == 0
    assert client.get("/api/v1/demo").status_code == 404
    me = client.get("/api/v1/auth/me").json
    assert "demo" not in me and "demo_accounts" not in me


def test_status_shows_device_reading(client, login, dev_client):
    from backend.tests.conftest import reading

    login()
    r = dev_client.post("/api/device/v1/readings", reading("esp32-0001"))
    assert r.status_code == 200, r.json
    st = client.get("/api/v1/status").json
    assert st["device"]["id"] == "gk-node-01"
    probes = {p["id"]: p for p in st["reading"]["probes"]}
    assert probes["S1"]["vwc"] == 31.4 and probes["S1"]["raw"] == 2210
    assert probes["S3"]["fault"] is True


def test_vercel_requires_real_database(monkeypatch):
    import pytest

    from backend.config import load_settings

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("SECRET_KEY", raising=False)
    # A leftover GK_DEMO_MODE=true must not bring back the throwaway SQLite garden.
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        load_settings({"VERCEL": "1", "GK_DEMO_MODE": "true", "SECRET_KEY": "x"})
