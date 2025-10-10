# -*- coding: utf-8 -*-
"""Cấu hình chung cho pytest (bao gồm stub pytz khi môi trường không có)."""

from __future__ import annotations

import sys
from datetime import timedelta, tzinfo
from types import SimpleNamespace


class _UTCStub(tzinfo):
    """Stub tzinfo mô phỏng pytz.UTC."""

    def utcoffset(self, dt):  # type: ignore[override]
        return timedelta(0)

    def tzname(self, dt):  # type: ignore[override]
        return "UTC"

    def dst(self, dt):  # type: ignore[override]
        return timedelta(0)

    # Phương thức tương thích với pytz
    def localize(self, dt):
        return dt.replace(tzinfo=self)

    def normalize(self, dt):
        return dt


def _timezone_stub(_name: str) -> _UTCStub:
    return _UTCStub()


if "pytz" not in sys.modules:  # pragma: no cover - phụ thuộc môi trường
    sys.modules["pytz"] = SimpleNamespace(utc=_UTCStub(), timezone=_timezone_stub)


class _InvestPyStub:
    def economic_calendar(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        return []


if "investpy" not in sys.modules:  # pragma: no cover
    sys.modules["investpy"] = _InvestPyStub()


class _PandasStub:
    class DataFrame:  # type: ignore[too-few-public-methods]
        pass


if "pandas" not in sys.modules:  # pragma: no cover
    sys.modules["pandas"] = _PandasStub()


class _TradingEconomicsStub:
    class Calendar:
        def __init__(self):
            pass


if "tradingeconomics" not in sys.modules:  # pragma: no cover
    sys.modules["tradingeconomics"] = _TradingEconomicsStub()


class _GenAIStub:
    def get_file(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        return None

    def delete_file(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        return None


if "google.generativeai" not in sys.modules:  # pragma: no cover
    sys.modules["google.generativeai"] = _GenAIStub()
if "google" not in sys.modules:  # pragma: no cover
    google_pkg = type("GooglePkg", (), {})()
    setattr(google_pkg, "generativeai", sys.modules["google.generativeai"])
    sys.modules["google"] = google_pkg
if "google.generativeai.client" not in sys.modules:  # pragma: no cover
    client_stub = type("ClientStub", (), {"configure": lambda *args, **kwargs: None})()
    sys.modules["google.generativeai.client"] = client_stub
if "google.generativeai.generative_models" not in sys.modules:  # pragma: no cover
    gm_stub = type("GMStub", (), {"GenerativeModel": object})
    sys.modules["google.generativeai.generative_models"] = gm_stub
if "google.generativeai.models" not in sys.modules:  # pragma: no cover
    models_stub = type("ModelsStub", (), {"list_models": lambda *args, **kwargs: []})()
    sys.modules["google.generativeai.models"] = models_stub
if "google.api_core" not in sys.modules:  # pragma: no cover
    api_core_stub = type("APICore", (), {"exceptions": type("Exceptions", (), {})})()
    sys.modules["google.api_core"] = api_core_stub
    sys.modules["google.api_core.exceptions"] = api_core_stub.exceptions


class _MetaTraderStub:
    def __getattr__(self, name):  # type: ignore[no-untyped-def]
        raise AttributeError(name)


if "MetaTrader5" not in sys.modules:  # pragma: no cover
    sys.modules["MetaTrader5"] = _MetaTraderStub()


class _DotenvStub:
    def load_dotenv(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        return None


if "dotenv" not in sys.modules:  # pragma: no cover
    sys.modules["dotenv"] = _DotenvStub()


class _HolidaysStub:
    class CountryHoliday(dict):
        def __init__(self, *args, **kwargs):
            super().__init__()


if "holidays" not in sys.modules:  # pragma: no cover
    sys.modules["holidays"] = _HolidaysStub()
