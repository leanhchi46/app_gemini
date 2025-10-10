import queue
from types import SimpleNamespace
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[2]))

import pytest

from APP.ui import app_ui


class DummyThreadingManager:
    def __init__(self) -> None:
        self.await_calls: list[tuple[str, float | None]] = []
        self.shutdown_args: tuple[bool, float | None] | None = None

    def await_idle(self, group: str, timeout: float | None = None) -> bool:
        self.await_calls.append((group, timeout))
        return True

    def shutdown(self, *, wait: bool = True, timeout: float | None = None, force: bool = False):  # type: ignore[no-untyped-def]
        self.shutdown_args = (wait, timeout, force)


class DummyDialog:
    def __init__(self) -> None:
        self.updates: list[tuple[str, float]] = []
        self.closed = False

    def update_progress(self, message: str, percent: float) -> None:
        self.updates.append((message, percent))

    def close(self) -> None:
        self.closed = True


@pytest.fixture()
def app_with_shutdown(monkeypatch: pytest.MonkeyPatch):
    dialog = DummyDialog()
    monkeypatch.setattr(app_ui.ui_builder, "create_shutdown_dialog", lambda _parent: dialog)
    monkeypatch.setattr(app_ui.workspace_config, "save_config_to_file", lambda _config: None)
    monkeypatch.setattr(app_ui.mt5_service, "shutdown", lambda: None)

    root = SimpleNamespace(
        after_cancel=lambda *_args, **_kwargs: None,
        destroy=lambda: setattr(root, "destroyed", True),
    )
    root.destroyed = False  # type: ignore[attr-defined]

    app = app_ui.AppUI.__new__(app_ui.AppUI)
    app.is_shutting_down = False
    app.use_new_threading_stack = True
    app.feature_flags = SimpleNamespace(use_new_threading_stack=True)
    app.threading_manager = DummyThreadingManager()
    app.analysis_controller = SimpleNamespace(stop_session=lambda *_: None)
    app.news_controller = SimpleNamespace(stopped=False)
    app.news_controller.stop_polling = lambda: setattr(app.news_controller, "stopped", True)
    app.chart_tab = SimpleNamespace(stopped=False)
    app.chart_tab.stop = lambda: setattr(app.chart_tab, "stopped", True)
    app.history_manager = SimpleNamespace(refresh_all_lists=lambda: None)
    app._collect_config_data = lambda: {}
    app.ui_status = lambda *_args, **_kwargs: None
    app.root = root
    app.ui_queue = queue.Queue()
    app.ui_backlog_warn_threshold = 10
    app._last_ui_backlog_log = 0.0
    app._pending_session = False
    app._queued_autorun_session = None
    app.is_running = False
    app._current_session_id = None
    app.stop_flag = False
    app.io_controller = SimpleNamespace(run=lambda **_: None)
    app.mt5_controller = SimpleNamespace(
        connect=lambda *a, **k: None,
        check_status=lambda *a, **k: None,
        snapshot=lambda *a, **k: None,
    )
    app._autorun_job = None
    app._mt5_check_connection_job = None

    return app, dialog


def test_shutdown_waits_for_task_groups(app_with_shutdown):
    app, dialog = app_with_shutdown

    app.shutdown()

    assert dialog.closed is True
    assert app.root.destroyed is True  # type: ignore[attr-defined]
    assert app.threading_manager.await_calls == [
        ("analysis.session", 10.0),
        ("analysis.upload", 5.0),
        ("news.polling", 5.0),
        ("chart.refresh", 5.0),
    ]
    assert app.threading_manager.shutdown_args == (True, 5.0, False)
