"""Kiểm thử tích hợp ThreadingManager với PyQt6 thông qua UiQueueBridge."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("PyQt6")

from APP.ui.pyqt6.controller_bridge import ControllerSet
from APP.ui.pyqt6.main_window import TradingMainWindow


@contextmanager
def make_window(config_state, harness, **kwargs):
    """Dựng TradingMainWindow với adapter Qt thật và tự động dọn dẹp."""

    window = TradingMainWindow(config_state, harness.adapter, harness.bridge, **kwargs)
    try:
        harness.pump_events()
        yield window
    finally:
        try:
            window._autorun_timer.stop()
        except Exception:
            pass
        window.close()
        harness.pump_events()


def test_manual_analysis_updates_log(qapp, config_state, pyqt_threading_adapter) -> None:
    """Phiên phân tích mock chạy qua ThreadingManager vẫn cập nhật log/status."""

    harness = pyqt_threading_adapter
    with make_window(config_state, harness) as window:
        window._handle_manual_analysis()
        harness.await_idle(group="analysis")
        log_text = window.overview_tab.log_view.toPlainText()
        assert "Hoàn tất phiên phân tích" in log_text
        assert "Đã hoàn thành phiên phân tích" in window.statusBar().currentMessage()


def test_news_refresh_dispatches_through_threading_manager(
    qapp, config_state, pyqt_threading_adapter
) -> None:
    """Job lấy tin tức giả lập được xử lý qua ThreadingManager và phản ánh lên UI."""

    harness = pyqt_threading_adapter
    with make_window(config_state, harness) as window:
        window._handle_news_refresh()
        harness.await_idle(group="news")
        assert window.news_tab.table.rowCount() == 3
        assert "Đã cập nhật tin tức" in window.statusBar().currentMessage()


def test_upload_group_callbacks_update_ui(qapp, config_state, pyqt_threading_adapter) -> None:
    """Callback của group analysis.upload phải chạy trên thread UI thông qua bridge."""

    harness = pyqt_threading_adapter
    with make_window(config_state, harness) as window:
        def _on_result(result: str) -> None:
            window.overview_tab.set_status(f"Upload {result}", running=False)
            window.overview_tab.append_log(f"[UPLOAD] {result}")

        harness.adapter.submit(
            func=lambda: "cache-hit",
            group="analysis.upload",
            name="analysis.upload.cache_test",
            on_result=_on_result,
        )
        harness.await_idle(group="analysis.upload")
        log_text = window.overview_tab.log_view.toPlainText()
        assert "[UPLOAD] cache-hit" in log_text
        assert "Upload cache-hit" in window.overview_tab.status_label.text()


class AutorunControllerStub:
    """Giả lập AnalysisController.enqueue_autorun phát callback qua Qt adapter."""

    def __init__(self, harness) -> None:
        self.harness = harness
        self.calls: list[str] = []

    def enqueue_autorun(self, session_id: str, app: Any, cfg: Any, *, on_start=None) -> str:
        self.calls.append(session_id)
        if on_start:
            self.harness.adapter.submit(
                func=lambda: None,
                group="analysis",
                name="analysis.autorun.stub",
                on_result=lambda _: on_start(session_id, "autorun"),
            )
        return "started"

    def start_session(self, *args, **kwargs):  # pragma: no cover - không dùng ở đây
        raise AssertionError("Không mong đợi start_session trong autorun stub")


def test_autorun_session_emits_start_signal(qapp, config_state, pyqt_threading_adapter) -> None:
    """Autorun sử dụng controller stub vẫn phát log/status thông qua UiQueueBridge."""

    harness = pyqt_threading_adapter
    stub = AutorunControllerStub(harness)
    controllers = ControllerSet(analysis=stub)

    with make_window(config_state, harness, controllers=controllers) as window:
        Path(config_state.folder.folder).mkdir(parents=True, exist_ok=True)
        window._autorun_enabled = True
        window._autorun_interval = 1
        window._handle_autorun_timeout()
        harness.await_idle(group="analysis")

    assert stub.calls
    log_lines = window.overview_tab.log_view.toPlainText().splitlines()
    assert any("autorun" in line.lower() for line in log_lines)
    assert "autorun" in window.statusBar().currentMessage().lower()
