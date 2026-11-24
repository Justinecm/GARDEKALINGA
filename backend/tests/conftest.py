import hashlib
import hmac
import json
import os
import secrets
import time

import pytest

from backend.app import create_app
from backend.db import SessionLocal


@pytest.fixture()
def app(tmp_path, monkeypatch):
    for k in ("DATABASE_URL", "OWM_API_KEY", "VERCEL", "CRON_SECRET", "GK_LEGACY_DEVICE_API"):
        monkeypatch.delenv(k, raising=False)
    # GK_TEST_DATABASE_URL=mysql+pymysql://... runs the same suite on MySQL 8.4.
    url = os.environ.get("GK_TEST_DATABASE_URL") or f"sqlite:///{tmp_path / 'test.db'}"
    if url.startswith("mysql"):
        from sqlalchemy import create_engine

        from backend import models  # noqa: F401
        from backend.db import Base

        eng = create_engine(url)
        Base.metadata.drop_all(eng)
        eng.dispose()
    a = create_app({
        "DATABASE_URL": url,
        "SECRET_KEY": "test-secret-key",
        "GK_AUTO_CREATE_TABLES": "true",
        "CRON_SECRET": "cron-test",
        "GK_LEGACY_DEVICE_API": "true",
    })
    a.config["TESTING"] = True
    with a.app_context():
        yield a
        SessionLocal.remove()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def make_user(app):
    from backend.models import User
    from backend.security import hash_password
    from backend.timeutil import utcnow

    def _make(username="ana", role="manager", password="correct-horse-1"):
        s = SessionLocal()
        u = User(full_name=username.title(), username=username, password_hash=hash_password(password), role=role,
                 created_at=utcnow(), is_active=True, theme="auto")
        s.add(u)
        s.commit()
        return u

    return _make


@pytest.fixture()
def login(client, make_user):
    def _login(username="ana", role="manager", password="correct-horse-1"):
        make_user(username, role, password)
        r = client.post("/api/v1/auth/login", json={"username": username, "password": password})
        assert r.status_code == 200, r.json
        return r.json["csrf"]

    return _login


@pytest.fixture()
def device(app):
    from backend.blueprints.admin import register_device

    d, secret = register_device("gk-node-01", "Box B")
    SessionLocal().commit()
    return {"id": d.device_id, "secret": secret}


class DeviceClient:
    """Signs requests exactly like the firmware (C-3)."""

    def __init__(self, client, device_id, secret):
        self.c, self.id, self.secret = client, device_id, secret

    def _headers(self, method, path, body: bytes, ts=None, nonce=None):
        ts = str(int(time.time()) if ts is None else ts)
        nonce = nonce or secrets.token_hex(16)
        msg = "\n".join([method, path, ts, nonce, hashlib.sha256(body).hexdigest()]).encode()
        sig = hmac.new(bytes.fromhex(self.secret), msg, hashlib.sha256).hexdigest()
        return {"X-GK-Device": self.id, "X-GK-Timestamp": ts, "X-GK-Nonce": nonce, "X-GK-Signature": sig,
                "Content-Type": "application/json"}

    def post(self, path, payload, **kw):
        body = json.dumps(payload).encode()
        return self.c.post(path, data=body, headers=self._headers("POST", path, body, **kw))

    def get(self, path, **kw):
        return self.c.get(path, headers=self._headers("GET", path, b"", **kw))


@pytest.fixture()
def dev_client(client, device):
    return DeviceClient(client, device["id"], device["secret"])


def reading(uuid="r-0000001", mean=None, probes=((2210, 31.4, False), (2350, 28.9, False), (40, None, True)), **extra):
    body = {
        "reading_uuid": uuid,
        "probes": [{"id": f"S{i+1}", "raw": raw, "vwc": vwc, "fault": f} for i, (raw, vwc, f) in enumerate(probes)],
        "supply_v": 12.02, "power_source": "adapter", "control_mode": "online", "settings_version": 0, "fw": "1.0.0",
    }
    body.update(extra)
    return body
