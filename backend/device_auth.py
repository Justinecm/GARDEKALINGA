"""Device authentication (BUILD_PROMPT C-3).

Headers on every device request:
  X-GK-Device, X-GK-Timestamp (unix s), X-GK-Nonce (32 hex chars), X-GK-Signature
  signature = hex(HMAC_SHA256(secret, METHOD \n PATH_WITH_QUERY \n TS \n NONCE \n hex(SHA256(body))))

Device secrets are 32 random bytes, shown once, stored Fernet-encrypted.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import timedelta
from functools import wraps
from typing import Callable

from cryptography.fernet import Fernet, InvalidToken
from flask import current_app, g, request
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError

from .db import db
from .errors import ApiError
from .models import Device, DeviceNonce
from .timeutil import utcnow

MAX_SKEW_S = 120
NONCE_TTL = timedelta(minutes=10)
# A timestamp before 2020-09 means the node has not synced its clock yet.
UNSYNCED_BEFORE = 1_600_000_000


def _fernet() -> Fernet:
    return Fernet(current_app.config["GK"].device_key_enc_key.encode())


def new_device_secret() -> str:
    return secrets.token_hex(32)


def encrypt_secret(secret_hex: str) -> str:
    return _fernet().encrypt(secret_hex.encode()).decode()


def decrypt_secret(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as e:  # wrong DEVICE_KEY_ENC_KEY
        raise ApiError(500, "device_key_unreadable", "Device key cannot be decrypted. Check DEVICE_KEY_ENC_KEY.") from e


def sign(secret_hex: str, method: str, path_with_query: str, ts: str, nonce: str, body: bytes) -> str:
    body_hash = hashlib.sha256(body or b"").hexdigest()
    msg = "\n".join([method.upper(), path_with_query, ts, nonce, body_hash]).encode()
    return hmac.new(bytes.fromhex(secret_hex), msg, hashlib.sha256).hexdigest()


@dataclass
class DeviceContext:
    device: Device
    time_unsynced: bool


def _path_with_query() -> str:
    qs = request.query_string.decode()
    return request.path + ("?" + qs if qs else "")


def verify_device_request() -> DeviceContext:
    device_id = request.headers.get("X-GK-Device", "")
    ts = request.headers.get("X-GK-Timestamp", "")
    nonce = request.headers.get("X-GK-Nonce", "")
    sig = request.headers.get("X-GK-Signature", "")
    if not (device_id and ts and nonce and sig):
        raise ApiError(401, "device_auth_missing", "Missing device authentication headers.")
    if len(nonce) > 64 or len(sig) != 64:
        raise ApiError(401, "device_auth_invalid", "Malformed device authentication headers.")
    try:
        ts_int = int(ts)
    except ValueError as e:
        raise ApiError(401, "device_auth_invalid", "Bad timestamp.") from e

    s = db()
    device = s.get(Device, device_id)
    if device is None:
        # Same work as a real check so unknown ids are not obvious by timing.
        hmac.compare_digest(sig, "0" * 64)
        raise ApiError(401, "device_unknown", "Unknown device.")

    secret = decrypt_secret(device.key_encrypted)
    expected = sign(secret, request.method, _path_with_query(), ts, nonce, request.get_data(cache=True))
    if not hmac.compare_digest(sig.lower(), expected):
        raise ApiError(401, "device_bad_signature", "Signature does not match.")

    now = utcnow()
    unsynced = ts_int < UNSYNCED_BEFORE
    if not unsynced and abs(now.timestamp() - ts_int) > MAX_SKEW_S:
        raise ApiError(401, "device_clock_skew", "Timestamp is more than 120 s off.")

    # Replay protection: a nonce may be used once in 10 minutes.
    try:
        with s.begin_nested():
            s.add(DeviceNonce(device_id=device_id, nonce=nonce.lower(), seen_at=now))
    except IntegrityError as e:
        raise ApiError(401, "device_replay", "Nonce already used.") from e
    return DeviceContext(device=device, time_unsynced=unsynced)


def purge_nonces() -> int:
    res = db().execute(delete(DeviceNonce).where(DeviceNonce.seen_at < utcnow() - NONCE_TTL))
    return res.rowcount or 0


def device_auth_required(fn: Callable) -> Callable:
    @wraps(fn)
    def wrapper(*args, **kwargs):
        g.device_ctx = verify_device_request()
        return fn(*args, **kwargs)

    return wrapper
