"""Vercel Cron / external scheduler entry points.

Vercel sends `Authorization: Bearer $CRON_SECRET`. Without CRON_SECRET set these
endpoints are disabled (404), so nobody can trigger jobs anonymously.
"""
from __future__ import annotations

import hmac

from flask import Blueprint, current_app, jsonify, request

from ..errors import ApiError
from ..services import jobs
from ..timeutil import iso, utcnow

bp = Blueprint("cron", __name__, url_prefix="/api/cron")


def _check():
    secret = current_app.config["GK"].cron_secret
    if not secret:
        raise ApiError(404, "not_found", "Cron endpoints are disabled (set CRON_SECRET).")
    sent = request.headers.get("Authorization", "")
    if not hmac.compare_digest(sent, f"Bearer {secret}"):
        raise ApiError(401, "unauthorized", "Bad cron secret.")


@bp.get("/due")
def run_due():
    _check()
    now = utcnow()
    names = tuple(jobs.JOBS.keys())
    return jsonify({"ran": jobs.run_due(now, names), "at": iso(now)})


@bp.get("/<name>")
def run_one(name: str):
    _check()
    if name not in jobs.JOBS:
        raise ApiError(404, "unknown_job", "Unknown job.")
    now = utcnow()
    return jsonify({"job": name, "result": jobs.run_job(name, now), "at": iso(now)})
