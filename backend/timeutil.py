"""Time helpers. Store naive UTC; show Asia/Manila (UTC+8, no DST)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

try:
    MANILA = ZoneInfo("Asia/Manila")
except Exception:  # pragma: no cover - tzdata missing on a minimal image
    MANILA = timezone(timedelta(hours=8), "Asia/Manila")  # type: ignore[assignment]


def utcnow() -> datetime:
    n = datetime.now(timezone.utc).replace(tzinfo=None)
    return n.replace(microsecond=(n.microsecond // 1000) * 1000)


def to_naive_utc(dt: datetime) -> datetime:
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    v = value.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    dt = datetime.fromisoformat(v)
    return to_naive_utc(dt)


def iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = to_naive_utc(dt)
    return dt.replace(microsecond=(dt.microsecond // 1000) * 1000).isoformat(timespec="milliseconds") + "Z"


def to_manila(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc).astimezone(MANILA)


def manila_to_utc(dt_local: datetime) -> datetime:
    if dt_local.tzinfo is None:
        dt_local = dt_local.replace(tzinfo=MANILA)
    return dt_local.astimezone(timezone.utc).replace(tzinfo=None)


def manila_day(dt: datetime) -> str:
    return to_manila(dt).strftime("%Y-%m-%d")


def floor_half_hour(dt: datetime) -> datetime:
    return dt.replace(minute=0 if dt.minute < 30 else 30, second=0, microsecond=0)


def floor_hour(dt: datetime) -> datetime:
    return dt.replace(minute=0, second=0, microsecond=0)
