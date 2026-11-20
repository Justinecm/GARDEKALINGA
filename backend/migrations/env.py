"""Alembic environment. Uses DATABASE_URL (the migration user, which has DDL rights)."""
import os

from alembic import context
from sqlalchemy import create_engine, pool

from backend import models  # noqa: F401  (registers the tables)
from backend.db import Base, _normalize_url

target_metadata = Base.metadata


def _url() -> str:
    url = os.environ.get("MIGRATE_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("Set DATABASE_URL (or MIGRATE_DATABASE_URL) before running migrations.")
    return _normalize_url(url)


def run_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def run_online() -> None:
    args = {}
    if os.environ.get("DATABASE_SSL", "").lower() in {"1", "true", "yes", "on"} and _url().startswith("mysql"):
        import certifi

        args["ssl"] = {"ca": certifi.where()}
    engine = create_engine(_url(), poolclass=pool.NullPool, connect_args=args)
    with engine.connect() as conn:
        context.configure(connection=conn, target_metadata=target_metadata, render_as_batch=True, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_offline()
else:
    run_online()
