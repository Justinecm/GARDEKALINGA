"""Health checks (no auth): /api/health (process up) and /api/ready (database)."""
from __future__ import annotations

from flask import Blueprint, current_app, jsonify
from sqlalchemy import text

from ..db import db
from ..timeutil import iso, utcnow

bp = Blueprint("health", __name__)


@bp.get("/api/health")
def health():
    return jsonify({"ok": True, "service": "gardekalinga-api", "time": iso(utcnow())})


@bp.get("/api/ready")
def ready():
    try:
        db().execute(text("SELECT 1"))
        db_ok = True
    except Exception:  # pragma: no cover
        db_ok = False
    cfg = current_app.config["GK"]
    body = {"ok": db_ok, "database": db_ok, "weather_key": bool(cfg.owm_api_key)}
    return jsonify(body), (200 if db_ok else 503)
