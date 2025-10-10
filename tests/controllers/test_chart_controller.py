# -*- coding: utf-8 -*-
"""Unit test cho ChartController đảm bảo tích hợp ThreadingManager mới."""

from __future__ import annotations
# -*- coding: utf-8 -*-
"""Unit test cho ChartController đảm bảo tích hợp ThreadingManager mới."""

import queue

from concurrent.futures import Future
from pathlib import Path
from typing import Callable

import sys

sys.path.append(str(Path(__file__).resolve().parents[2]))

import pytest

from APP.ui.controllers.chart_controller import ChartController, ChartStreamConfig
from APP.utils.threading_utils import CancelToken, TaskRecord


class DummyThreadingManager:
    """Giả lập ThreadingManager để kiểm soát submit/cancel trong unit test."""

    def __init__(self) -> None:
        self.submitted: list[dict] = []
        self.cancelled: list[str] = []

    def new_cancel_token(self) -> CancelToken:
        return CancelToken()

    def submit(self, **kwargs):  # type: ignore[no-untyped-def]
        future: Future = Future()
        future.set_result({"dummy": True})
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


@pytest.fixture()
def dummy_tm() -> DummyThreadingManager:
    return DummyThreadingManager()


@pytest.fixture()
def ui_queue() -> "queue.Queue[Callable[[], None]]":
    return queue.Queue()


def test_start_stream_submits_tasks_with_metadata(
    dummy_tm: DummyThreadingManager, ui_queue: "queue.Queue[Callable[[], None]]"
) -> None:
    controller = ChartController(threading_manager=dummy_tm, ui_queue=ui_queue, backlog_limit=5)
    config = ChartStreamConfig(symbol="XAUUSD", timeframe="M15", candles=120, chart_type="Nến")

    controller.start_stream(
        config=config,
        info_worker=lambda *_args, **_kwargs: {"ok": True},
        chart_worker=lambda *_args, **_kwargs: {"success": True},
        on_info_done=lambda payload: None,
        on_chart_done=lambda payload: None,
    )

    # Gọi force refresh sẽ khiến submit chạy hai lần (info + chart)
    assert len(dummy_tm.submitted) == 2
    for call in dummy_tm.submitted:
        kwargs = call["kwargs"]
        assert kwargs["group"] == "chart.refresh"
        assert kwargs["timeout"] == 10.0
        assert kwargs["metadata"]["symbol"] == "XAUUSD"


def test_trigger_refresh_respects_backlog(
    dummy_tm: DummyThreadingManager, ui_queue: "queue.Queue[Callable[[], None]]"
) -> None:
    controller = ChartController(threading_manager=dummy_tm, ui_queue=ui_queue, backlog_limit=1)
    config = ChartStreamConfig(symbol="XAUUSD", timeframe="M1", candles=60, chart_type="Nến")
    controller.start_stream(
        config=config,
        info_worker=lambda *_args, **_kwargs: {"ok": True},
        chart_worker=lambda *_args, **_kwargs: {"success": True},
        on_info_done=lambda payload: None,
        on_chart_done=lambda payload: None,
    )
    dummy_tm.submitted.clear()

    # backlog vượt ngưỡng → không submit mới
    ui_queue.put(lambda: None)
    ui_queue.put(lambda: None)
    controller.trigger_refresh()
    assert dummy_tm.submitted == []

    # Force refresh bỏ qua backlog guard
    ui_queue.queue.clear()
    controller.trigger_refresh(force=True)
    assert len(dummy_tm.submitted) == 2


def test_stop_stream_cancels_group(
    dummy_tm: DummyThreadingManager, ui_queue: "queue.Queue[Callable[[], None]]"
) -> None:
    controller = ChartController(threading_manager=dummy_tm, ui_queue=ui_queue, backlog_limit=5)
    config = ChartStreamConfig(symbol="XAUUSD", timeframe="M5", candles=90, chart_type="Đường")
    controller.start_stream(
        config=config,
        info_worker=lambda *_args, **_kwargs: {"ok": True},
        chart_worker=lambda *_args, **_kwargs: {"success": True},
        on_info_done=lambda payload: None,
        on_chart_done=lambda payload: None,
    )
    controller.stop_stream()
    assert dummy_tm.cancelled == ["chart.refresh"]
