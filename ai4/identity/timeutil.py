"""UTC timestamps for identity records. Caller-supplied clock; no network time."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol

from ai4.identity.errors import IdentityError

TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


class Clock(Protocol):
    def now(self) -> datetime:
        """Return an aware UTC datetime."""


class SystemClock:
    """Local process clock. Not NTP, not a remote time service."""

    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class FixedClock:
    """Deterministic clock for offline tests."""

    def __init__(self, when: datetime) -> None:
        self._when = require_aware_utc(when)

    def now(self) -> datetime:
        return self._when


def require_aware_utc(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise IdentityError("timestamp must be a datetime")
    if value.tzinfo is None:
        raise IdentityError("timestamps must be timezone-aware UTC")
    return value.astimezone(timezone.utc).replace(microsecond=0)


def format_utc(value: datetime | str) -> str:
    if isinstance(value, str):
        parse_utc(value)
        return value
    return require_aware_utc(value).strftime(TIMESTAMP_FORMAT)


def parse_utc(value: object) -> datetime:
    if not isinstance(value, str):
        raise IdentityError("timestamp must be an RFC 3339 UTC string")
    try:
        parsed = datetime.strptime(value, TIMESTAMP_FORMAT)
    except ValueError as exc:
        raise IdentityError(
            f"timestamp {value!r} must be RFC 3339 UTC second-precision with Z"
        ) from exc
    return parsed.replace(tzinfo=timezone.utc)


def require_expiry_window(issued_at: str, expires_at: str) -> tuple[datetime, datetime]:
    issued = parse_utc(issued_at)
    expires = parse_utc(expires_at)
    if expires <= issued:
        raise IdentityError("expires_at must be strictly later than issued_at")
    return issued, expires


def is_expired(expires_at: str, *, now: datetime) -> bool:
    return require_aware_utc(now) >= parse_utc(expires_at)


def is_not_yet_valid(issued_at: str, *, now: datetime) -> bool:
    return require_aware_utc(now) < parse_utc(issued_at)
