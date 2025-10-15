"""Lightweight fallback for the pytz module using zoneinfo.

This project expects ``pytz`` to be available, but the dependency cannot be
installed inside the execution environment.  We emulate the limited subset of
APIs used in the codebase: ``utc``, ``timezone`` and the ``UnknownTimeZoneError``
exception together with ``localize``/``astimezone`` helpers so the rest of the
application can continue to work using the standard library ``zoneinfo``
implementation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class UnknownTimeZoneError(KeyError):
    """Exception raised when a timezone cannot be located."""


class _ZoneInfoWrapper:
    def __init__(self, zone: ZoneInfo):
        self._zone = zone

    @property
    def key(self) -> str:
        return getattr(self._zone, "key", str(self._zone))

    def localize(self, dt: datetime, is_dst: bool | None = None) -> datetime:
        if dt.tzinfo is not None:
            return dt.astimezone(self._zone)
        return dt.replace(tzinfo=self._zone)

    def normalize(self, dt: datetime) -> datetime:
        return dt.astimezone(self._zone)

    def __getattr__(self, item):
        return getattr(self._zone, item)


class _UTCProxy(_ZoneInfoWrapper):
    def __init__(self):
        super().__init__(timezone.utc)

    def localize(self, dt: datetime, is_dst: bool | None = None) -> datetime:
        if dt.tzinfo is not None:
            return dt.astimezone(timezone.utc)
        return dt.replace(tzinfo=timezone.utc)


def timezone_(name: str) -> _ZoneInfoWrapper:
    try:
        return _ZoneInfoWrapper(ZoneInfo(name))
    except ZoneInfoNotFoundError as exc:  # pragma: no cover - parity with pytz
        raise UnknownTimeZoneError(name) from exc


utc = _UTCProxy()
timezone = timezone_

