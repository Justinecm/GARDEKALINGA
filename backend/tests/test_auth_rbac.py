"""Login, throttling, CSRF, roles, re-auth, audit (FR-SEC, C-9)."""
from backend.db import SessionLocal
from backend.models import AuditLog


def test_login_required(client):
    for path in ("/api/v1/status", "/api/v1/readings", "/api/v1/settings", "/api/v1/users", "/api/v1/model"):
        assert client.get(path).status_code == 401
    assert client.get("/api/health").status_code == 200


def test_bad_password_and_lockout(client, make_user):
    make_user("ana", "manager", "correct-horse-1")
    r = client.post("/api/v1/auth/login", json={"username": "ana", "password": "wrong"})
    assert r.status_code == 401 and r.json["error"]["code"] == "bad_credentials"
    codes = [client.post("/api/v1/auth/login", json={"username": "ana", "password": "wrong"}).status_code for _ in range(5)]
    assert 429 in codes  # 5 per minute per IP and username
    assert SessionLocal().query(AuditLog).filter(AuditLog.action == "auth.login_failed").count() >= 4


def test_csrf_required(client, login):
    login("cara", "caretaker")
    r = client.post("/api/v1/watering/stop")
    assert r.status_code == 403 and r.json["error"]["code"] == "csrf_failed"


def test_role_matrix(client, login):
    csrf = login("lea", "leader")
    h = {"X-CSRF-Token": csrf}
    assert client.get("/api/v1/status").status_code == 200
    assert client.post("/api/v1/watering/start", json={"duration_s": 60}, headers=h).status_code == 403
    assert client.post("/api/v1/settings", json={}, headers=h).status_code == 403
    assert client.get("/api/v1/users").status_code == 403
    assert client.get("/api/v1/reports/irrigation.csv").status_code == 200
    assert client.get("/api/v1/audit").status_code == 200


def test_caretaker_cannot_export_or_configure(client, login):
    csrf = login("cara", "caretaker")
    assert client.get("/api/v1/reports/irrigation.csv").status_code == 403
    assert client.post("/api/v1/settings", json={"moisture_threshold": 31}, headers={"X-CSRF-Token": csrf}).status_code == 403


def test_manager_settings_versioning(client, login):
    csrf = login()
    h = {"X-CSRF-Token": csrf}
    v1 = client.get("/api/v1/settings").json["settings"]["version"]
    r = client.post("/api/v1/settings", json={"moisture_threshold": 32.5, "note": "after cold start"}, headers=h)
    assert r.status_code == 200 and r.json["settings"]["version"] == v1 + 1
    assert r.json["changed"] == ["moisture_threshold"]
    bad = client.post("/api/v1/settings", json={"moisture_threshold": 99}, headers=h)
    assert bad.status_code == 422 and "moisture_threshold" in bad.json["error"]["fields"]
    fixed = client.post("/api/v1/settings", json={"cold_start_days": 7}, headers=h)
    assert fixed.status_code == 422
    assert client.get("/api/v1/settings/history").json["items"][0]["changed"] == {"moisture_threshold": 32.5}


def test_reauth_after_15_minutes(client, login):
    from freezegun import freeze_time

    csrf = login()
    with freeze_time(None) as _:
        pass
    with client.session_transaction() as sess:
        sess["auth_at"] = sess["auth_at"] - 16 * 60
    r = client.post("/api/v1/settings", json={"moisture_threshold": 31}, headers={"X-CSRF-Token": csrf})
    assert r.status_code == 401 and r.json["error"]["code"] == "reauth_required"
    assert client.post("/api/v1/auth/reauth", json={"password": "correct-horse-1"}, headers={"X-CSRF-Token": csrf}).status_code == 200
    assert client.post("/api/v1/settings", json={"moisture_threshold": 31}, headers={"X-CSRF-Token": csrf}).status_code == 200


def test_user_management(client, login):
    csrf = login()
    h = {"X-CSRF-Token": csrf}
    r = client.post("/api/v1/users", json={"full_name": "Jun Cruz", "username": "jun", "role": "caretaker", "password": "short"}, headers=h)
    assert r.status_code == 422
    r = client.post("/api/v1/users", json={"full_name": "Jun Cruz", "username": "jun", "role": "caretaker", "password": "long-enough-1"}, headers=h)
    assert r.status_code == 201
    uid = r.json["user"]["id"]
    assert client.patch(f"/api/v1/users/{uid}", json={"is_active": False}, headers=h).json["user"]["is_active"] is False
    assert client.post("/api/v1/auth/login", json={"username": "jun", "password": "long-enough-1"}).status_code == 401
    me = client.get("/api/v1/auth/me").json["user"]["id"]
    assert client.patch(f"/api/v1/users/{me}", json={"role": "caretaker"}, headers=h).json["error"]["code"] == "last_manager"
