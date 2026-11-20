"""Device API: HMAC auth, replay, ingestion, decisions, commands, sync (C-3, TC3/4/5/7/10)."""
import time
from datetime import timedelta

from backend.db import SessionLocal
from backend.models import ActuationEvent, ControlDecision, DeviceCommand, SensorLog
from backend.timeutil import iso, utcnow

from .conftest import reading


def test_reading_and_decision(dev_client):
    r = dev_client.post("/api/device/v1/readings", reading(probes=((2900, 20.0, False), (2800, 24.0, False), (40, None, True))))
    assert r.status_code == 200, r.json
    body = r.json
    # mean 22 < 30 and no forecast stored yet: water, rain pause not applied
    assert body["decision"]["action"] == "water" and body["decision"]["reason"] == "forecast_stale"
    assert body["decision"]["duration_s"] == 180
    log = SessionLocal().query(SensorLog).one()
    assert log.active_probe_count == 2 and log.probe_fault_json["S3"] is True  # TC3: raw 40 is faulty
    assert body["settings"]["v"] >= 1  # settings pushed because the node had version 0


def test_decision_values(dev_client):
    r = dev_client.post("/api/device/v1/readings", reading(probes=((2000, 35.0, False), (2000, 36.0, False), (2000, 34.0, False))))
    assert r.json["decision"] == {"id": r.json["decision"]["id"], "action": "none", "duration_s": 0, "reason": "moist_enough"}


def test_fault_rule_overrides_node(dev_client):
    # The node says not faulty but raw 3900 is above 95% of the span.
    dev_client.post("/api/device/v1/readings", reading(probes=((3900, 5.0, False), (2000, 35.0, False), (2000, 35.0, False))))
    log = SessionLocal().query(SensorLog).one()
    assert log.probe_fault_json["S1"] is True and log.spatial_mean_vwc == 35.0


def test_idempotent_reading(dev_client):
    a = dev_client.post("/api/device/v1/readings", reading(uuid="same-uuid-1"))
    b = dev_client.post("/api/device/v1/readings", reading(uuid="same-uuid-1"))
    assert a.json["decision"]["id"] == b.json["decision"]["id"]
    assert SessionLocal().query(SensorLog).count() == 1
    assert SessionLocal().query(ControlDecision).count() == 1


def test_bad_signature_and_replay(dev_client, client):
    good = dev_client._headers("GET", "/api/device/v1/poll", b"", nonce="ab" * 16)
    assert client.get("/api/device/v1/poll", headers=good).status_code == 200
    assert client.get("/api/device/v1/poll", headers=good).json["error"]["code"] == "device_replay"
    bad = dict(good, **{"X-GK-Signature": "0" * 64, "X-GK-Nonce": "cd" * 16})
    assert client.get("/api/device/v1/poll", headers=bad).status_code == 401
    skew = dev_client._headers("GET", "/api/device/v1/poll", b"", ts=int(time.time()) - 500)
    assert client.get("/api/device/v1/poll", headers=skew).json["error"]["code"] == "device_clock_skew"
    unsynced = dev_client._headers("GET", "/api/device/v1/poll", b"", ts=1234)
    r = client.get("/api/device/v1/poll", headers=unsynced)
    assert r.status_code == 200 and r.json.get("tu") == 1
    assert client.get("/api/device/v1/poll").status_code == 401


def test_poll_size_and_command_flow(dev_client, client, login):
    csrf = login("cara", "caretaker")
    assert dev_client.get("/api/device/v1/poll?p=0&v=0&src=adapter&sv=12.02&m=online&w=0&rem=0&s=1").status_code == 200
    r = client.post("/api/v1/watering/start", json={"duration_s": 900}, headers={"X-CSRF-Token": csrf})
    assert r.status_code == 202
    cmd_id = r.json["command"]["id"]
    assert r.json["command"]["duration_s"] == 180  # Tier 1 clamp to max_actuation_sec
    p = dev_client.get("/api/device/v1/poll?p=0&v=0&src=adapter&sv=12.02&m=online&w=0&rem=0&s=1")
    assert len(p.data) <= 300  # NFR-PERF-02
    assert p.json["cmd"] == [{"id": cmd_id, "op": "start", "d": 180}]
    a = dev_client.post(f"/api/device/v1/commands/{cmd_id}/ack", {"status": "executed", "at": iso(utcnow())})
    assert a.status_code == 200
    c = client.get(f"/api/v1/commands/{cmd_id}").json["command"]
    assert c["phase"] == "executed" and c["latency_s"] <= 6
    # The node reports the finished manual cycle; the user is attached from the command (TC7).
    now = utcnow()
    ev = {"uuid": "ev-000001", "type": "actuation", "trigger_source": "manual", "command_id": cmd_id,
          "valve_open_at": iso(now), "pump_on_at": iso(now + timedelta(milliseconds=501)),
          "pump_off_at": iso(now + timedelta(seconds=180)), "valve_closed_at": iso(now + timedelta(seconds=180.1)),
          "interlock_ms": 501, "close_gap_ms": 102, "duration_s": 180, "ended_reason": "max_cutoff"}
    assert dev_client.post("/api/device/v1/events", ev).json["stored"] == 1
    assert dev_client.post("/api/device/v1/events", ev).json["stored"] == 0  # idempotent
    e = SessionLocal().query(ActuationEvent).one()
    assert e.user_id is not None and e.interlock_ms == 501 and e.ended_reason == "max_cutoff"
    # TC5: soak after the cycle blocks the next automatic decision
    r = dev_client.post("/api/device/v1/readings", reading(uuid="after-0001", probes=((2900, 15.0, False),)))
    assert r.json["decision"]["reason"] == "soak"


def test_start_blocked_when_offline(client, login, device):
    csrf = login("cara", "caretaker")
    r = client.post("/api/v1/watering/start", json={"duration_s": 60}, headers={"X-CSRF-Token": csrf})
    assert r.status_code == 409 and r.json["error"]["code"] == "start_blocked_offline"


def test_offline_sync(dev_client):
    now = utcnow()
    body = {
        "readings": [reading(uuid=f"offline-{i:04d}", recorded_at=iso(now - timedelta(minutes=30 * (4 - i))), control_mode="offline_failsafe")
                     for i in range(4)],
        "events": [{"uuid": "off-ev-1", "type": "actuation", "trigger_source": "offline_failsafe", "valve_open_at": iso(now),
                    "pump_on_at": iso(now), "pump_off_at": iso(now), "duration_s": 180, "interlock_ms": 500, "close_gap_ms": 100,
                    "ended_reason": "completed"},
                   {"uuid": "off-pw-1", "type": "power_transition", "occurred_at": iso(now), "from": "solar", "to": "adapter", "supply_v": 11.58},
                   {"uuid": "off-boot-1", "type": "boot", "occurred_at": iso(now), "reset_reason": "TASK_WDT", "fw": "1.0.0"}],
    }
    r = dev_client.post("/api/device/v1/sync", body)
    assert r.json["accepted"] == {"readings": 4, "events": 3}
    r = dev_client.post("/api/device/v1/sync", body)
    assert r.json["accepted"] == {"readings": 0, "events": 0}
    s = SessionLocal()
    assert s.query(SensorLog).filter(SensorLog.synced_offline.is_(True)).count() == 4
    assert s.query(ControlDecision).count() == 0  # synced readings get no new decision


def test_command_expiry(app, client, login, dev_client):
    from backend.services.device_service import expire_commands

    csrf = login("cara", "caretaker")
    dev_client.get("/api/device/v1/poll?p=0&v=0")
    cid = client.post("/api/v1/watering/start", json={"duration_s": 60}, headers={"X-CSRF-Token": csrf}).json["command"]["id"]
    assert expire_commands(utcnow() + timedelta(seconds=61)) == 1
    SessionLocal().commit()
    assert SessionLocal().get(DeviceCommand, cid).status == "expired"


def test_legacy_sketch_endpoint(client, device):
    body = {"device_id": "gk-node-01", "readings": {"soil_moisture": 45, "temperature": None},
            "irrigation": {"state": "RUNNING", "mode": "AUTO"}}
    r = client.post("/api/sensors/readings", json=body, headers={"X-Device-Key": device["secret"]})
    assert r.status_code == 200 and r.json["stored"] is True
    r = client.post("/api/sensors/readings", json=body, headers={"X-Device-Key": device["secret"]})
    assert r.json["stored"] is False  # one stored reading per 30-minute slot
    assert client.post("/api/sensors/readings", json=body, headers={"X-Device-Key": "nope"}).status_code == 401
