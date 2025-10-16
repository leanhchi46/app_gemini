from __future__ import annotations

import json
import queue
from concurrent.futures import Future
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from contextlib import contextmanager

import pytest

PyQt6 = pytest.importorskip("PyQt6")
from PyQt6.QtWidgets import QApplication  # type: ignore[attr-defined]

from APP.configs.app_config import (
    ApiConfig,
    AutoTradeConfig,
    ChartConfig,
    ContextConfig,
    FMPConfig,
    FolderConfig,
    ImageProcessingConfig,
    MT5Config,
    NewsConfig,
    NoRunConfig,
    NoTradeConfig,
    PersistenceConfig,
    TEConfig,
    TelegramConfig,
    UploadConfig,
)
from APP.ui.pyqt6.controller_bridge import ControllerSet
from APP.ui.controllers.chart_controller import ChartStreamConfig
from APP.ui.pyqt6.dialogs import JsonPreviewDialog, ShutdownDialog
from APP.ui.pyqt6.event_bridge import UiQueueBridge
from APP.ui.pyqt6.main_window import TradingMainWindow
from APP.ui.state import AutorunState, PromptState, UiConfigState
from APP.utils.threading_utils import CancelToken, TaskRecord, ThreadingManager


class ImmediateThreadingAdapter:
    """Threading adapter thực thi tác vụ đồng bộ để dễ kiểm thử."""

    def __init__(self, ui_bridge: UiQueueBridge) -> None:
        self.threading_manager = ThreadingManager(max_workers=1)
        self._bridge = ui_bridge

    def submit(
        self,
        *,
        func,
        args=None,
        kwargs=None,
        group: str = "default",
        name: str | None = None,
        on_result=None,
        on_error=None,
        **_: object,
    ) -> TaskRecord:
        future: Future = Future()
        try:
            result = func(*(args or ()), **(kwargs or {}))
        except Exception as exc:  # pragma: no cover - điều hướng xuống on_error
            future.set_exception(exc)
            if on_error:
                self._bridge.post(lambda exc=exc: on_error(exc))
        else:
            future.set_result(result)
            if on_result:
                self._bridge.post(lambda result=result: on_result(result))
        return TaskRecord(
            future=future,
            token=CancelToken(),
            name=name or getattr(func, "__name__", "anonymous"),
            group=group,
        )


class StubIOController:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def run(
        self,
        *,
        worker,
        group: str,
        name: str,
        metadata: dict | None = None,
        **_: object,
    ) -> TaskRecord:
        self.calls.append((group, name))
        future: Future = Future()
        try:
            result = worker()
        except Exception as exc:  # pragma: no cover - lỗi được chuyển về UI
            future.set_exception(exc)
        else:
            future.set_result(result)
        return TaskRecord(
            future=future,
            token=CancelToken(),
            name=name,
            group=group,
            metadata=dict(metadata or {}),
        )


class StubNewsController:
    def __init__(self, bridge: UiQueueBridge) -> None:
        self.bridge = bridge
        self.refresh_calls = 0
        self.autorun_calls = 0
        self._callback = None

    def start_polling(self, callback) -> None:  # type: ignore[no-untyped-def]
        self._callback = callback

    def refresh_now(self) -> None:
        self.refresh_calls += 1
        if self._callback:
            payload = {
                "events": [
                    {
                        "when_local": datetime.now() + timedelta(minutes=15),
                        "country": "US",
                        "title": "GDP",
                        "impact": "high",
                    }
                ],
                "source": "stub",
                "latency": 0.1,
                "priority": "user",
            }
            self.bridge.post(lambda p=payload: self._callback(p))

    def trigger_autorun(self, *, force: bool = False) -> None:
        if force:
            self.autorun_calls += 1


class StubChartController:
    def __init__(self) -> None:
        self.last_config: ChartStreamConfig | None = None
        self.refresh_calls = 0
        self.snapshot_calls = 0

    def start_stream(
        self,
        *,
        config: ChartStreamConfig,
        info_worker,
        chart_worker,
        on_info_done,
        on_chart_done,
    ) -> None:
        self.last_config = config
        # Kích hoạt callback ngay để mô phỏng dữ liệu ban đầu
        on_info_done({"metrics": "stub"})
        on_chart_done({"snapshot": "stub"})

    def update_config(self, config: ChartStreamConfig) -> None:
        self.last_config = config

    def trigger_refresh(self, *, force: bool = False) -> None:
        if force:
            self.refresh_calls += 1

    def request_snapshot(self) -> None:
        self.snapshot_calls += 1

    def cancel_group(self, group: str) -> None:  # pragma: no cover - không dùng trong test
        del group

    def await_idle(self, group: str | None = None, timeout: float | None = None) -> bool:
        del group, timeout
        return True

    def shutdown(self, *, wait: bool = True, timeout: float | None = None, force: bool = False) -> None:
        del wait, timeout, force


class StubAnalysisController:
    def __init__(self) -> None:
        self.start_calls: list[tuple[str, Any, Any, str]] = []
        self.stop_calls: list[str] = []
        self.autorun_calls: list[str] = []

    def start_session(
        self,
        session_id: str,
        app,
        cfg,
        *,
        priority: str = "user",
        on_start=None,
    ) -> None:
        self.start_calls.append((session_id, app, cfg, priority))
        if on_start:
            on_start(session_id, priority)

    def stop_session(self, session_id: str) -> None:
        self.stop_calls.append(session_id)

    def enqueue_autorun(
        self,
        session_id: str,
        app,
        cfg,
        *,
        on_start=None,
    ) -> str:
        self.autorun_calls.append(session_id)
        if on_start:
            on_start(session_id, "autorun")
        return "started"


@pytest.fixture()
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture()
def config_state(tmp_path: Path) -> UiConfigState:
    workspace = tmp_path / "workspace"
    prompt_file = tmp_path / "prompts.json"
    return UiConfigState(
        folder=FolderConfig(folder=str(workspace), delete_after=True, max_files=5, only_generate_if_changed=False),
        upload=UploadConfig(upload_workers=2, cache_enabled=True, optimize_lossless=False),
        image_processing=ImageProcessingConfig(max_width=800, jpeg_quality=90),
        context=ContextConfig(
            ctx_limit=2048,
            create_ctx_json=True,
            prefer_ctx_json=False,
            ctx_json_n=5,
            remember_context=True,
            n_reports=2,
        ),
        api=ApiConfig(tries=3, delay=1.0),
        telegram=TelegramConfig(
            enabled=True,
            token="abc",
            chat_id="123",
            skip_verify=False,
            ca_path="/tmp/ca.pem",
            notify_on_early_exit=True,
        ),
        mt5=MT5Config(enabled=True, symbol="XAUUSD", n_M1=120, n_M5=90, n_M15=60, n_H1=30),
        mt5_terminal_path="/opt/mt5/terminal.exe",
        no_run=NoRunConfig(
            weekend_enabled=True,
            killzone_enabled=False,
            holiday_check_enabled=False,
            holiday_check_country="US",
            timezone="Asia/Ho_Chi_Minh",
            killzone_summer=None,
            killzone_winter=None,
        ),
        no_trade=NoTradeConfig(
            enabled=True,
            spread_max_pips=2.0,
            min_atr_m5_pips=1.5,
            min_dist_keylvl_pips=3.0,
            allow_session_asia=True,
            allow_session_london=True,
            allow_session_ny=False,
        ),
        auto_trade=AutoTradeConfig(
            enabled=False,
            strict_bias=False,
            size_mode="risk_percent",
            risk_per_trade=0.5,
            split_tp_enabled=False,
            split_tp_ratio=50,
            deviation=10,
            magic_number=999,
            comment="demo",
            pending_ttl_min=60,
            min_rr_tp2=1.5,
            cooldown_min=15,
            dynamic_pending=False,
            dry_run=True,
            move_to_be_after_tp1=False,
            trailing_atr_mult=0.5,
            filling_type="IOC",
        ),
        news=NewsConfig(
            block_enabled=True,
            block_before_min=15,
            block_after_min=30,
            cache_ttl_sec=120,
            priority_keywords=("USD",),
            provider_error_threshold=3,
            provider_error_backoff_sec=180,
            surprise_score_threshold=0.5,
            currency_country_overrides=None,
            symbol_country_overrides=None,
        ),
        persistence=PersistenceConfig(max_md_reports=10),
        fmp=FMPConfig(enabled=True, api_key="fmp"),
        te=TEConfig(enabled=False, api_key="", skip_ssl_verify=False),
        chart=ChartConfig(timeframe="M15", num_candles=150, chart_type="Nến", refresh_interval_secs=5),
        model="gemini-pro",
        autorun=AutorunState(enabled=True, interval_secs=300),
        prompt=PromptState(file_path=str(prompt_file), auto_load_from_disk=True),
    )


def _drain_bridge(bridge: UiQueueBridge) -> None:
    while bridge.drain_once():
        pass

@contextmanager
def make_window(
    config_state: UiConfigState,
    *,
    controllers: ControllerSet | None = None,
    controllers_factory=None,
    dialogs=None,
    apply_config=None,
    queue_factory=lambda: queue.Queue(),
):
    bridge = UiQueueBridge(queue_factory())
    threading = ImmediateThreadingAdapter(bridge)
    controller_set = controllers_factory(bridge) if controllers_factory else controllers
    window = TradingMainWindow(
        config_state,
        threading,
        bridge,
        controllers=controller_set,
        dialogs=dialogs,
        apply_config=apply_config,
    )
    try:
        yield window, bridge, threading
    finally:
        try:
            bridge.stop()
        except Exception:
            pass
        try:
            window.close()
        except Exception:
            pass
        try:
            QApplication.processEvents()
        except Exception:
            pass
        threading.threading_manager.shutdown(force=True)


def test_prompt_load_uses_io_controller(qapp, config_state, tmp_path: Path):
    prompt_file = tmp_path / "custom_prompt.json"
    prompt_file.write_text(json.dumps({"no_entry": "demo", "entry_run": "demo"}), encoding="utf-8")

    stub_io = StubIOController()

    with make_window(config_state, controllers=ControllerSet(io=stub_io)) as (window, bridge, _threading):
        window._handle_prompt_load(str(prompt_file))
        _drain_bridge(bridge)

        assert window.prompt_tab.no_entry_editor.toPlainText() == "demo"
        assert window.prompt_tab.entry_editor.toPlainText() == "demo"
        assert stub_io.calls
        assert stub_io.calls[-1] == ("prompt", "prompt.load")


def test_news_refresh_uses_controller(qapp, config_state):
    holder: dict[str, StubNewsController] = {}

    def _factory(bridge: UiQueueBridge) -> ControllerSet:
        stub = StubNewsController(bridge)
        holder['stub'] = stub
        return ControllerSet(news=stub)

    with make_window(config_state, controllers_factory=_factory) as (window, bridge, _threading):
        stub_news = holder['stub']
        window._handle_news_refresh()
        assert stub_news.refresh_calls >= 1
        _drain_bridge(bridge)
        assert window.news_tab.table.rowCount() == 1
        window._handle_options_changed({})
        assert stub_news.autorun_calls >= 1


def test_chart_refresh_uses_controller(qapp, config_state):
    stub_chart = StubChartController()

    def _factory(bridge: UiQueueBridge) -> ControllerSet:
        return ControllerSet(chart=stub_chart)

    with make_window(config_state, controllers_factory=_factory) as (window, bridge, _threading):
        window._handle_chart_refresh()
        assert stub_chart.refresh_calls == 1
        assert "Đang yêu cầu" in window.chart_tab.chart_output.toPlainText()
        window._handle_chart_snapshot()
        assert stub_chart.snapshot_calls == 1


def test_manual_analysis_uses_controller(qapp, config_state):
    holder: dict[str, StubAnalysisController] = {}

    def _factory(bridge: UiQueueBridge) -> ControllerSet:
        stub = StubAnalysisController()
        holder["stub"] = stub
        return ControllerSet(analysis=stub)

    with make_window(
        config_state,
        controllers_factory=_factory,
        apply_config=lambda state: state.to_run_config(),
    ) as (window, bridge, _threading):
        stub_analysis = holder["stub"]
        window._handle_manual_analysis()
        _drain_bridge(bridge)

        assert len(stub_analysis.start_calls) == 1
        session_id, app_adapter, run_cfg, priority = stub_analysis.start_calls[0]
        assert priority == "user"
        assert run_cfg.chart.timeframe == config_state.chart.timeframe
        assert app_adapter.__class__.__name__ == "PyQtAnalysisAppAdapter"
        assert window.overview_tab.cancel_button.isEnabled()
        assert not window.overview_tab.start_button.isEnabled()


def test_cancel_analysis_uses_controller(qapp, config_state):
    holder: dict[str, StubAnalysisController] = {}

    def _factory(bridge: UiQueueBridge) -> ControllerSet:
        stub = StubAnalysisController()
        holder["stub"] = stub
        return ControllerSet(analysis=stub)

    with make_window(
        config_state,
        controllers_factory=_factory,
        apply_config=lambda state: state.to_run_config(),
    ) as (window, bridge, _threading):
        stub_analysis = holder["stub"]
        window._handle_manual_analysis()
        _drain_bridge(bridge)
        assert stub_analysis.start_calls

        window._handle_cancel_analysis()
        assert stub_analysis.stop_calls == [stub_analysis.start_calls[0][0]]


class StubDialogProvider:
    """Thay thế DialogProvider để quan sát tương tác trong test."""

    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.saved_requests: list[dict[str, str]] = []
        self.open_requests: list[dict[str, str]] = []
        self.prompt_browse: list[dict[str, str]] = []
        self.json_dialogs: list[str] = []
        self.opened_paths: list[str] = []
        self.info_messages: list[tuple[str, str]] = []
        self.warning_messages: list[tuple[str, str]] = []
        self.error_messages: list[tuple[str, str]] = []

    def save_file(self, *, caption: str, directory: str, filter: str) -> str:
        self.saved_requests.append({"caption": caption, "directory": directory, "filter": filter})
        return str(self.tmp_path / "workspace_copy.json")

    def open_file(self, *, caption: str, directory: str, filter: str) -> str:
        self.open_requests.append({"caption": caption, "directory": directory, "filter": filter})
        return str(self.tmp_path / "prompt.json")

    def show_json_dialog(self, *, title: str, payload) -> JsonPreviewDialog:
        self.json_dialogs.append(title)
        dialog = JsonPreviewDialog()
        dialog.set_payload(payload)
        dialog.show()
        return dialog

    def show_info(self, *, title: str, message: str) -> None:
        self.info_messages.append((title, message))

    def show_warning(self, *, title: str, message: str) -> None:
        self.warning_messages.append((title, message))

    def show_error(self, *, title: str, message: str) -> None:
        self.error_messages.append((title, message))

    def open_path(self, path: str) -> bool:
        self.opened_paths.append(path)
        return True

    def create_shutdown_dialog(self) -> ShutdownDialog:  # pragma: no cover - chưa dùng
        return ShutdownDialog()


def test_main_window_prompt_flow(qapp, config_state: UiConfigState, tmp_path: Path) -> None:
    prompt_path = Path(config_state.prompt.file_path)
    prompt_path.write_text(
        json.dumps({"no_entry": "Hello", "entry_run": "World", "auto_load": True}, ensure_ascii=False),
        encoding="utf-8",
    )

    dialogs = StubDialogProvider(tmp_path)

    with make_window(config_state, dialogs=dialogs) as (window, bridge, _threading):
        _drain_bridge(bridge)

        assert "Hello" in window.prompt_tab.no_entry_editor.toPlainText()
        assert "World" in window.prompt_tab.entry_editor.toPlainText()

        window.prompt_tab.no_entry_editor.setPlainText('{"text": "Xin chào"}')
        window.prompt_tab.reformat_button.click()
        _drain_bridge(bridge)
        assert "Xin chào" in window.prompt_tab.no_entry_editor.toPlainText()


def test_main_window_history_open_json(tmp_path: Path, qapp, config_state: UiConfigState) -> None:
    dialogs = StubDialogProvider(tmp_path)

    with make_window(config_state, dialogs=dialogs) as (window, bridge, _threading):
        json_file = tmp_path / "Reports" / "ctx_1.json"
        json_file.parent.mkdir(parents=True, exist_ok=True)
        json_file.write_text(json.dumps({"foo": "bar"}), encoding="utf-8")

        window._handle_history_open(str(json_file))
        _drain_bridge(bridge)

        assert dialogs.json_dialogs and dialogs.json_dialogs[0].endswith("ctx_1.json")


def test_main_window_history_open_markdown(tmp_path: Path, qapp, config_state: UiConfigState) -> None:
    dialogs = StubDialogProvider(tmp_path)

    with make_window(config_state, dialogs=dialogs) as (window, bridge, _threading):
        md_file = tmp_path / "Reports" / "report.md"
        md_file.parent.mkdir(parents=True, exist_ok=True)
        md_file.write_text("demo", encoding="utf-8")

        window._handle_history_open(str(md_file))
        _drain_bridge(bridge)

        assert dialogs.opened_paths and dialogs.opened_paths[0] == str(md_file.parent)

def test_main_window_history_refresh_and_preview(qapp, config_state: UiConfigState, tmp_path: Path) -> None:
    workspace = Path(config_state.folder.folder)
    reports_dir = workspace / "XAUUSD" / "Reports"
    reports_dir.mkdir(parents=True)
    report_file = reports_dir / "report_1.md"
    report_file.write_text("Báo cáo mẫu", encoding="utf-8")
    ctx_file = reports_dir / "ctx_1.json"
    ctx_file.write_text("{\"ctx\": 1}", encoding="utf-8")

    ui_queue: queue.Queue = queue.Queue()
    bridge = UiQueueBridge(ui_queue)
    threading = ImmediateThreadingAdapter(bridge)

    window = TradingMainWindow(config_state, threading, bridge)
    _drain_bridge(bridge)  # xử lý auto-load prompt

    window.history_tab.refresh_requested.emit("reports")
    _drain_bridge(bridge)

    assert window.history_tab.reports_list.count() >= 1

    window.history_tab.reports_list.setCurrentRow(0)
    _drain_bridge(bridge)

    assert "Báo cáo" in window.history_tab.preview_box.toPlainText()


def test_main_window_reports_refresh_and_delete(qapp, config_state: UiConfigState, tmp_path: Path) -> None:
    workspace = Path(config_state.folder.folder)
    workspace.mkdir(parents=True, exist_ok=True)
    reports_dir = workspace / "Reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_file = reports_dir / "report_demo.md"
    report_file.write_text("Báo cáo PyQt6", encoding="utf-8")

    ui_queue: queue.Queue = queue.Queue()
    bridge = UiQueueBridge(ui_queue)
    threading = ImmediateThreadingAdapter(bridge)
    dialogs = StubDialogProvider(tmp_path)

    window = TradingMainWindow(config_state, threading, bridge, dialogs=dialogs)
    _drain_bridge(bridge)

    assert window.reports_tab.table.rowCount() >= 1

    window._handle_reports_delete(str(report_file))
    _drain_bridge(bridge)
    assert not report_file.exists()


def test_main_window_options_updates(qapp, config_state: UiConfigState, tmp_path: Path) -> None:
    ui_queue: queue.Queue = queue.Queue()
    bridge = UiQueueBridge(ui_queue)
    threading = ImmediateThreadingAdapter(bridge)
    dialogs = StubDialogProvider(tmp_path)

    window = TradingMainWindow(config_state, threading, bridge, dialogs=dialogs)
    _drain_bridge(bridge)

    messages: list[str] = []
    window.statusBar().messageChanged.connect(lambda msg: messages.append(msg or ""))

    window.options_tab.max_files_spin.setValue(config_state.folder.max_files + 2)
    _drain_bridge(bridge)

    assert any("Options" in message for message in messages if message)

    window._handle_options_load_env()
    _drain_bridge(bridge)
    assert any(".env" in line for line in window.overview_tab.log_view.toPlainText().splitlines())


def test_main_window_snapshot_ui_state(qapp, config_state: UiConfigState, tmp_path: Path) -> None:
    ui_queue: queue.Queue = queue.Queue()
    bridge = UiQueueBridge(ui_queue)
    threading = ImmediateThreadingAdapter(bridge)
    window = TradingMainWindow(config_state, threading, bridge, dialogs=StubDialogProvider(tmp_path))
    _drain_bridge(bridge)

    window.options_tab.cache_enabled_checkbox.setChecked(False)
    window.options_tab.max_md_reports_spin.setValue(77)
    window.overview_tab.set_autorun_state(False, 450)
    window.chart_tab.timeframe_combo.setCurrentText("H1")

    state = window.snapshot_ui_state()
    assert state.upload.cache_enabled is False
    assert state.persistence.max_md_reports == 77
    assert state.autorun.enabled is False
    assert state.autorun.interval_secs == 450
    assert state.chart.timeframe == "H1"


def test_main_window_build_workspace_payload(qapp, config_state: UiConfigState, tmp_path: Path) -> None:
    ui_queue: queue.Queue = queue.Queue()
    bridge = UiQueueBridge(ui_queue)
    threading = ImmediateThreadingAdapter(bridge)
    dialogs = StubDialogProvider(tmp_path)
    window = TradingMainWindow(config_state, threading, bridge, dialogs=dialogs)
    _drain_bridge(bridge)

    window.overview_tab.set_autorun_state(False, 720)
    window.prompt_tab.path_edit.setText(str(tmp_path / "prompt_custom.json"))
    window.prompt_tab.no_entry_editor.setPlainText("Demo no entry")
    window.prompt_tab.entry_editor.setPlainText("Demo entry")
    window.prompt_tab.autoload_checkbox.setChecked(False)
    window.options_tab.api_key_edit.setText("secret")
    window.options_tab.max_md_reports_spin.setValue(42)
    window.chart_tab.timeframe_combo.setCurrentText("H4")

    payload = window.build_workspace_payload()

    assert payload["folder"]["folder_path"] == config_state.folder.folder
    assert payload["autorun"] is False
    assert payload["autorun_secs"] == 720
    assert payload["persistence"]["max_md_reports"] == 42
    assert payload["prompts"]["prompt_file_path"].endswith("prompt_custom.json")
    assert payload["prompts"]["auto_load_prompt_txt"] is False
    assert payload["prompts"]["no_entry"] == "Demo no entry"
    assert payload["prompts"]["entry_run"] == "Demo entry"
    assert payload["chart"]["timeframe"] == "H4"
    assert payload["api_keys"]["google_ai"] == "secret"


def test_main_window_ui_status_and_log(qapp, config_state: UiConfigState, tmp_path: Path) -> None:
    ui_queue: queue.Queue = queue.Queue()
    bridge = UiQueueBridge(ui_queue)
    threading = ImmediateThreadingAdapter(bridge)
    dialogs = StubDialogProvider(tmp_path)
    window = TradingMainWindow(config_state, threading, bridge, dialogs=dialogs)
    _drain_bridge(bridge)

    window.ui_status("Đang xử lý batch", running=True)
    assert "Đang xử lý batch" in window.overview_tab.status_label.text()
    assert window.overview_tab.log_view.toPlainText().splitlines()[0] == "Đang xử lý batch"
    assert "Đang xử lý batch" in window.statusBar().currentMessage()

    window.show_info_message("Thông báo", "Hoàn tất")
    assert dialogs.info_messages[-1] == ("Thông báo", "Hoàn tất")


def test_main_window_ui_progress_modes(qapp, config_state: UiConfigState, tmp_path: Path) -> None:
    dialogs = StubDialogProvider(tmp_path)

    with make_window(config_state, dialogs=dialogs) as (window, bridge, _threading):
        window.show()
        qapp.processEvents()
        _drain_bridge(bridge)

        window.ui_progress(25)
        qapp.processEvents()
        assert window.overview_tab.progress_bar.isVisible()
        assert window.overview_tab.progress_bar.maximum() == 100
        assert window.overview_tab.progress_bar.value() == 25

        window.ui_progress(0, indeterminate=True)
        qapp.processEvents()
        assert window.overview_tab.progress_bar.maximum() == 0

        window.ui_progress(None)
        qapp.processEvents()
        assert not window.overview_tab.progress_bar.isVisible()


def test_main_window_ui_detail_and_error(qapp, config_state: UiConfigState, tmp_path: Path) -> None:
    ui_queue: queue.Queue = queue.Queue()
    bridge = UiQueueBridge(ui_queue)
    threading = ImmediateThreadingAdapter(bridge)
    dialogs = StubDialogProvider(tmp_path)
    window = TradingMainWindow(config_state, threading, bridge, dialogs=dialogs)
    _drain_bridge(bridge)

    window.ui_detail_replace("Chi tiết báo cáo mới")
    assert "Chi tiết báo cáo" in window.reports_tab.detail_output.toPlainText()

    window.show_error_message("Lỗi", "Không thể xử lý")
    assert dialogs.error_messages[-1] == ("Lỗi", "Không thể xử lý")
