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
        self.started: list[tuple[str, object, object]] = []
        self.stopped: list[str] = []

    def start_session(self, session_id: str, app, cfg) -> None:  # type: ignore[no-untyped-def]
        self.started.append((session_id, app, cfg))

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
    app.analysis_controller = dummy_controller
    app.ui_queue = queue.Queue()
    app.threading_manager = None
    app.run_config = None
    app._schedule_next_autorun = lambda: None
    app.autorun_var = SimpleNamespace(get=lambda: False)

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
    session_id, session_app, cfg = controller.started[0]
    assert session_app is app
    assert cfg is app.run_config
    assert session_id.startswith("manual-")


def test_stop_analysis_calls_controller(dummy_app):
    app, controller = dummy_app
    app.is_running = True
    app._current_session_id = "manual-999"

    app.stop_analysis()

    assert app.stop_flag is True
    assert controller.stopped == ["manual-999"]
