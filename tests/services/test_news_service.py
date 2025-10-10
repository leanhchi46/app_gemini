# -*- coding: utf-8 -*-
"""Unit test cho NewsService sau refactor đa luồng."""

from __future__ import annotations

from concurrent.futures import Future
from pathlib import Path

import sys

sys.path.append(str(Path(__file__).resolve().parents[2]))

import pytest

from APP.configs.app_config import NewsConfig
from APP.services.news_service import NewsService
from APP.utils.threading_utils import CancelToken, TaskRecord


class DummyThreadingManager:
    """Giả lập ThreadingManager để NewsService sử dụng trong test."""

    def __init__(self) -> None:
        self.submitted: list[dict] = []

    def new_cancel_token(self) -> CancelToken:
        return CancelToken()

    def submit(self, **kwargs):  # type: ignore[no-untyped-def]
        future: Future = Future()
        try:
            result = kwargs["func"](*kwargs.get("args", ()), cancel_token=kwargs["cancel_token"])
            future.set_result(result)
        except Exception as exc:  # pragma: no cover - test không đi vào nhánh này
            future.set_exception(exc)
        record = TaskRecord(
            future=future,
            token=kwargs["cancel_token"],
            name=kwargs.get("name", ""),
            group=kwargs.get("group", ""),
            metadata=kwargs.get("metadata", {}),
        )
        self.submitted.append({"kwargs": kwargs, "record": record})
        return record


@pytest.fixture()
def dummy_tm() -> DummyThreadingManager:
    return DummyThreadingManager()


def _make_service() -> NewsService:
    service = NewsService()
    service.news_config = NewsConfig(
        block_enabled=False,
        block_before_min=0,
        block_after_min=0,
        cache_ttl_sec=60,
        provider_timeout_sec=5,
    )

    class _StubFMP:
        def get_economic_calendar(self, days: int = 7):  # noqa: D401
            return [
                {"date": "01/01/2024", "time": "10:00", "event": "CPI", "zone": "US", "importance": "high"}
            ]

    service.fmp_service = _StubFMP()
    service.te_service = None
    return service


def test_refresh_uses_threading_manager_metadata(dummy_tm: DummyThreadingManager) -> None:
    service = _make_service()
    token = dummy_tm.new_cancel_token()
    payload = service.refresh(
        threading_manager=dummy_tm,
        cancel_token=token,
        priority="autorun",
        timeout_sec=5,
        force=True,
    )

    assert len(payload["events"]) == 1
    assert payload["source"] == "network"
    assert dummy_tm.submitted[0]["kwargs"]["group"] == "news.polling"
    assert dummy_tm.submitted[0]["kwargs"]["metadata"]["priority"] == "autorun"


def test_refresh_uses_cache_when_within_ttl(dummy_tm: DummyThreadingManager) -> None:
    service = _make_service()
    token = dummy_tm.new_cancel_token()
    service.refresh(
        threading_manager=dummy_tm,
        cancel_token=token,
        priority="autorun",
        timeout_sec=5,
        force=True,
    )
    dummy_tm.submitted.clear()

    cached_payload = service.refresh(
        threading_manager=dummy_tm,
        cancel_token=dummy_tm.new_cancel_token(),
        priority="autorun",
        timeout_sec=5,
        force=False,
    )

    assert cached_payload["source"] == "cache"
    assert dummy_tm.submitted == []
