"""Append-only audit trail (FR-SEC-03, C-9)."""
from __future__ import annotations

from typing import Any

from flask import g, has_request_context

from ..db import db
from ..models import AuditLog
from ..timeutil import utcnow


def audit(action: str, target: str | None = None, before: Any = None, after: Any = None, user_id: int | None = None) -> None:
    ip = None
    if has_request_context():
        from ..security import client_ip

        ip = client_ip()
        if user_id is None and getattr(g, "user", None) is not None:
            user_id = g.user.user_id
    db().add(
        AuditLog(
            user_id=user_id,
            action=action,
            target=target,
            before_json=_jsonable(before),
            after_json=_jsonable(after),
            ip=ip,
            at=utcnow(),
        )
    )


def _jsonable(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    if isinstance(v, (str, int, float, bool)):
        return v
    if hasattr(v, "isoformat"):
        from ..timeutil import iso

        return iso(v)
    return str(v)
