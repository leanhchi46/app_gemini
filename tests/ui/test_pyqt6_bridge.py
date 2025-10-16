"""Kiểm thử các adapter PyQt6 ở giai đoạn 2."""

from __future__ import annotations

import logging
import queue

import pytest

PyQt6 = pytest.importorskip("PyQt6")
from PyQt6.QtCore import QCoreApplication  # type: ignore[attr-defined]

from APP.ui.pyqt6.event_bridge import QtThreadingAdapter, UiQueueBridge
from APP.utils.threading_utils import ThreadingManager


@pytest.fixture()
def core_app():
    app = QCoreApplication.instance() or QCoreApplication([])
    try:
        yield app
    finally:
        app.quit()
        while app and app.thread().isRunning():
            app.processEvents()


def test_ui_queue_bridge_executes_callbacks(core_app):
    bridge = UiQueueBridge(queue.Queue())
    called: list[str] = []

    bridge.post(lambda: called.append("ran"))
    processed = bridge.drain_once()

    assert processed == 1
    assert called == ["ran"]
    bridge.stop()


def test_ui_queue_bridge_warns_on_backlog(core_app, caplog):
    bridge = UiQueueBridge(queue.Queue(), warn_threshold=2, warn_interval_sec=0.0)

    with caplog.at_level(logging.WARNING):
        bridge.post(lambda: None)
        bridge.post(lambda: None)
        bridge.post(lambda: None)

    assert any("vượt ngưỡng cảnh báo" in record.message for record in caplog.records)


def test_ui_queue_bridge_drops_callbacks_when_threshold_exceeded(core_app, caplog):
    dropped: list[object] = []
    bridge = UiQueueBridge(queue.Queue(), drop_threshold=2, on_drop=lambda cb: dropped.append(cb))

    cb1 = lambda: None
    cb2 = lambda: None
    cb3 = lambda: None

    with caplog.at_level(logging.ERROR):
        assert bridge.post(cb1) is True
        assert bridge.post(cb2) is True
        assert bridge.post(cb3) is False

    assert bridge.queue.qsize() == 2
    assert dropped == [cb3]
    assert any("vượt ngưỡng loại bỏ" in record.message for record in caplog.records)


def test_threading_adapter_routes_results_to_ui(core_app):
    tm = ThreadingManager(max_workers=1)
    bridge = UiQueueBridge(queue.Queue())
    adapter = QtThreadingAdapter(tm, bridge)

    results: list[str] = []

    def _job() -> str:
        return "ok"

    adapter.submit(func=_job, group="test", name="job", on_result=lambda value: results.append(value))

    tm.await_idle(group="test", timeout=5)
    bridge.drain_once()

    assert results == ["ok"]
    bridge.stop()
    tm.shutdown(force=True)


def test_threading_adapter_routes_errors(core_app):
    tm = ThreadingManager(max_workers=1)
    bridge = UiQueueBridge(queue.Queue())
    adapter = QtThreadingAdapter(tm, bridge)

    errors: list[str] = []

    def _boom() -> None:
        raise ValueError("bad")

    record = adapter.submit(func=_boom, group="test", name="boom", on_error=lambda exc: errors.append(str(exc)))

    with pytest.raises(ValueError):
        record.future.result(timeout=5)

    bridge.drain_once()

    assert errors == ["bad"]
    bridge.stop()
    tm.shutdown(force=True)
