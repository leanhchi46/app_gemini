"""Lightweight fallback for the pytz module using zoneinfo.

This project expects ``pytz`` to be available, but the dependency cannot be
installed inside the execution environment.  We emulate the limited subset of
APIs used in the codebase: ``utc``, ``timezone`` and the ``UnknownTimeZoneError``
exception together with ``localize``/``astimezone`` helpers so the rest of the
application can continue to work using the standard library ``zoneinfo``
implementation.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class UnknownTimeZoneError(KeyError):
    """Exception raised when a timezone cannot be located."""


class _ZoneInfoWrapper(ZoneInfo):
    """Thin wrapper around :class:`zoneinfo.ZoneInfo` with pytz helpers."""

    def __new__(cls, key: str):
        try:
            return super().__new__(cls, key)
        except ZoneInfoNotFoundError as exc:  # pragma: no cover - parity with pytz
            raise UnknownTimeZoneError(key) from exc

    @property
    def key(self) -> str:
        try:
            return super().key  # type: ignore[attr-defined]
        except AttributeError:  # pragma: no cover - defensive
            return str(self)

    def localize(self, dt: datetime, is_dst: bool | None = None) -> datetime:
        if dt.tzinfo is not None:
            return dt.astimezone(self)
        return dt.replace(tzinfo=self)

    def normalize(self, dt: datetime) -> datetime:
        return dt.astimezone(self)


class _UTCProxy(_ZoneInfoWrapper):
    def __new__(cls):
        return super().__new__(cls, "UTC")


def timezone(name: str) -> _ZoneInfoWrapper:
    return _ZoneInfoWrapper(name)


utc = _UTCProxy()


