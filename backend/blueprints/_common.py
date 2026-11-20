"""Shared helpers for dashboard routes."""
from __future__ import annotations

from datetime import datetime, timedelta

from flask import request

from ..errors import ApiError
from ..timeutil import parse_iso, utcnow


def time_range(default_hours: int = 24, max_days: int = 400) -> tuple[datetime, datetime]:
    now = utcnow()
    try:
        to = parse_iso(request.args.get("to")) or now
        frm = parse_iso(request.args.get("from")) or (to - timedelta(hours=default_hours))
    except ValueError as e:
        raise ApiError(422, "validation_error", "Dates must be ISO 8601.", {"from": "invalid"}) from e
    if frm >= to:
        raise ApiError(422, "validation_error", "'from' must be before 'to'.", {"from": "after_to"})
    if to - frm > timedelta(days=max_days):
        frm = to - timedelta(days=max_days)
    return frm, to


def int_arg(name: str, default: int, lo: int, hi: int) -> int:
    try:
        v = int(request.args.get(name, default))
    except (TypeError, ValueError):
        v = default
    return max(lo, min(hi, v))
