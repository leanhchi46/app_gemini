# -*- coding: utf-8 -*-
"""Unit test cho NewsController."""

from __future__ import annotations

import queue

from concurrent.futures import Future
from pathlib import Path
from typing import Callable

import sys

sys.path.append(str(Path(__file__).resolve().parents[2]))

import pytest

from APP.ui.controllers.news_controller import NewsController
from APP.utils.threading_utils import CancelToken, TaskRecord


class DummyThreadingManager:
    """Mock ThreadingManager để quan sát submit/cancel."""

    def __init__(self) -> None:
        self.submitted: list[dict] = []
        self.cancelled: list[str] = []

    def new_cancel_token(self) -> CancelToken:
        return CancelToken()

    def submit(self, **kwargs):  # type: ignore[no-untyped-def]
        future: Future = Future()
        result = kwargs["func"](*kwargs.get("args", ()), cancel_token=kwargs["cancel_token"])
        future.set_result(result)
        record = TaskRecord(
            future=future,
            token=kwargs["cancel_token"],
            name=kwargs.get("name", ""),
            group=kwargs.get("group", ""),
            metadata=kwargs.get("metadata", {}),
        )
        self.submitted.append({"kwargs": kwargs, "record": record})
        return record

    def cancel_group(self, group: str) -> None:
        self.cancelled.append(group)


class StubNewsService:
    """Stub NewsService chỉ ghi nhận tham số refresh."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def get_timeout_sec(self) -> int:
        return 5

    def refresh(self, *, threading_manager, cancel_token, priority, timeout_sec, force):  # type: ignore[no-untyped-def]
        self.calls.append({
            "priority": priority,
            "timeout": timeout_sec,
            "force": force,
        })
        return {"events": [], "source": "network", "priority": priority, "ttl": 60, "latency_sec": 0.1}


@pytest.fixture()
def dummy_tm() -> DummyThreadingManager:
    return DummyThreadingManager()


@pytest.fixture()
def stub_service() -> StubNewsService:
    return StubNewsService()


@pytest.fixture()
def ui_queue() -> "queue.Queue[Callable[[], None]]":
    return queue.Queue()


def test_start_polling_triggers_autorun(dummy_tm: DummyThreadingManager, stub_service: StubNewsService, ui_queue: "queue.Queue[Callable[[], None]]") -> None:
    controller = NewsController(threading_manager=dummy_tm, news_service=stub_service, ui_queue=ui_queue, backlog_limit=5)
    controller.start_polling(lambda payload: None)
    assert dummy_tm.submitted[0]["kwargs"]["metadata"]["priority"] == "autorun"
    assert stub_service.calls[0]["priority"] == "autorun"


def test_backlog_blocks_autorun(dummy_tm: DummyThreadingManager, stub_service: StubNewsService, ui_queue: "queue.Queue[Callable[[], None]]") -> None:
    controller = NewsController(threading_manager=dummy_tm, news_service=stub_service, ui_queue=ui_queue, backlog_limit=1)
    controller.start_polling(lambda payload: None)
    dummy_tm.submitted.clear()
    ui_queue.put(lambda: None)
    ui_queue.put(lambda: None)
    controller.trigger_autorun()
    assert dummy_tm.submitted == []


def test_refresh_now_cancels_existing_tasks(dummy_tm: DummyThreadingManager, stub_service: StubNewsService, ui_queue: "queue.Queue[Callable[[], None]]") -> None:
    controller = NewsController(threading_manager=dummy_tm, news_service=stub_service, ui_queue=ui_queue, backlog_limit=5)
    controller.start_polling(lambda payload: None)
    dummy_tm.submitted.clear()
    controller.refresh_now()
    assert dummy_tm.cancelled[-1] == NewsController.GROUP_NAME
    assert dummy_tm.submitted[0]["kwargs"]["metadata"]["priority"] == "user"
