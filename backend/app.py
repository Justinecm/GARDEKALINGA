"""Flask application factory.

Used by: Vercel (api/index.py), gunicorn in Docker (backend.app:create_app()),
the worker, the CLI and the tests.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from flask import Flask, g, request

from .config import load_settings
from .db import Base, SessionLocal, get_engine, init_engine
from .errors import register_error_handlers


def create_app(overrides: dict | None = None) -> Flask:
    cfg = load_settings(overrides)
    app = Flask(__name__, static_folder=None)
    app.config.update(
        GK=cfg,
        SECRET_KEY=cfg.secret_key,
        SESSION_COOKIE_NAME="gk_session",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SECURE=cfg.cookie_secure,
        SESSION_COOKIE_SAMESITE="Strict",
        PERMANENT_SESSION_LIFETIME=timedelta(days=7),  # rolling; 30-day absolute in security.py
        SESSION_REFRESH_EACH_REQUEST=True,
        MAX_CONTENT_LENGTH=512 * 1024,
        JSON_SORT_KEYS=False,
    )
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    for w in cfg.warnings:
        app.logger.warning(w)

    init_engine(cfg.database_url, serverless=cfg.on_vercel)
    if cfg.auto_create_tables:
        from . import models  # noqa: F401

        Base.metadata.create_all(get_engine())

    register_error_handlers(app)

    from .blueprints import admin, auth, control, cron, dashboard, device, health, model, reports, settings, users

    for bp in (health.bp, auth.bp, dashboard.bp, control.bp, settings.bp, users.bp, model.bp, reports.bp, admin.bp,
               device.bp, device.legacy_bp, cron.bp):
        app.register_blueprint(bp)

    @app.after_request
    def _commit_and_headers(resp):
        s = SessionLocal()
        try:
            if resp.status_code < 400 or getattr(g, "commit_on_error", False):
                s.commit()
            else:
                s.rollback()
        except Exception:  # pragma: no cover - surfaced as 500 by the error handler
            s.rollback()
            raise
        # Security headers (Caddy adds the same on Docker; vercel.json on Vercel).
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        if request.path.startswith("/api/"):
            resp.headers.setdefault("Cache-Control", "no-store")
        return resp

    @app.teardown_appcontext
    def _remove_session(_exc):
        SessionLocal.remove()

    return app
