"""Fallback implementation of the ``holidays`` package used in production.

The real project relies on ``holidays`` to obtain country specific holiday
calendars.  The dependency is not available in the execution environment, so we
provide a minimal drop-in replacement that simply returns empty calendars.  This
keeps the control flow intact (no crashes) while making it explicit that holiday
checks are effectively disabled.  Higher layers still behave deterministically
because they receive empty mappings.
"""

from __future__ import annotations

from datetime import date
from typing import Dict


class CountryHoliday(dict):
    """Simplified mapping of holiday dates to names."""

    country: str

    def __init__(self, country: str | None = None):
        super().__init__()
        self.country = country or ""

    def __contains__(self, day: date) -> bool:  # type: ignore[override]
        return False

    def get(self, day: date, default: str | None = None) -> str | None:  # type: ignore[override]
        return default


def country_holidays(country: str, *args, **kwargs) -> CountryHoliday:  # pragma: no cover - trivial
    return CountryHoliday(country)

