"""Unit test xác minh AppUI sử dụng controller đa luồng mới."""

from __future__ import annotations

import queue
from types import SimpleNamespace

from pathlib import Path

import sys

sys.path.append(str(Path(__file__).resolve().parents[2]))

import pytest

from APP.ui import app_ui


class DummyAnalysisController:
    """Giả lập AnalysisController để theo dõi lời gọi."""

    def __init__(self) -> None:
        self.started: list[tuple[str, str]] = []
        self.stopped: list[str] = []

    def start_session(
        self,
        session_id: str,
        app,
        cfg,
        *,
        priority: str = "user",
        on_start=None,
    ) -> None:  # type: ignore[no-untyped-def]
        self.started.append((session_id, priority))
        if on_start:
            on_start(session_id, priority)

    def enqueue_autorun(self, session_id: str, app, cfg, *, on_start=None):  # type: ignore[no-untyped-def]
        self.started.append((session_id, "autorun"))
        if on_start:
            on_start(session_id, "autorun")
        return "started"

    def stop_session(self, session_id: str) -> None:
        self.stopped.append(session_id)


@pytest.fixture()
def dummy_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Tạo đối tượng AppUI rút gọn phục vụ test threading."""

    dummy_controller = DummyAnalysisController()

    app = app_ui.AppUI.__new__(app_ui.AppUI)
    app.is_running = False
    app.stop_flag = False
    app._current_session_id = None
    app._pending_session = False
    app._queued_autorun_session = None
    app.analysis_controller = dummy_controller
    app.ui_queue = queue.Queue()
    app.threading_manager = SimpleNamespace(submit_task=lambda *args, **kwargs: SimpleNamespace())
    app.run_config = None
    app._schedule_next_autorun = lambda: None
    app.autorun_var = SimpleNamespace(get=lambda: False)
    app.feature_flags = SimpleNamespace(use_new_threading_stack=True)
    app.use_new_threading_stack = True
    app.io_controller = SimpleNamespace(run=lambda **kwargs: None)
    app.mt5_controller = SimpleNamespace(connect=lambda *a, **k: None, check_status=lambda *a, **k: None, snapshot=lambda *a, **k: None)
    app.ui_backlog_warn_threshold = 50
    app._last_ui_backlog_log = 0.0

    # Stub các phương thức UI
    app.ui_status = lambda *_args, **_kwargs: None
    app.show_error_message = lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("Không mong đợi popup lỗi"))

    # Biến Tkinter được thay bằng SimpleNamespace để dễ kiểm soát
    folder_path = tmp_path / "images"
    folder_path.mkdir()
    app.folder_path = SimpleNamespace(get=lambda: str(folder_path), set=lambda value: None)

    # Snapshot config trả về object giả
    dummy_cfg = object()
    app._snapshot_config = lambda: dummy_cfg
    app._update_services_config = lambda: None

    monkeypatch.setattr(app_ui.ui_builder, "toggle_controls_state", lambda *_args, **_kwargs: None)

    return app, dummy_controller


def test_start_analysis_uses_controller(dummy_app):
    app, controller = dummy_app

    app.start_analysis()

    assert app.is_running is True
    assert app._current_session_id is not None
    assert controller.started
    session_id, priority = controller.started[0]
    assert priority == "user"
    assert app.run_config is not None
    assert session_id.startswith("manual-")


def test_stop_analysis_calls_controller(dummy_app):
    app, controller = dummy_app
    app.is_running = True
    app._current_session_id = "manual-999"

    app.stop_analysis()

    assert app.stop_flag is True
    assert controller.stopped == ["manual-999"]
