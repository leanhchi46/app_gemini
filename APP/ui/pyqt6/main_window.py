"""Khung cửa sổ chính PyQt6 sau khi tách từng module UI."""

from __future__ import annotations

import ast
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Optional

from PyQt6.QtCore import QTimer, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QDialog, QMainWindow, QTabWidget, QWidget

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
from APP.ui.controllers import ChartStreamConfig
from APP.ui.pyqt6.controller_bridge import ControllerSet
from APP.ui.pyqt6.dialogs import DialogProvider
from APP.ui.pyqt6.event_bridge import QtThreadingAdapter, UiQueueBridge
from APP.ui.pyqt6.tabs import (
    ChartTabWidget,
    HistoryEntry,
    HistoryTabWidget,
    NewsTabWidget,
    OptionsTabWidget,
    OverviewTab,
    PromptTabWidget,
    ReportEntry,
    ReportTabWidget,
)
from APP.ui.state import AutorunState, PromptState, UiConfigState
from APP.ui.utils.timeframe_detector import TimeframeDetector

_PROMPT_TEXT_KEYS = ("text", "content", "prompt", "body", "value")


def _extract_prompt_text(obj: Any) -> str:
    parts: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, str):
            if value.strip():
                parts.append(value)
            return
        if isinstance(value, dict):
            for key in _PROMPT_TEXT_KEYS:
                item = value.get(key)
                if isinstance(item, str) and item.strip():
                    parts.append(item)
            for item in value.values():
                if item is not None and not isinstance(item, str):
                    walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(obj)
    text = "\n\n".join(part.strip() for part in parts if part and part.strip())
    if text and text.count('"') > 0 and text.count("\n") <= text.count('"'):
        text = (
            text.replace('"', "\n")
            .replace("\\t", "\t")
            .replace('\\"', '"')
            .replace("\\'", "'")
        )
    if text:
        return text
    return json.dumps(obj, ensure_ascii=False, indent=2)


def _normalize_prompt_text(raw: str) -> str:
    s = raw.strip()
    if not s:
        return ""
    try:
        obj = json.loads(s)
    except Exception:
        obj = None
    if obj is not None:
        return _extract_prompt_text(obj)
    try:
        parsed = ast.literal_eval(s)
    except Exception:
        return s
    return _extract_prompt_text(parsed)


class _SimpleVar:
    """Biến đơn giản với API tương thích tk.Variable."""

    def __init__(self, value: Any = "") -> None:
        self._value = value

    def get(self) -> Any:
        return self._value

    def set(self, value: Any) -> None:
        self._value = value


class _PyQtPromptManager:
    """Adapter lấy prompt từ PromptTabWidget."""

    def __init__(self, window: "TradingMainWindow") -> None:
        self._window = window

    def get_prompts(self) -> dict[str, str]:
        return self._window.prompt_tab.prompt_texts()


class _PyQtHistoryManager:
    """Adapter tối giản làm mới tab lịch sử."""

    def __init__(self, window: "TradingMainWindow") -> None:
        self._window = window

    def refresh_all_lists(self) -> None:
        self._window.history_tab.set_status("Đang cập nhật lịch sử…")


class PyQtAnalysisAppAdapter:
    """Đưa TradingMainWindow về API mong đợi của AnalysisWorker."""

    def __init__(
        self,
        window: "TradingMainWindow",
        ui_queue,
        threading_manager,
    ) -> None:
        self._window = window
        self.ui_queue = ui_queue
        self.threading_manager = threading_manager
        self.prompt_manager = _PyQtPromptManager(window)
        self.history_manager = _PyQtHistoryManager(window)
        self.timeframe_detector = TimeframeDetector()
        self.folder_path = _SimpleVar(window._config_state.folder.folder)
        self.api_key_var = _SimpleVar("")
        self.model_var = _SimpleVar(window._config_state.model)
        self.stop_flag = False
        self.results: list[dict[str, Any]] = []
        self.combined_report_text = ""

    def update_from_state(
        self,
        state: UiConfigState,
        *,
        options_payload: dict[str, Any] | None = None,
    ) -> None:
        self.folder_path.set(state.folder.folder)
        self.model_var.set(state.model)
        if options_payload:
            api_keys = options_payload.get("api_keys")
            if isinstance(api_keys, dict):
                self.api_key_var.set(str(api_keys.get("google", "")))

    def prepare_for_session(self) -> None:
        self.results = []
        self.combined_report_text = ""
        self.stop_flag = False

    # ------------------------------------------------------------------
    # Proxy API mà AnalysisWorker mong đợi
    # ------------------------------------------------------------------
    def ui_status(self, message: str) -> None:
        self._window.ui_status(message)

    def ui_progress(self, value: float | None, *, indeterminate: bool = False) -> None:
        self._window.ui_progress(value, indeterminate=indeterminate)

    def ui_detail_replace(self, text: str) -> None:
        self._window.ui_detail_replace(text)

    def show_error_message(self, title: str, message: str) -> None:
        self._window.show_error_message(title, message)

    def append_log(self, message: str) -> None:
        self._window.append_log(message)

    def _update_tree_row(self, index: int, status: str) -> None:
        if 0 <= index < len(self.results):
            self.results[index]["status"] = status

    def _update_progress(self, current_step: int, total_steps: int) -> None:
        value = 0.0
        if total_steps:
            value = (current_step / total_steps) * 100.0
        self._window.ui_progress(value)

    def _finalize_done(self) -> None:
        self._window._finalize_done()

    def _finalize_stopped(self) -> None:
        self._window._finalize_stopped()

class TradingMainWindow(QMainWindow):
    """Cửa sổ chính PyQt6 gồm các tab chức năng độc lập."""

    def __init__(
        self,
        config_state: UiConfigState,
        threading: QtThreadingAdapter,
        ui_bridge: UiQueueBridge,
        *,
        controllers: ControllerSet | None = None,
        apply_config: Callable[[UiConfigState], Any] | None = None,
        parent: Optional[QWidget] = None,
        dialogs: DialogProvider | None = None,
    ) -> None:
        super().__init__(parent)
        self._config_state = config_state
        self._threading = threading
        self._ui_bridge = ui_bridge
        self._dialogs = dialogs or DialogProvider(self)
        self._active_dialogs: list[QDialog] = []
        self._workspace_folder = Path(self._config_state.folder.folder).expanduser()
        self._report_previews: dict[str, str] = {}
        self._last_options_payload: dict[str, Any] | None = None
        self._controllers = controllers or ControllerSet()
        self._apply_config = apply_config
        self._run_config = self._apply_config(self._config_state) if self._apply_config else None
        if self._run_config is None:
            self._run_config = self._config_state.to_run_config()
        self._last_news_payload: dict[str, Any] | None = None
        self._ui_queue = self._ui_bridge.queue
        self._analysis_adapter = PyQtAnalysisAppAdapter(
            self,
            self._ui_queue,
            self._threading.threading_manager,
        )
        self._analysis_adapter.update_from_state(self._config_state)
        self._is_running = False
        self._pending_session = False
        self._current_session_id: str | None = None
        self._queued_autorun_session: str | None = None
        self._news_polling_started = False
        self._autorun_timer = QTimer(self)
        self._autorun_timer.setSingleShot(True)
        self._autorun_timer.timeout.connect(self._handle_autorun_timeout)
        self._autorun_enabled = bool(self._config_state.autorun.enabled)
        self._autorun_interval = int(self._config_state.autorun.interval_secs)

        self.setWindowTitle("TOOL GIAO DỊCH TỰ ĐỘNG")
        self.resize(1180, 780)
        self.setMinimumSize(1024, 660)

        self._tabs = QTabWidget(self)
        self.setCentralWidget(self._tabs)

        self.overview_tab = OverviewTab(config_state, self)
        self.reports_tab = ReportTabWidget(self._workspace_folder, self)
        self.chart_tab = ChartTabWidget(config_state, self)
        self.news_tab = NewsTabWidget(config_state, self)
        self.prompt_tab = PromptTabWidget(config_state, self)
        self.history_tab = HistoryTabWidget(self)
        self.options_tab = OptionsTabWidget(config_state, self)

        self._tabs.addTab(self.overview_tab, "Tổng quan")
        self._tabs.addTab(self.reports_tab, "Báo cáo")
        self._tabs.addTab(self.chart_tab, "Biểu đồ")
        self._tabs.addTab(self.news_tab, "Tin tức")
        self._tabs.addTab(self.prompt_tab, "Prompt")
        self._tabs.addTab(self.history_tab, "Lịch sử")
        self._tabs.addTab(self.options_tab, "Tuỳ chọn")

        self._connect_signals()
        self._setup_controllers()
        self._update_services_config(self._config_state)
        if self._autorun_enabled:
            self._schedule_next_autorun()

        if self._config_state.prompt.auto_load_from_disk:
            self._handle_prompt_load(self._config_state.prompt.file_path)
        self._handle_reports_refresh()

    # ------------------------------------------------------------------
    def _connect_signals(self) -> None:
        self.overview_tab.start_analysis_requested.connect(self._handle_manual_analysis)
        self.overview_tab.cancel_analysis_requested.connect(self._handle_cancel_analysis)
        self.overview_tab.autorun_toggled.connect(self._handle_autorun_toggle)
        self.overview_tab.autorun_interval_changed.connect(self._handle_autorun_interval_change)
        self.overview_tab.save_workspace_requested.connect(self._handle_workspace_save)
        self.overview_tab.load_workspace_requested.connect(self._handle_workspace_load)

        self.reports_tab.refresh_requested.connect(self._handle_reports_refresh)
        self.reports_tab.open_requested.connect(self._handle_reports_open)
        self.reports_tab.delete_requested.connect(self._handle_reports_delete)
        self.reports_tab.open_folder_requested.connect(self._handle_reports_open_folder)
        self.reports_tab.selection_changed.connect(self._handle_reports_selection_changed)

        self.chart_tab.settings_changed.connect(self._handle_chart_settings_changed)
        self.chart_tab.refresh_requested.connect(self._handle_chart_refresh)
        self.chart_tab.snapshot_requested.connect(self._handle_chart_snapshot)

        self.news_tab.manual_refresh_requested.connect(self._handle_news_refresh)
        self.news_tab.override_toggled.connect(self._handle_news_override)

        self.prompt_tab.load_requested.connect(self._handle_prompt_load)
        self.prompt_tab.save_requested.connect(self._handle_prompt_save)
        self.prompt_tab.reformat_requested.connect(self._handle_prompt_reformat)
        self.prompt_tab.browse_requested.connect(self._handle_prompt_browse)

        self.history_tab.refresh_requested.connect(self._handle_history_refresh)
        self.history_tab.preview_requested.connect(self._handle_history_preview)
        self.history_tab.open_requested.connect(self._handle_history_open)

        self.options_tab.config_changed.connect(self._handle_options_changed)
        self.options_tab.load_env_requested.connect(self._handle_options_load_env)
        self.options_tab.save_safe_requested.connect(self._handle_options_save_safe)
        self.options_tab.delete_safe_requested.connect(self._handle_options_delete_safe)

    # ------------------------------------------------------------------
    def _setup_controllers(self) -> None:
        chart_ctrl = self._controllers.chart
        if chart_ctrl:
            config = self.chart_tab.current_config()
            chart_ctrl.update_config(config)
            chart_ctrl.start_stream(
                config=config,
                info_worker=self._chart_info_worker,
                chart_worker=self._chart_snapshot_worker,
                on_info_done=self._chart_info_finished,
                on_chart_done=self._chart_snapshot_finished,
            )

        news_ctrl = self._controllers.news
        if news_ctrl:
            news_ctrl.start_polling(self._handle_news_payload)
            self._news_polling_started = True

    # ------------------------------------------------------------------
    # Handlers cho tab Tổng quan
    # ------------------------------------------------------------------
    def _handle_manual_analysis(self) -> None:
        analysis_ctrl = self._controllers.analysis
        if analysis_ctrl and self._run_config:
            state = self.snapshot_ui_state()
            self._config_state = state
            self._analysis_adapter.update_from_state(state)
            if self._apply_config:
                self._run_config = self._apply_config(state)
            else:
                self._run_config = state.to_run_config()
            run_config = self._run_config
            self._update_services_config(state)
            self._analysis_adapter.prepare_for_session()
            session_id = datetime.now().strftime("manual-%Y%m%d-%H%M%S")
            self._pending_session = True
            self._analysis_adapter.stop_flag = False
            self.overview_tab.set_status("Đang chuẩn bị chạy phân tích...", running=True)
            self._log_status("Đã gửi yêu cầu phân tích thủ công.")

            def _on_start(sid: str, priority: str) -> None:
                self._handle_session_started(sid, priority, run_config, source="manual")

            analysis_ctrl.start_session(
                session_id,
                self._analysis_adapter,
                run_config,
                priority="user",
                on_start=_on_start,
            )
            return

        # Fallback mô phỏng nếu chưa có AnalysisController
        self.overview_tab.set_status("Đang khởi động phiên phân tích…", running=True)
        self._log_status("Đã gửi yêu cầu phân tích thủ công (mock).")

        def _analysis_job() -> dict[str, str]:
            return {
                "status": "completed",
                "timestamp": datetime.now().isoformat(timespec="seconds"),
            }

        def _on_result(result: dict[str, str]) -> None:
            self.overview_tab.set_status("Phiên phân tích hoàn tất.", running=False)
            self.overview_tab.append_log(
                f"[{result['timestamp']}] Hoàn tất phiên phân tích thủ công (status={result['status']})."
            )
            self.statusBar().showMessage("Đã hoàn thành phiên phân tích.", 5000)

        def _on_error(exc: BaseException) -> None:
            self.overview_tab.set_status(f"Phiên phân tích lỗi: {exc}", running=False)
            self.overview_tab.append_log(f"[ERROR] Không thể hoàn tất phiên phân tích: {exc}")
            self.statusBar().showMessage("Phiên phân tích gặp lỗi.", 5000)

        self._threading.submit(
            func=_analysis_job,
            group="analysis",
            name="manual_analysis",
            on_result=_on_result,
            on_error=_on_error,
        )

    def _handle_cancel_analysis(self) -> None:
        analysis_ctrl = self._controllers.analysis
        if analysis_ctrl and self._current_session_id:
            self._analysis_adapter.stop_flag = True
            analysis_ctrl.stop_session(self._current_session_id)
            self.overview_tab.set_status("Đang dừng phiên phân tích...", running=True)
            self._log_status("Đã gửi yêu cầu hủy phiên phân tích.")
            return

        self._threading.cancel_group("analysis")
        self.overview_tab.set_status("Đã gửi yêu cầu hủy phiên.", running=False)
        self.overview_tab.append_log("[USER] Hủy phiên phân tích đang chạy.")
        self.statusBar().showMessage("Đã yêu cầu hủy phiên phân tích.", 4000)

    def _handle_autorun_toggle(self, enabled: bool) -> None:
        self._autorun_enabled = enabled
        state = "bật" if enabled else "tắt"
        self._log_status(f"Người dùng {state} chế độ autorun.")
        if enabled:
            self._schedule_next_autorun(immediate=True)
        else:
            if self._autorun_timer.isActive():
                self._autorun_timer.stop()

    def _handle_autorun_interval_change(self, interval: int) -> None:
        self._autorun_interval = max(1, interval)
        self._log_status(f"Cập nhật chu kỳ autorun: {self._autorun_interval} giây.")
        if self._autorun_enabled:
            self._schedule_next_autorun(immediate=True)

    def _handle_workspace_save(self) -> None:
        default_dir = str(Path(self._config_state.folder.folder).expanduser())
        path = self._dialogs.save_file(
            caption="Chọn nơi lưu workspace",
            directory=default_dir,
            filter="Workspace JSON (*.json);;Tất cả tệp (*)",
        )
        if path:
            payload = self.build_workspace_payload()
            self._log_status(
                "Đã chuẩn bị cấu hình workspace (" +
                f"{len(json.dumps(payload, ensure_ascii=False))} ký tự) để lưu tại {path}."
            )
        else:
            self._log_status("Người dùng hủy lưu workspace.")

    def _handle_workspace_load(self) -> None:
        default_dir = str(Path(self._config_state.folder.folder).expanduser())
        path = self._dialogs.open_file(
            caption="Chọn workspace để nạp",
            directory=default_dir,
            filter="Workspace JSON (*.json);;Tất cả tệp (*)",
        )
        if path:
            self._log_status(f"Đã chọn nạp workspace từ {path}.")
        else:
            self._log_status("Người dùng hủy nạp workspace.")

    # ------------------------------------------------------------------
    # Handlers cho tab Báo cáo
    # ------------------------------------------------------------------
    def _handle_reports_refresh(self) -> None:
        self.reports_tab.set_loading(True)

        def _job() -> dict[str, object]:
            base = self._workspace_folder
            collected: list[tuple[str, str, str, str, float]] = []
            if base.exists():
                search_roots = {base}
                reports_dir = base / "Reports"
                if reports_dir.is_dir():
                    search_roots.add(reports_dir)
                for child in base.iterdir():
                    if not child.is_dir():
                        continue
                    nested = child / "Reports"
                    if nested.is_dir():
                        search_roots.add(nested)
                for root in search_roots:
                    for file_path in root.glob("*.md"):
                        try:
                            content = file_path.read_text(encoding="utf-8", errors="ignore")
                        except OSError:
                            content = ""
                        try:
                            mtime = file_path.stat().st_mtime
                        except OSError:
                            mtime = 0.0
                        preview_lines = [line for line in content.splitlines() if line.strip()][:40]
                        preview = "\n".join(preview_lines)[:1200]
                        status = "Hoàn tất" if content else "Không đọc được"
                        try:
                            display = str(file_path.relative_to(base))
                        except ValueError:
                            display = file_path.name
                        collected.append((str(file_path), display, status, preview, mtime))
            collected.sort(key=lambda item: item[4], reverse=True)
            entries = [
                {
                    "path": path,
                    "display": display,
                    "status": status,
                    "preview": preview,
                }
                for path, display, status, preview, _ in collected
            ]
            status_msg = f"Tìm thấy {len(entries)} báo cáo." if entries else "Chưa có báo cáo trong workspace."
            return {"entries": entries, "status": status_msg}

        def _on_result(payload: dict[str, object]) -> None:
            self.reports_tab.set_loading(False)
            entries_payload = list(payload.get("entries") or [])
            report_entries: list[ReportEntry] = []
            previews: dict[str, str] = {}
            for item in entries_payload:
                path = str(item.get("path", ""))
                if not path:
                    continue
                report_entries.append(
                    ReportEntry(
                        path=Path(path),
                        display_name=str(item.get("display", Path(path).name)),
                        status=str(item.get("status", "")),
                    )
                )
                previews[path] = str(item.get("preview", ""))
            self._report_previews = previews
            self.reports_tab.set_entries(report_entries)
            if report_entries:
                first_path = str(report_entries[0].path)
                self.reports_tab.set_detail_text(previews.get(first_path, ""))
            else:
                self.reports_tab.clear_detail()
            status = str(payload.get("status", ""))
            if status:
                self.reports_tab.set_status(status)
                self.statusBar().showMessage(status, 4000)

        def _on_error(exc: BaseException) -> None:
            self.reports_tab.set_loading(False)
            message = f"Lỗi khi quét báo cáo: {exc}"
            self.reports_tab.set_status(message)
            self.statusBar().showMessage(message, 5000)

        self._threading.submit(
            func=_job,
            group="reports",
            name="reports.refresh",
            on_result=_on_result,
            on_error=_on_error,
        )

    def _handle_reports_open(self, path_str: str) -> None:
        path = Path(path_str)
        if not path.exists():
            self.statusBar().showMessage(f"Tệp không tồn tại: {path.name}", 4000)
            return
        if path.suffix.lower() == ".json":
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                payload = path.read_text(encoding="utf-8", errors="ignore")
            dialog = self._dialogs.show_json_dialog(
                title=f"Báo cáo JSON: {path.name}",
                payload=payload,
            )
            self._register_dialog(dialog)
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
            if self._dialogs.open_path(str(path.parent)):
                self._log_status(f"Đã mở thư mục chứa {path.name}.")
            else:
                self.statusBar().showMessage("Không thể mở báo cáo trong hệ điều hành.", 5000)
        else:
            self._log_status(f"Đã mở {path.name} trong hệ điều hành.")

    def _handle_reports_delete(self, path_str: str) -> None:
        path = Path(path_str)
        if not path.exists():
            self.statusBar().showMessage("Tệp không tồn tại để xoá.", 4000)
            return
        try:
            path.unlink()
        except OSError as exc:
            self.statusBar().showMessage(f"Không thể xoá {path.name}: {exc}", 5000)
        else:
            self._log_status(f"Đã xoá {path.name}.")
            self._handle_reports_refresh()

    def _handle_reports_open_folder(self) -> None:
        reports_dir = self._workspace_folder / "Reports"
        target = reports_dir if reports_dir.exists() else self._workspace_folder
        if self._dialogs.open_path(str(target)):
            self._log_status(f"Đã mở thư mục {target}.")
        else:
            self.statusBar().showMessage("Không thể mở thư mục báo cáo.", 5000)

    def _handle_reports_selection_changed(self, path_str: str) -> None:
        preview = self._report_previews.get(path_str)
        if preview:
            self.reports_tab.set_detail_text(preview)
        else:
            self.reports_tab.clear_detail()

    # ------------------------------------------------------------------
    # Handlers cho tab Biểu đồ
    # ------------------------------------------------------------------
    def _chart_info_worker(self, config: ChartStreamConfig) -> dict[str, Any]:
        return {
            "metrics": (
                "No-trade metrics sẽ được đồng bộ khi gắn MT5/NewsController thực sự.\n"
                f"Symbol: {config.symbol} — Timeframe: {config.timeframe}"
            )
        }

    def _chart_snapshot_worker(self, config: ChartStreamConfig) -> dict[str, Any]:
        now = datetime.now()
        snapshot = (
            f"Symbol: {config.symbol}\n"
            f"Timeframe: {config.timeframe}\n"
            f"Candles: {config.candles}\n"
            f"Snapshot lúc {now.strftime('%H:%M:%S')}"
        )
        return {"snapshot": snapshot}

    def _chart_info_finished(self, payload: dict[str, Any]) -> None:
        metrics = str(payload.get("metrics", ""))
        if metrics:
            self.chart_tab.set_metrics_text(metrics)

    def _chart_snapshot_finished(self, payload: dict[str, Any]) -> None:
        snapshot = str(payload.get("snapshot", ""))
        if snapshot:
            self.chart_tab.set_snapshot_text(snapshot)
            self.statusBar().showMessage("Đã cập nhật snapshot biểu đồ.", 4000)

    def _handle_chart_settings_changed(self, config: ChartStreamConfig) -> None:
        self.statusBar().showMessage(
            f"Đang chuẩn bị stream {config.symbol} khung {config.timeframe} ({config.candles} nến)…",
            4000,
        )
        chart_ctrl = self._controllers.chart
        if chart_ctrl:
            chart_ctrl.update_config(config)

    def _handle_chart_refresh(self) -> None:
        chart_ctrl = self._controllers.chart
        if chart_ctrl:
            chart_ctrl.trigger_refresh(force=True)
            self.chart_tab.set_snapshot_text("Đang yêu cầu dữ liệu biểu đồ…")
            return

        config = self.chart_tab.current_config()
        self.chart_tab.set_snapshot_text("Đang yêu cầu dữ liệu biểu đồ…")

        def _job() -> dict[str, Any]:
            return self._chart_snapshot_worker(config) | self._chart_info_worker(config)

        self._threading.submit(
            func=_job,
            group="chart",
            name="chart.refresh",
            on_result=lambda payload: (
                self._chart_snapshot_finished(payload),
                self._chart_info_finished(payload),
            ),
        )

    def _handle_chart_snapshot(self) -> None:
        chart_ctrl = self._controllers.chart
        if chart_ctrl:
            self._log_status("Đang yêu cầu snapshot biểu đồ ngay lập tức.")
            chart_ctrl.request_snapshot()
            return
        self._log_status("Ghi nhận yêu cầu snapshot biểu đồ tức thời.")
        self._handle_chart_refresh()

    # ------------------------------------------------------------------
    # Handlers cho tab Tin tức
    # ------------------------------------------------------------------
    def _handle_news_refresh(self) -> None:
        self.news_tab.set_loading(True)
        news_ctrl = self._controllers.news
        if news_ctrl:
            news_ctrl.refresh_now()
            return

        def _job() -> dict[str, object]:
            now = datetime.now()
            events = [
                {
                    "when_local": now + timedelta(minutes=idx * 15),
                    "country": "US" if idx % 2 == 0 else "EU",
                    "title": f"Sự kiện kinh tế #{idx + 1}",
                    "impact": "high" if idx == 0 else "medium",
                    "actual": 1.5 + idx,
                    "forecast": 1.2 + idx,
                    "previous": 1.1 + idx,
                    "surprise_score": 0.4 * (idx + 1),
                    "surprise_direction": "positive" if idx % 2 == 0 else "negative",
                }
                for idx in range(3)
            ]
            return {"events": events, "source": "mock", "latency": 0.2, "priority": "user"}

        self._threading.submit(
            func=_job,
            group="news",
            name="news.refresh",
            on_result=self._handle_news_payload,
            on_error=lambda exc: self._handle_news_error(exc),
        )

    def _handle_news_override(self, enabled: bool) -> None:
        message = "Đã bật bỏ qua chặn tin" if enabled else "Đã tắt bỏ qua chặn tin"
        self.statusBar().showMessage(message, 3000)

    def _handle_news_payload(self, payload: dict[str, Any]) -> None:
        events = payload.get("events") or []
        source = str(payload.get("source") or "unknown")
        latency = float(payload.get("latency") or payload.get("latency_sec") or 0.0)
        priority = str(payload.get("priority") or "auto")
        self._last_news_payload = {
            "events": events,
            "source": source,
            "latency": latency,
            "priority": priority,
        }
        self.news_tab.update_events(events, source=source, latency_sec=latency)
        self.news_tab.set_loading(False)
        self.statusBar().showMessage(
            f"Đã cập nhật tin tức ({priority}, nguồn {source}).",
            4000,
        )

    def _handle_news_error(self, exc: BaseException) -> None:
        self.news_tab.set_loading(False)
        message = f"Lỗi khi tải tin tức: {exc}"
        self.news_tab.status_label.setText(message)
        self.statusBar().showMessage(message, 5000)

    # ------------------------------------------------------------------
    # Handlers cho tab Prompt
    # ------------------------------------------------------------------
    def _handle_prompt_load(self, path_str: str) -> None:
        default_path = Path(self._config_state.prompt.file_path).expanduser()
        path = Path(path_str).expanduser() if path_str else default_path
        self.prompt_tab.set_file_path(str(path))
        self.prompt_tab.set_loading(True)
        self.prompt_tab.set_status(f"Đang tải prompt từ {path}…")
        default_auto = self.prompt_tab.autoload_checkbox.isChecked()

        def _job() -> dict[str, object]:
            if not path.exists():
                return {
                    "no_entry": "",
                    "entry_run": "",
                    "auto_load": default_auto,
                    "message": f"Không tìm thấy tệp prompt: {path}",
                }

            raw = path.read_text(encoding="utf-8", errors="ignore")
            try:
                data = json.loads(raw)
                message = "Đã tải prompt ở định dạng JSON."
            except json.JSONDecodeError:
                data = {"no_entry": raw, "entry_run": raw}
                message = "Tệp không phải JSON, áp dụng nội dung như nhau cho cả hai tab."

            no_entry = str(data.get("no_entry", ""))
            entry_run = str(data.get("entry_run", ""))
            auto = bool(data.get("auto_load", default_auto))
            return {
                "no_entry": no_entry,
                "entry_run": entry_run,
                "auto_load": auto,
                "message": message,
                "path": str(path),
            }

        def _on_result(payload: dict[str, object]) -> None:
            self.prompt_tab.set_loading(False)
            self.prompt_tab.set_prompt_content("no_entry", str(payload.get("no_entry", "")))
            self.prompt_tab.set_prompt_content("entry_run", str(payload.get("entry_run", "")))
            self.prompt_tab.set_autoload(bool(payload.get("auto_load", default_auto)))
            status = str(payload.get("message", "Đã tải prompt."))
            self.prompt_tab.set_status(status)
            self.statusBar().showMessage(status, 4000)

        def _on_error(exc: BaseException) -> None:
            self.prompt_tab.set_loading(False)
            message = f"Lỗi khi tải prompt: {exc}"
            self.prompt_tab.set_status(message)
            self.statusBar().showMessage(message, 5000)

        self._submit_io_task(
            worker=_job,
            group="prompt",
            name="prompt.load",
            metadata={"component": "prompt", "operation": "load"},
            on_result=_on_result,
            on_error=_on_error,
        )

    def _handle_prompt_save(self, path_str: str, payload: dict[str, object]) -> None:
        default_path = Path(self._config_state.prompt.file_path).expanduser()
        path = Path(path_str).expanduser() if path_str else default_path
        self.prompt_tab.set_file_path(str(path))
        self.prompt_tab.set_loading(True)
        self.prompt_tab.set_status("Đang lưu prompt…")

        no_entry = str(payload.get("no_entry", ""))
        entry_run = str(payload.get("entry_run", ""))
        auto_load = bool(payload.get("auto_load", self.prompt_tab.autoload_checkbox.isChecked()))

        def _job() -> dict[str, object]:
            path.parent.mkdir(parents=True, exist_ok=True)
            serialized = json.dumps(
                {
                    "no_entry": no_entry,
                    "entry_run": entry_run,
                    "auto_load": auto_load,
                },
                ensure_ascii=False,
                indent=2,
            )
            path.write_text(serialized, encoding="utf-8")
            return {"path": str(path), "auto_load": auto_load}

        def _on_result(payload: dict[str, object]) -> None:
            self.prompt_tab.set_loading(False)
            if "auto_load" in payload:
                self.prompt_tab.set_autoload(bool(payload["auto_load"]))
            message = f"Đã lưu prompt vào {payload.get('path', path)}"
            self.prompt_tab.set_status(message)
            self.statusBar().showMessage(message, 4000)

        def _on_error(exc: BaseException) -> None:
            self.prompt_tab.set_loading(False)
            message = f"Lỗi khi lưu prompt: {exc}"
            self.prompt_tab.set_status(message)
            self.statusBar().showMessage(message, 5000)

        self._submit_io_task(
            worker=_job,
            group="prompt",
            name="prompt.save",
            metadata={"component": "prompt", "operation": "save"},
            on_result=_on_result,
            on_error=_on_error,
        )

    def _handle_prompt_reformat(self, mode: str, raw_text: str) -> None:
        self.prompt_tab.set_loading(True)
        self.prompt_tab.set_status("Đang định dạng prompt…")

        def _job() -> str:
            return _normalize_prompt_text(raw_text)

        def _on_result(text: str) -> None:
            self.prompt_tab.set_loading(False)
            self.prompt_tab.set_prompt_content(mode, text)
            self.prompt_tab.set_status("Đã định dạng lại prompt.")
            self.statusBar().showMessage("Định dạng prompt hoàn tất.", 3000)

        def _on_error(exc: BaseException) -> None:
            self.prompt_tab.set_loading(False)
            message = f"Lỗi khi định dạng prompt: {exc}"
            self.prompt_tab.set_status(message)
            self.statusBar().showMessage(message, 5000)

        self._threading.submit(
            func=_job,
            group="prompt",
            name=f"prompt.reformat.{mode}",
            on_result=_on_result,
            on_error=_on_error,
        )

    def _handle_prompt_browse(self) -> None:
        default_dir = str(Path(self._config_state.prompt.file_path).expanduser().parent)
        path = self._dialogs.open_file(
            caption="Chọn tệp prompt",
            directory=default_dir,
            filter="Tệp JSON (*.json);;Tất cả tệp (*)",
        )
        if path:
            self._log_status(f"Đang tải prompt từ {path}…")
            self._handle_prompt_load(path)
        else:
            self.statusBar().showMessage("Đã hủy chọn tệp prompt.", 3000)

    # ------------------------------------------------------------------
    # Handlers cho tab Lịch sử
    # ------------------------------------------------------------------
    def _handle_history_refresh(self, kind: str) -> None:
        self.history_tab.set_loading(kind, True)
        label = "báo cáo" if kind == "reports" else "ngữ cảnh"
        self.history_tab.set_status(f"Đang quét {label} trong workspace…")
        base_folder = Path(self._config_state.folder.folder).expanduser()

        def _job() -> dict[str, object]:
            if not base_folder.exists():
                return {
                    "entries": [],
                    "status": f"Thư mục workspace không tồn tại: {base_folder}",
                }

            pattern = "report_*.md" if kind == "reports" else "ctx_*.json"
            collected: list[tuple[str, str, float]] = []
            for symbol_dir in base_folder.iterdir():
                if not symbol_dir.is_dir():
                    continue
                reports_dir = symbol_dir / "Reports"
                if not reports_dir.is_dir():
                    continue
                for file_path in reports_dir.glob(pattern):
                    try:
                        mtime = file_path.stat().st_mtime
                    except OSError:
                        mtime = 0.0
                    display = f"{symbol_dir.name}/{file_path.name}"
                    collected.append((str(file_path), display, mtime))

            collected.sort(key=lambda item: item[2], reverse=True)
            status = f"Tìm thấy {len(collected)} {label}."
            entries = [(path, display) for path, display, _ in collected]
            return {"entries": entries, "status": status}

        def _on_result(payload: dict[str, object]) -> None:
            self.history_tab.set_loading(kind, False)
            entries_data = list(payload.get("entries") or [])
            entries = [HistoryEntry(path=Path(path), display_name=display) for path, display in entries_data]
            self.history_tab.set_files(kind, entries)
            if not entries:
                self.history_tab.clear_preview()
            status = str(payload.get("status", "Đã quét xong."))
            self.history_tab.set_status(status)
            self.statusBar().showMessage(status, 4000)

        def _on_error(exc: BaseException) -> None:
            self.history_tab.set_loading(kind, False)
            message = f"Lỗi khi quét lịch sử: {exc}"
            self.history_tab.set_status(message)
            self.statusBar().showMessage(message, 5000)

        self._threading.submit(
            func=_job,
            group=f"history.{kind}",
            name=f"history.refresh.{kind}",
            on_result=_on_result,
            on_error=_on_error,
        )

    def _handle_history_preview(self, path_str: str) -> None:
        path = Path(path_str)
        if not path.exists():
            message = f"Tệp không tồn tại: {path.name}"
            self.history_tab.set_status(message)
            self.statusBar().showMessage(message, 4000)
            return

        self.history_tab.set_status(f"Đang đọc {path.name}…")

        def _job() -> str:
            return path.read_text(encoding="utf-8", errors="ignore")

        def _on_result(content: str) -> None:
            self.history_tab.set_preview_text(content)
            message = f"Đã tải nội dung {path.name}."
            self.history_tab.set_status(message)
            self.statusBar().showMessage(message, 4000)

        def _on_error(exc: BaseException) -> None:
            message = f"Lỗi khi đọc {path.name}: {exc}"
            self.history_tab.set_status(message)
            self.statusBar().showMessage(message, 5000)

        self._threading.submit(
            func=_job,
            group="history.preview",
            name="history.preview",
            on_result=_on_result,
            on_error=_on_error,
        )

    def _handle_history_open(self, path_str: str) -> None:
        path = Path(path_str)
        if not path.exists():
            self.statusBar().showMessage("Không thể mở: tệp không tồn tại.", 4000)
            return
        if path.suffix.lower() == ".json":
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                payload = path.read_text(encoding="utf-8", errors="ignore")
            dialog = self._dialogs.show_json_dialog(
                title=f"Ngữ cảnh: {path.name}",
                payload=payload,
            )
            self._register_dialog(dialog)
            return

        if self._dialogs.open_path(str(path.parent)):
            self._log_status(f"Đã mở thư mục chứa {path.name}.")
        else:
            self.statusBar().showMessage("Không thể mở thư mục trong hệ điều hành.", 5000)

    # ------------------------------------------------------------------
    # Handlers cho tab Tuỳ chọn
    # ------------------------------------------------------------------
    def _handle_options_changed(self, payload: dict[str, Any]) -> None:
        self._last_options_payload = payload
        new_state = self.snapshot_ui_state(options_payload=payload)
        self._config_state = new_state
        if self._apply_config:
            run_config = self._apply_config(new_state)
            self._run_config = run_config if run_config is not None else new_state.to_run_config()
        else:
            self._run_config = new_state.to_run_config()
        self._analysis_adapter.update_from_state(new_state, options_payload=payload)
        autorun_state = new_state.autorun
        self._autorun_enabled = bool(autorun_state.enabled)
        self._autorun_interval = int(autorun_state.interval_secs)
        self.overview_tab.set_autorun_state(autorun_state.enabled, autorun_state.interval_secs)
        self._update_services_config(new_state)
        if self._autorun_enabled:
            self._schedule_next_autorun(immediate=True)
        elif self._autorun_timer.isActive():
            self._autorun_timer.stop()
        sections = ", ".join(sorted(payload.keys())) if payload else ""
        message = "Đã cập nhật thông tin Options." if not sections else f"Đã cập nhật Options: {sections}."
        self.statusBar().showMessage(message, 3000)

    def _handle_options_load_env(self) -> None:
        self._log_status("Yêu cầu tải khóa API từ .env (sẽ được nối với logic thật ở Giai đoạn 4).")

    def _handle_options_save_safe(self) -> None:
        self._log_status("Yêu cầu lưu khóa API vào SafeData (sẽ triển khai ở Giai đoạn 4).")

    def _handle_options_delete_safe(self) -> None:
        self._log_status("Yêu cầu xoá khóa API đã lưu (sẽ triển khai ở Giai đoạn 4).")

    # ------------------------------------------------------------------
    # Autorun & vòng đời phiên phân tích
    # ------------------------------------------------------------------
    def _handle_autorun_timeout(self) -> None:
        if not self._autorun_enabled:
            return
        if self._is_running or self._pending_session:
            self._schedule_next_autorun()
            return
        folder = Path(self._analysis_adapter.folder_path.get()).expanduser()
        if not folder.exists():
            self.ui_status("Autorun bỏ qua: thư mục chưa hợp lệ.", running=False)
            self._schedule_next_autorun()
            return
        self._start_autorun_session()

    def _start_autorun_session(self) -> None:
        analysis_ctrl = self._controllers.analysis
        if not analysis_ctrl or not self._run_config:
            self._log_status("Autorun chưa khả dụng vì thiếu AnalysisController.")
            self._schedule_next_autorun()
            return
        if self._is_running or self._pending_session:
            self._schedule_next_autorun()
            return

        state = self.snapshot_ui_state()
        self._config_state = state
        self._analysis_adapter.update_from_state(state)
        if self._apply_config:
            run_config = self._apply_config(state)
            self._run_config = run_config if run_config is not None else state.to_run_config()
        else:
            self._run_config = state.to_run_config()
        run_config = self._run_config
        self._update_services_config(state)
        self._analysis_adapter.prepare_for_session()

        session_id = datetime.now().strftime("autorun-%Y%m%d-%H%M%S")
        self._pending_session = True
        self._analysis_adapter.stop_flag = False
        self.overview_tab.set_status("Đang chuẩn bị chạy autorun…", running=True)
        self._log_status(f"Autorun {session_id} đang khởi động.")

        def _on_start(sid: str, priority: str) -> None:
            self._queued_autorun_session = None
            self._handle_session_started(sid, priority, run_config, source="autorun")

        status = analysis_ctrl.enqueue_autorun(
            session_id,
            self._analysis_adapter,
            run_config,
            on_start=_on_start,
        )
        if status == "queued":
            self._queued_autorun_session = session_id
            self._pending_session = False
            self.ui_status("Autorun đã xếp hàng, sẽ chạy sau khi tác vụ hiện tại hoàn tất.", running=False)
            self._schedule_next_autorun()

    def _schedule_next_autorun(self, *, immediate: bool = False) -> None:
        if not self._autorun_enabled or self._is_running or self._pending_session:
            if self._autorun_timer.isActive():
                self._autorun_timer.stop()
            return
        delay_ms = max(1, self._autorun_interval) * 1000
        if immediate:
            delay_ms = min(delay_ms, 500)
        self._autorun_timer.start(delay_ms)
        self._log_status(f"Autorun sẽ kiểm tra lại sau {delay_ms / 1000:.0f} giây.")

    def _handle_session_started(self, session_id: str, priority: str, cfg: Any, *, source: str) -> None:
        self._is_running = True
        self._pending_session = False
        self._current_session_id = session_id
        self._run_config = cfg
        message = "Autorun đang chạy phân tích..." if priority == "autorun" else "Đang chạy phân tích..."
        self.overview_tab.set_status(message, running=True)
        self.statusBar().showMessage(message, 4000)
        self._log_status(f"Phiên {session_id} bắt đầu (priority={priority}, source={source}).")

    def _finalize_done(self) -> None:
        self._is_running = False
        self._pending_session = False
        self._current_session_id = None
        self._queued_autorun_session = None
        self._analysis_adapter.stop_flag = False
        self.ui_progress(None)
        self.overview_tab.set_status("Hoàn tất.", running=False)
        self._schedule_next_autorun()

    def _finalize_stopped(self) -> None:
        self._is_running = False
        self._pending_session = False
        self._current_session_id = None
        self._queued_autorun_session = None
        self._analysis_adapter.stop_flag = False
        self.ui_progress(None)
        self.overview_tab.set_status("Đã dừng bởi người dùng.", running=False)
        self._schedule_next_autorun()

    def _update_services_config(self, state: UiConfigState | None = None) -> None:
        state = state or self._config_state
        run_config = state.to_run_config()
        self._run_config = run_config
        news_service = self._controllers.news_service
        if news_service:
            news_service.update_config(run_config)
        news_ctrl = self._controllers.news
        if news_ctrl:
            if not self._news_polling_started:
                news_ctrl.start_polling(self._handle_news_payload)
                self._news_polling_started = True
            else:
                news_ctrl.trigger_autorun(force=True)

    # ------------------------------------------------------------------
    # Thu thập state phục vụ Giai đoạn 4 trở đi
    # ------------------------------------------------------------------
    def snapshot_ui_state(self, *, options_payload: dict[str, Any] | None = None) -> UiConfigState:
        """Dựng lại UiConfigState từ các widget PyQt6 hiện tại."""

        options = options_payload or self.options_tab.collect_payload()
        base = self._config_state

        folder_cfg = options.get("folder", {})
        folder_state = FolderConfig(
            folder=str(self._workspace_folder),
            delete_after=bool(folder_cfg.get("delete_after", base.folder.delete_after)),
            max_files=int(folder_cfg.get("max_files", base.folder.max_files)),
            only_generate_if_changed=bool(
                folder_cfg.get("only_generate_if_changed", base.folder.only_generate_if_changed)
            ),
        )

        upload_cfg = options.get("upload", {})
        upload_state = UploadConfig(
            upload_workers=int(upload_cfg.get("upload_workers", base.upload.upload_workers)),
            cache_enabled=bool(upload_cfg.get("cache_enabled", base.upload.cache_enabled)),
            optimize_lossless=bool(upload_cfg.get("optimize_lossless", base.upload.optimize_lossless)),
        )

        image_cfg = options.get("image_processing", {})
        image_state = ImageProcessingConfig(
            max_width=int(image_cfg.get("max_width", base.image_processing.max_width)),
            jpeg_quality=int(image_cfg.get("jpeg_quality", base.image_processing.jpeg_quality)),
        )

        api_cfg = options.get("api", {})
        api_state = ApiConfig(
            tries=int(api_cfg.get("tries", base.api.tries)),
            delay=float(api_cfg.get("delay", base.api.delay)),
        )

        context_cfg = options.get("context", {})
        context_state = ContextConfig(
            ctx_limit=int(context_cfg.get("ctx_limit", base.context.ctx_limit)),
            create_ctx_json=bool(context_cfg.get("create_ctx_json", base.context.create_ctx_json)),
            prefer_ctx_json=bool(context_cfg.get("prefer_ctx_json", base.context.prefer_ctx_json)),
            ctx_json_n=int(context_cfg.get("ctx_json_n", base.context.ctx_json_n)),
            remember_context=bool(context_cfg.get("remember_context", base.context.remember_context)),
            n_reports=int(context_cfg.get("n_reports", base.context.n_reports)),
        )

        telegram_cfg = options.get("telegram", {})
        telegram_state = TelegramConfig(
            enabled=bool(telegram_cfg.get("enabled", base.telegram.enabled)),
            token=str(telegram_cfg.get("token", base.telegram.token)),
            chat_id=str(telegram_cfg.get("chat_id", base.telegram.chat_id)),
            skip_verify=bool(telegram_cfg.get("skip_verify", base.telegram.skip_verify)),
            ca_path=str(telegram_cfg.get("ca_path", base.telegram.ca_path)),
            notify_on_early_exit=bool(
                telegram_cfg.get("notify_on_early_exit", base.telegram.notify_on_early_exit)
            ),
        )

        mt5_cfg = options.get("mt5", {})
        mt5_state = MT5Config(
            enabled=bool(mt5_cfg.get("enabled", base.mt5.enabled)),
            symbol=str(mt5_cfg.get("symbol", base.mt5.symbol)),
            n_M1=int(mt5_cfg.get("n_M1", base.mt5.n_M1)),
            n_M5=int(mt5_cfg.get("n_M5", base.mt5.n_M5)),
            n_M15=int(mt5_cfg.get("n_M15", base.mt5.n_M15)),
            n_H1=int(mt5_cfg.get("n_H1", base.mt5.n_H1)),
        )

        no_run_cfg = options.get("no_run", {})
        no_run_state = NoRunConfig(
            weekend_enabled=bool(no_run_cfg.get("weekend_enabled", base.no_run.weekend_enabled)),
            killzone_enabled=bool(no_run_cfg.get("killzone_enabled", base.no_run.killzone_enabled)),
            holiday_check_enabled=bool(no_run_cfg.get("holiday_check_enabled", base.no_run.holiday_check_enabled)),
            holiday_check_country=str(
                no_run_cfg.get("holiday_check_country", base.no_run.holiday_check_country)
            ),
            timezone=str(no_run_cfg.get("timezone", base.no_run.timezone)),
            killzone_summer=no_run_cfg.get("killzone_summer", base.no_run.killzone_summer),
            killzone_winter=no_run_cfg.get("killzone_winter", base.no_run.killzone_winter),
        )

        no_trade_cfg = options.get("no_trade", {})
        no_trade_state = NoTradeConfig(
            enabled=bool(no_trade_cfg.get("enabled", base.no_trade.enabled)),
            spread_max_pips=float(no_trade_cfg.get("spread_max_pips", base.no_trade.spread_max_pips)),
            min_atr_m5_pips=float(no_trade_cfg.get("min_atr_m5_pips", base.no_trade.min_atr_m5_pips)),
            min_dist_keylvl_pips=float(
                no_trade_cfg.get("min_dist_keylvl_pips", base.no_trade.min_dist_keylvl_pips)
            ),
            allow_session_asia=bool(
                no_trade_cfg.get("allow_session_asia", base.no_trade.allow_session_asia)
            ),
            allow_session_london=bool(
                no_trade_cfg.get("allow_session_london", base.no_trade.allow_session_london)
            ),
            allow_session_ny=bool(no_trade_cfg.get("allow_session_ny", base.no_trade.allow_session_ny)),
        )

        auto_trade_cfg = options.get("auto_trade", {})
        auto_trade_state = AutoTradeConfig(
            enabled=bool(auto_trade_cfg.get("enabled", base.auto_trade.enabled)),
            strict_bias=bool(auto_trade_cfg.get("strict_bias", base.auto_trade.strict_bias)),
            size_mode=str(auto_trade_cfg.get("size_mode", base.auto_trade.size_mode)),
            risk_per_trade=float(auto_trade_cfg.get("risk_per_trade", base.auto_trade.risk_per_trade)),
            split_tp_enabled=bool(
                auto_trade_cfg.get("split_tp_enabled", base.auto_trade.split_tp_enabled)
            ),
            split_tp_ratio=int(auto_trade_cfg.get("split_tp_ratio", base.auto_trade.split_tp_ratio)),
            deviation=int(auto_trade_cfg.get("deviation", base.auto_trade.deviation)),
            magic_number=int(auto_trade_cfg.get("magic_number", base.auto_trade.magic_number)),
            comment=str(auto_trade_cfg.get("comment", base.auto_trade.comment)),
            pending_ttl_min=int(auto_trade_cfg.get("pending_ttl_min", base.auto_trade.pending_ttl_min)),
            min_rr_tp2=float(auto_trade_cfg.get("min_rr_tp2", base.auto_trade.min_rr_tp2)),
            cooldown_min=int(auto_trade_cfg.get("cooldown_min", base.auto_trade.cooldown_min)),
            dynamic_pending=bool(auto_trade_cfg.get("dynamic_pending", base.auto_trade.dynamic_pending)),
            dry_run=bool(auto_trade_cfg.get("dry_run", base.auto_trade.dry_run)),
            move_to_be_after_tp1=bool(
                auto_trade_cfg.get("move_to_be_after_tp1", base.auto_trade.move_to_be_after_tp1)
            ),
            trailing_atr_mult=float(
                auto_trade_cfg.get("trailing_atr_mult", base.auto_trade.trailing_atr_mult)
            ),
            filling_type=str(auto_trade_cfg.get("filling_type", base.auto_trade.filling_type)),
        )

        news_cfg = options.get("news", {})
        priority = news_cfg.get("priority_keywords")
        priority_tuple: tuple[str, ...] | None
        if priority is None:
            priority_tuple = None
        else:
            priority_tuple = tuple(str(item) for item in priority)
        news_state = NewsConfig(
            block_enabled=bool(news_cfg.get("block_enabled", base.news.block_enabled)),
            block_before_min=int(news_cfg.get("block_before_min", base.news.block_before_min)),
            block_after_min=int(news_cfg.get("block_after_min", base.news.block_after_min)),
            cache_ttl_sec=int(news_cfg.get("cache_ttl_sec", base.news.cache_ttl_sec)),
            provider_timeout_sec=base.news.provider_timeout_sec,
            priority_keywords=priority_tuple,
            provider_error_threshold=int(
                news_cfg.get("provider_error_threshold", base.news.provider_error_threshold)
            ),
            provider_error_backoff_sec=int(
                news_cfg.get("provider_error_backoff_sec", base.news.provider_error_backoff_sec)
            ),
            surprise_score_threshold=float(
                news_cfg.get("surprise_score_threshold", base.news.surprise_score_threshold)
            ),
            currency_country_overrides=news_cfg.get(
                "currency_country_overrides", base.news.currency_country_overrides
            ),
            symbol_country_overrides=news_cfg.get(
                "symbol_country_overrides", base.news.symbol_country_overrides
            ),
        )

        fmp_cfg = options.get("fmp", {})
        fmp_state = FMPConfig(
            enabled=bool(fmp_cfg.get("enabled", base.fmp.enabled)),
            api_key=str(fmp_cfg.get("api_key", base.fmp.api_key)),
        )

        te_cfg = options.get("te", {})
        te_state = TEConfig(
            enabled=bool(te_cfg.get("enabled", base.te.enabled)),
            api_key=str(te_cfg.get("api_key", base.te.api_key)),
            skip_ssl_verify=bool(te_cfg.get("skip_ssl_verify", base.te.skip_ssl_verify)),
        )

        persistence_cfg = options.get("persistence", {})
        persistence_state = PersistenceConfig(
            max_md_reports=int(
                persistence_cfg.get("max_md_reports", base.persistence.max_md_reports)
            ),
            max_json_reports=base.persistence.max_json_reports,
        )

        chart_stream = self.chart_tab.current_config()
        chart_state = ChartConfig(
            timeframe=chart_stream.timeframe,
            num_candles=chart_stream.candles,
            chart_type=chart_stream.chart_type,
            refresh_interval_secs=self._config_state.chart.refresh_interval_secs,
        )

        prompt_state = self.prompt_tab.prompt_state()
        autorun_state = self.overview_tab.autorun_state()

        state = UiConfigState(
            folder=folder_state,
            upload=upload_state,
            image_processing=image_state,
            context=context_state,
            api=api_state,
            telegram=telegram_state,
            mt5=mt5_state,
            mt5_terminal_path=str(mt5_cfg.get("terminal_path", base.mt5_terminal_path)),
            no_run=no_run_state,
            no_trade=no_trade_state,
            auto_trade=auto_trade_state,
            news=news_state,
            persistence=persistence_state,
            fmp=fmp_state,
            te=te_state,
            chart=chart_state,
            model=self._config_state.model,
            autorun=autorun_state,
            prompt=prompt_state,
        )

        self._config_state = state
        self._last_options_payload = options
        return state

    def build_workspace_payload(self) -> dict[str, Any]:
        """Tạo payload workspace từ state hiện tại và nội dung prompt."""

        options = self._last_options_payload or self.options_tab.collect_payload()
        state = self.snapshot_ui_state(options_payload=options)
        payload = state.to_workspace_payload()

        prompt_payload = self.prompt_tab.prompt_payload()
        prompt_section = payload.setdefault("prompts", {})
        prompt_section["prompt_file_path"] = state.prompt.file_path
        prompt_section["auto_load_prompt_txt"] = state.prompt.auto_load_from_disk
        prompt_section["no_entry"] = str(prompt_payload.get("no_entry", ""))
        prompt_section["entry_run"] = str(prompt_payload.get("entry_run", ""))

        api_keys = options.get("api_keys")
        if api_keys:
            payload["api_keys"] = api_keys

        return payload

    # ------------------------------------------------------------------
    def _log_status(self, message: str) -> None:
        self.statusBar().showMessage(message, 4000)
        self._ui_bridge.post(lambda msg=message: self.overview_tab.append_log(msg))

    def _submit_io_task(
        self,
        *,
        worker: Callable[[], Any],
        group: str,
        name: str,
        metadata: dict[str, Any],
        on_result: Callable[[Any], None],
        on_error: Callable[[BaseException], None] | None = None,
    ) -> None:
        io_ctrl = self._controllers.io
        if io_ctrl:
            record = io_ctrl.run(
                worker=worker,
                group=group,
                name=name,
                metadata=metadata,
                cancel_previous=True,
            )
            if record:
                def _done(future) -> None:  # type: ignore[no-untyped-def]
                    try:
                        payload = future.result()
                    except Exception as exc:  # pragma: no cover - lỗi chuyển xuống callback
                        if on_error:
                            self._ui_bridge.post(lambda e=exc: on_error(e))
                    else:
                        self._ui_bridge.post(lambda payload=payload: on_result(payload))

                record.future.add_done_callback(_done)
                return

        self._threading.submit(
            func=worker,
            group=group,
            name=name,
            on_result=on_result,
            on_error=on_error,
        )

    def _register_dialog(self, dialog: QDialog) -> None:
        self._active_dialogs.append(dialog)

        def _cleanup(_: int) -> None:
            if dialog in self._active_dialogs:
                self._active_dialogs.remove(dialog)

        dialog.finished.connect(_cleanup)

    # ------------------------------------------------------------------
    # API công khai phục vụ các giai đoạn sau (tương thích Tkinter)
    # ------------------------------------------------------------------
    def ui_status(self, message: str, *, running: bool | None = None) -> None:
        """Cập nhật nhãn trạng thái và ghi lại nhật ký."""

        self.overview_tab.set_status(message, running=running)
        self.overview_tab.append_log(message)
        self.statusBar().showMessage(message, 4000)

    def ui_progress(self, value: float | None, *, indeterminate: bool = False) -> None:
        """Điều khiển thanh tiến trình giống phiên bản Tkinter."""

        if value is None:
            self.overview_tab.set_progress_visible(False)
            self.overview_tab.set_progress_indeterminate(False)
            return

        if indeterminate:
            self.overview_tab.set_progress_indeterminate(True)
        else:
            self.overview_tab.set_progress_indeterminate(False)
            self.overview_tab.set_progress_value(value)
        self.overview_tab.set_progress_visible(True)

    def ui_detail_replace(self, text: str) -> None:
        """Thay thế nội dung khu vực chi tiết báo cáo."""

        self.reports_tab.set_detail_text(text)

    def append_log(self, message: str) -> None:
        """Thêm thông điệp vào nhật ký tổng quan."""

        self.overview_tab.append_log(message)

    def show_error_message(self, title: str, message: str) -> None:
        """Hiển thị hộp thoại lỗi và ghi nhận log ngắn trên status bar."""

        self._dialogs.show_error(title=title, message=message)
        self.statusBar().showMessage(f"{title}: {message}", 5000)

    def show_info_message(self, title: str, message: str) -> None:
        """Hiển thị hộp thoại thông tin và cập nhật nhật ký."""

        self._dialogs.show_info(title=title, message=message)
        self.statusBar().showMessage(message, 4000)
