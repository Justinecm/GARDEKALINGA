"""Database engine and session handling (SQLAlchemy 2).

Works with MySQL 8.4 (the paper's database, via PyMySQL), and with SQLite for
local development and tests. Serverless-friendly: on Vercel the
engine uses NullPool so no idle connection outlives an invocation.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, scoped_session, sessionmaker
from sqlalchemy.pool import NullPool


class Base(DeclarativeBase):
    pass


_engine: Engine | None = None
SessionLocal = scoped_session(sessionmaker(autoflush=False, expire_on_commit=False))


def _normalize_url(url: str) -> str:
    # Accept plain mysql:// URLs from hosting dashboards and use PyMySQL.
    if url.startswith("mysql://"):
        return "mysql+pymysql://" + url[len("mysql://") :]
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://") :]
    if url.startswith("postgresql://") and "+" not in url.split("://", 1)[0]:
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


def init_engine(url: str, serverless: bool = False) -> Engine:
    global _engine
    url = _normalize_url(url)
    kwargs: dict = {"future": True}
    connect_args: dict = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    elif url.startswith("mysql"):
        connect_args["charset"] = "utf8mb4"
        # Managed MySQL (TiDB Cloud, Aiven, PlanetScale) needs TLS. DATABASE_SSL=true
        # verifies the server with the public CA bundle from certifi.
        if os.environ.get("DATABASE_SSL", "").lower() in {"1", "true", "yes", "on"}:
            import certifi

            connect_args["ssl"] = {"ca": certifi.where()}
        kwargs["pool_pre_ping"] = True
        kwargs["pool_recycle"] = 280
    if serverless:
        kwargs["poolclass"] = NullPool
    _engine = create_engine(url, connect_args=connect_args, **kwargs)

    if url.startswith("sqlite"):

        @event.listens_for(_engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _record):  # pragma: no cover - trivial
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.close()

    SessionLocal.configure(bind=_engine)
    return _engine


def get_engine() -> Engine:
    if _engine is None:
        raise RuntimeError("Database engine not initialised")
    return _engine


def db() -> Session:
    return SessionLocal()


@contextmanager
def session_scope() -> Iterator[Session]:
    s = SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
