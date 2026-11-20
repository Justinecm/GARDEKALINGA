"""Runtime configuration, read once from environment variables.

Every secret comes from the environment (.env locally, Project Settings on Vercel).
See .env.example for the full list.
"""
from __future__ import annotations

import base64
import hashlib
import os
from dataclasses import dataclass, field


def _bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


@dataclass
class Settings:
    secret_key: str
    database_url: str
    device_key_enc_key: str
    owm_api_key: str
    cron_secret: str
    demo_mode: bool
    legacy_device_api: bool
    cookie_secure: bool
    on_vercel: bool
    auto_create_tables: bool
    command_ttl_s: int = 60
    offline_after_s: int = 15
    tz: str = "Asia/Manila"
    warnings: list[str] = field(default_factory=list)


def load_settings(overrides: dict | None = None) -> Settings:
    env = dict(os.environ)
    if overrides:
        env.update({k: str(v) for k, v in overrides.items()})

    def get(name: str, default: str = "") -> str:
        return env.get(name, default) or default

    on_vercel = bool(get("VERCEL"))
    demo = get("GK_DEMO_MODE", "").lower() in {"1", "true", "yes", "on"}
    warnings: list[str] = []

    database_url = get("DATABASE_URL")
    if not database_url:
        if demo or not on_vercel:
            # Demo / local development: a SQLite file. On Vercel only /tmp is writable,
            # and it is per instance, so demo data can reset after a cold start.
            path = "/tmp/gardekalinga-demo.db" if on_vercel else os.path.abspath("gardekalinga-dev.db")
            database_url = f"sqlite:///{path}"
            warnings.append("DATABASE_URL not set: using SQLite at " + path)
        else:
            raise RuntimeError("DATABASE_URL is required in production. See docs/DEPLOY.md.")

    secret_key = get("SECRET_KEY")
    if not secret_key:
        if demo or not on_vercel:
            seed = get("VERCEL_PROJECT_ID") or get("VERCEL_URL") or "gardekalinga-local-dev"
            secret_key = hashlib.sha256(("gk-demo::" + seed).encode()).hexdigest()
            warnings.append("SECRET_KEY not set: using a derived development key. Set SECRET_KEY before real use.")
        else:
            raise RuntimeError("SECRET_KEY is required in production.")

    enc_key = get("DEVICE_KEY_ENC_KEY")
    if not enc_key:
        # Derive a Fernet key from SECRET_KEY so demo and local runs work.
        enc_key = base64.urlsafe_b64encode(hashlib.sha256(("fernet::" + secret_key).encode()).digest()).decode()
        if not demo and on_vercel:
            warnings.append("DEVICE_KEY_ENC_KEY not set: derived from SECRET_KEY.")

    return Settings(
        secret_key=secret_key,
        database_url=database_url,
        device_key_enc_key=enc_key,
        owm_api_key=get("OWM_API_KEY"),
        cron_secret=get("CRON_SECRET"),
        demo_mode=demo,
        legacy_device_api=get("GK_LEGACY_DEVICE_API", "").lower() in {"1", "true", "yes", "on"},
        cookie_secure=get("SESSION_COOKIE_SECURE", "true" if on_vercel else "false").lower() in {"1", "true", "yes", "on"},
        on_vercel=on_vercel,
        auto_create_tables=get("GK_AUTO_CREATE_TABLES", "true" if (demo or database_url.startswith("sqlite")) else "false").lower()
        in {"1", "true", "yes", "on"},
        command_ttl_s=int(get("GK_COMMAND_TTL_S", "60")),
        offline_after_s=int(get("GK_OFFLINE_AFTER_S", "15")),
        warnings=warnings,
    )


__all__ = ["Settings", "load_settings", "_bool", "_int"]
