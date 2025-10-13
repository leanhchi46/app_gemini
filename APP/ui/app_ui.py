# -*- coding: utf-8 -*-
"""
Lớp giao diện người dùng chính (AppUI).

Chịu trách nhiệm khởi tạo, quản lý trạng thái và điều phối các sự kiện
từ giao diện người dùng, đồng thời ủy quyền các tác vụ xử lý logic
cho các thành phần khác như services, workers, và persistence handlers.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import threading
import tkinter as tk
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, ttk
from tkinter.scrolledtext import ScrolledText
from time import monotonic
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

from dotenv import load_dotenv
from google.api_core import exceptions

from APP.configs import workspace_config
from APP.configs.feature_flags import FEATURE_FLAGS
from APP.configs.app_config import (ApiConfig, AutoTradeConfig, ChartConfig,
                                    ContextConfig, FMPConfig, FolderConfig,
                                    ImageProcessingConfig, MT5Config,
                                    NewsConfig, NoRunConfig, NoTradeConfig,
                                    PersistenceConfig, RunConfig, TEConfig,
                                    TelegramConfig, UploadConfig)
from APP.configs.constants import FILES, MODELS, PATHS
from APP.services import gemini_service, mt5_service
from APP.services.news_service import DEFAULT_HIGH_IMPACT_KEYWORDS, NewsService
from APP.ui.components.chart_tab import ChartTab
from APP.ui.components.history_manager import HistoryManager
from APP.ui.components.news_tab import NewsTab
from APP.ui.components.prompt_manager import PromptManager
from APP.ui.utils import ui_builder
from APP.ui.utils.timeframe_detector import TimeframeDetector
from APP.ui.controllers import (AnalysisController, IOController,
                                MT5Controller, NewsController)
from APP.utils import general_utils
from APP.utils.safe_data import SafeData
from APP.utils.threading_utils import ThreadingManager

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class AppUI:
    """
    Lớp chính điều khiển giao diện và luồng hoạt động của ứng dụng.
    """

    def __init__(self, root: tk.Tk, initial_config: dict | None = None):
        """
        Khởi tạo giao diện chính và các biến trạng thái của ứng dụng.

        Args:
            root (tk.Tk): Đối tượng cửa sổ gốc của Tkinter.
            initial_config (dict | None): Cấu hình ban đầu được tải từ workspace.
        """
        logger.debug("Bắt đầu khởi tạo AppUI.")
        self.root = root
        self.initial_config = initial_config if initial_config is not None else {}
        self.root.title("TOOL GIAO DỊCH TỰ ĐỘNG")
        self.root.geometry("1180x780")
        self.root.minsize(1024, 660)

        # --- Attribute Declarations for Pyright ---
        self.run_config: Optional[RunConfig] = None
        self.telegram_client: Optional[Any] = None
        self.ff_cache_events_local: Optional[List[Dict[str, Any]]] = None
        self.config_path: Optional[Path] = None
        self.is_shutting_down: bool = False
        self.news_events: Optional[List[Dict[str, Any]]] = None
        self.news_fetch_time: Optional[float] = None
        self.news_service: Optional[NewsService] = None

        # Threading Manager
        self.threading_manager = ThreadingManager()
        self.feature_flags = FEATURE_FLAGS
        self.use_new_threading_stack = self.feature_flags.use_new_threading_stack

        # Component Managers (initialized below)
        self.history_manager: HistoryManager
        self.prompt_manager: PromptManager
        self.timeframe_detector: TimeframeDetector

        # Tkinter Variables (initialized in _init_tk_variables)
        self.folder_path: tk.StringVar
        self.status_var: tk.StringVar
        self.progress_var: tk.DoubleVar
        self.api_key_var: tk.StringVar
        self.fmp_api_key_var: tk.StringVar
        self.fmp_enabled_var: tk.BooleanVar
        self.te_api_key_var: tk.StringVar
        self.te_enabled_var: tk.BooleanVar
        self.model_var: tk.StringVar
        self.delete_after_var: tk.BooleanVar
        self.max_files_var: tk.IntVar
        self.autorun_var: tk.BooleanVar
        self.autorun_seconds_var: tk.IntVar
        self.remember_context_var: tk.BooleanVar
        self.context_n_reports_var: tk.IntVar
        self.context_limit_chars_var: tk.IntVar
        self.create_ctx_json_var: tk.BooleanVar
        self.prefer_ctx_json_var: tk.BooleanVar
        self.ctx_json_n_var: tk.IntVar
        self.telegram_enabled_var: tk.BooleanVar
        self.telegram_token_var: tk.StringVar
        self.telegram_chat_id_var: tk.StringVar
        self.telegram_skip_verify_var: tk.BooleanVar
        self.telegram_ca_path_var: tk.StringVar
        self.telegram_notify_early_exit_var: tk.BooleanVar
        self.mt5_enabled_var: tk.BooleanVar
        self.mt5_term_path_var: tk.StringVar
        self.mt5_symbol_var: tk.StringVar
        self.mt5_status_var: tk.StringVar
        self.mt5_n_M1: tk.IntVar
        self.mt5_n_M5: tk.IntVar
        self.mt5_n_M15: tk.IntVar
        self.mt5_n_H1: tk.IntVar
        self.no_run_weekend_enabled_var: tk.BooleanVar
        self.norun_killzone_var: tk.BooleanVar
        self.no_run_holiday_check_var: tk.BooleanVar
        self.no_trade_enabled_var: tk.BooleanVar
        self.nt_spread_max_pips_var: tk.DoubleVar
        self.nt_min_atr_m5_pips_var: tk.DoubleVar
        self.upload_workers_var: tk.IntVar
        self.cache_enabled_var: tk.BooleanVar
        self.optimize_lossless_var: tk.BooleanVar
        self.only_generate_if_changed_var: tk.BooleanVar
        self.image_max_width_var: tk.IntVar
        self.image_jpeg_quality_var: tk.IntVar
        self.api_tries_var: tk.IntVar
        self.api_delay_var: tk.DoubleVar
        self.auto_trade_enabled_var: tk.BooleanVar
        self.trade_strict_bias_var: tk.BooleanVar
        self.trade_size_mode_var: tk.StringVar
        self.trade_equity_risk_pct_var: tk.DoubleVar
        self.trade_split_tp1_pct_var: tk.IntVar
        self.trade_deviation_points_var: tk.IntVar
        self.trade_magic_var: tk.IntVar
        self.trade_comment_prefix_var: tk.StringVar
        self.trade_pending_ttl_min_var: tk.IntVar
        self.trade_min_rr_tp2_var: tk.DoubleVar
        self.trade_min_dist_keylvl_pips_var: tk.DoubleVar
        self.trade_cooldown_min_var: tk.IntVar
        self.trade_dynamic_pending_var: tk.BooleanVar
        self.auto_trade_dry_run_var: tk.BooleanVar
        self.trade_move_to_be_after_tp1_var: tk.BooleanVar
        self.trade_trailing_atr_mult_var: tk.DoubleVar
        self.trade_filling_type_var: tk.StringVar
        self.killzone_summer_vars: dict[str, dict[str, tk.StringVar]]
        self.killzone_winter_vars: dict[str, dict[str, tk.StringVar]]
        self.trade_allow_session_asia_var: tk.BooleanVar
        self.trade_allow_session_london_var: tk.BooleanVar
        self.trade_allow_session_ny_var: tk.BooleanVar
        self.news_block_enabled_var: tk.BooleanVar
        self.trade_news_block_before_min_var: tk.IntVar
        self.trade_news_block_after_min_var: tk.IntVar
        self.news_cache_ttl_var: tk.IntVar
        self.news_provider_var: tk.StringVar
        self.news_priority_keywords_var: tk.StringVar
        self.news_surprise_threshold_var: tk.DoubleVar
        self.news_provider_error_threshold_var: tk.IntVar
        self.news_provider_backoff_var: tk.IntVar
        self.news_currency_aliases_var: tk.StringVar
        self.news_symbol_overrides_var: tk.StringVar
        self.persistence_max_md_reports_var: tk.IntVar
        self.prompt_file_path_var: tk.StringVar
        self.auto_load_prompt_txt_var: tk.BooleanVar

        # Locks, Events, and Queues
        self._trade_log_lock = threading.Lock()
        self.ui_queue: queue.Queue[Any] = queue.Queue()
        self.ui_backlog_warn_threshold = 50
        self._last_ui_backlog_log = 0.0
        self._pending_session = False
        self._queued_autorun_session: Optional[str] = None

        # Facade điều phối đa luồng mới
        self.analysis_controller = AnalysisController(self.threading_manager, self.ui_queue)
        self.news_service = NewsService()
        self.news_service.set_update_callback(self._on_news_updated)
        self.news_controller = NewsController(
            threading_manager=self.threading_manager,
            news_service=self.news_service,
            ui_queue=self.ui_queue,
            backlog_limit=50,
        )
        self.io_controller = IOController(self.threading_manager, enabled=self.use_new_threading_stack)
        self.mt5_controller = MT5Controller(self.threading_manager, enabled=self.use_new_threading_stack)
        self._current_session_id: Optional[str] = None
        self._news_polling_started = False

        # UI Widget Attributes (khai báo trước để pyright nhận diện)
        self.tree: Optional[ttk.Treeview] = None
        self.detail_text: Optional[tk.Text] = None
        self.nb: Optional[ttk.Notebook] = None
        self.prompt_nb: Optional[ttk.Notebook] = None
        self.model_combo: Optional[ttk.Combobox] = None
        self.api_entry: Optional[tk.Entry] = None
        self.fmp_api_entry: Optional[tk.Entry] = None
        self.fmp_enabled_check: Optional[ttk.Checkbutton] = None
        self.te_api_entry: Optional[tk.Entry] = None
        self.te_enabled_check: Optional[ttk.Checkbutton] = None
        self.prompt_entry_run_text: Optional[tk.Text] = None
        self.prompt_no_entry_text: Optional[tk.Text] = None
        self.start_btn: Optional[ttk.Button] = None
        self.stop_btn: Optional[ttk.Button] = None
        self.save_ws_btn: Optional[ttk.Button] = None
        self.load_ws_btn: Optional[ttk.Button] = None
        self.delete_ws_btn: Optional[ttk.Button] = None
        self.choose_folder_btn: Optional[ttk.Button] = None
        self.folder_label: Optional[ttk.Entry] = None
        self.autorun_interval_spin: Optional[ttk.Spinbox] = None
        self.chart_tab: Optional[ChartTab] = None
        self.news_tab: Optional[NewsTab] = None
        self.history_list: Optional[tk.Listbox] = None
        self.json_list: Optional[tk.Listbox] = None

        # Thêm khai báo cho các widget tin tức
        self.news_card: Optional[ttk.LabelFrame] = None
        self.news_block_check: Optional[ttk.Checkbutton] = None
        self.news_before_spin: Optional[ttk.Spinbox] = None
        self.news_after_spin: Optional[ttk.Spinbox] = None
        self.news_cache_spin: Optional[ttk.Spinbox] = None
        self.news_provider_combo: Optional[ttk.Combobox] = None
        self.news_keywords_entry: Optional[ttk.Entry] = None
        self.news_surprise_spin: Optional[ttk.Spinbox] = None
        self.news_error_threshold_spin: Optional[ttk.Spinbox] = None
        self.news_backoff_spin: Optional[ttk.Spinbox] = None
        self.news_currency_aliases_text: Optional[ScrolledText] = None  # type: ignore[name-defined]
        self.news_symbol_overrides_text: Optional[ScrolledText] = None  # type: ignore[name-defined]


        # State Variables
        self.is_running = False
        self.stop_flag = False
        self.results: list[dict] = []
        self.combined_report_text = ""
        self._autorun_job: Optional[str] = None
        self._mt5_reconnect_job: Optional[str] = None
        self._mt5_check_connection_job: Optional[str] = None

        # Initialize Tkinter variables
        self._init_tk_variables()

        # Initialize component managers BEFORE building the UI
        # This is crucial because the UI builder needs access to these managers.
        self.history_manager = HistoryManager(self)
        self.prompt_manager = PromptManager(self)
        self.timeframe_detector = TimeframeDetector()

        # Build the UI layout
        ui_builder.build_ui(self)

        # Sửa lỗi: Liên kết các widget UI với HistoryManager SAU KHI chúng đã được tạo.
        self.history_manager.link_ui_widgets()

        # Post-UI setup
        self._configure_gemini_api_and_update_ui()
        self.apply_config(self.initial_config)
        ui_builder.poll_ui_queue(self)
        self._schedule_mt5_connection_check()

        # Load initial data through managers
        self.prompt_manager.load_prompts_from_disk()

        # Xóa bỏ làm mới tự động khi khởi động để tránh race condition.
        # Việc làm mới sẽ được thực hiện sau khi người dùng chọn thư mục hoặc tải workspace.
        
        # Cải tiến: Kiểm tra API key sau khi UI đã sẵn sàng
        self._check_api_key_on_startup()

        self.root.protocol("WM_DELETE_WINDOW", self.shutdown)
        logger.debug("AppUI đã khởi tạo xong.")

    def _run_in_background(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Future:
        """
        Chạy worker nền thông qua IOController để thống nhất logging/feature flag.
        """

        task_name = getattr(func, "__name__", "anonymous")
        record = self.io_controller.run(
            worker=func,
            args=args,
            kwargs=kwargs,
            group="ui.misc",
            name=f"ui.misc.{task_name}",
            metadata={"component": "ui", "operation": task_name},
        )
        if record:
            return record.future
        return self.threading_manager.submit_task(func, *args, **kwargs)

    def _check_api_key_on_startup(self):
        """
        Kiểm tra API key khi khởi động và thông báo cho người dùng nếu nó không hợp lệ.
        """
        api_key = self.api_key_var.get()
        # Chỉ hiển thị cảnh báo nếu không có key nào được tìm thấy từ cả file đã lưu và biến môi trường.
        if not api_key:
            # Sử dụng 'after' để đảm bảo cửa sổ chính đã sẵn sàng trước khi hiển thị popup.
            self.root.after(
                200,
                lambda: self.show_error_message(
                    "Thiếu API Key",
                    "Không tìm thấy Google AI API Key.\n\n"
                    "Lý do có thể là:\n"
                    "- Đây là lần chạy đầu tiên.\n"
                    "- File API key đã lưu bị hỏng hoặc không tương thích.\n\n"
                    "Vui lòng nhập API key của bạn trong tab 'Cài đặt' và bấm 'Lưu Key An Toàn'.",
                ),
            )

    def shutdown(self):
        """
        Xử lý sự kiện đóng cửa sổ ứng dụng một cách an toàn (graceful shutdown).
        """
        if self.is_shutting_down:
            return
        self.is_shutting_down = True
        logger.info("Bắt đầu quy trình tắt ứng dụng an toàn.")

        shutdown_dialog = ui_builder.create_shutdown_dialog(self.root) if self.use_new_threading_stack else None
        if shutdown_dialog:
            shutdown_dialog.update_progress("Đang chuẩn bị dừng các tác vụ nền...", 5)

        # 1. Dừng các tác vụ lặp lại
        if self._autorun_job:
            self.root.after_cancel(self._autorun_job)
        if self._mt5_check_connection_job:
            self.root.after_cancel(self._mt5_check_connection_job)

        # 2. Gửi tín hiệu dừng cho các controller nền
        if self._current_session_id:
            logger.info("Yêu cầu hủy session phân tích %s trong quá trình shutdown.", self._current_session_id)
            self.stop_flag = True
            self.analysis_controller.stop_session(self._current_session_id)

        if self.news_controller:
            self.news_controller.stop_polling()

        # 3. Dừng các thành phần UI phụ thuộc controller
        if self.chart_tab:
            self.chart_tab.stop()

        if shutdown_dialog:
            shutdown_dialog.update_progress("Đang lưu cấu hình và ngắt kết nối...", 25)

        # 4. Lưu cấu hình
        try:
            config_data = self._collect_config_data()
            workspace_config.save_config_to_file(config_data)
            logger.info("Đã lưu cấu hình workspace thành công.")
        except Exception:
            logger.exception("Lỗi khi lưu cấu hình workspace trong quá trình tắt.")

        # 5. Ngắt kết nối MT5
        mt5_service.shutdown()

        backlog = self.ui_queue.qsize()
        logger.info("UI queue backlog khi shutdown: %s", backlog)
        if backlog > self.ui_backlog_warn_threshold:
            logger.warning("UI queue backlog vượt ngưỡng trong quá trình shutdown.")

        if shutdown_dialog:
            shutdown_dialog.update_progress("Đang chờ tác vụ nền hoàn tất...", 60)

        # 6. Chờ các nhóm task nền hoàn tất trước khi tắt executor
        self.threading_manager.await_idle("analysis.session", timeout=10.0)
        self.threading_manager.await_idle("analysis.upload", timeout=5.0)
        self.threading_manager.await_idle("news.polling", timeout=5.0)
        self.threading_manager.await_idle("chart.refresh", timeout=5.0)
        self.threading_manager.shutdown(wait=True, timeout=5.0)

        if shutdown_dialog:
            try:
                shutdown_dialog.update_progress("Hoàn tất. Đang đóng cửa sổ...", 95)
            except tk.TclError:
                logger.debug("Không thể cập nhật tiến trình shutdown do cửa sổ đã bị hủy.")

        # 7. Đóng hộp thoại shutdown (nếu có) trước khi phá hủy root để tránh lỗi grab.
        if shutdown_dialog:
            try:
                shutdown_dialog.close()
            except tk.TclError:
                logger.debug("Hộp thoại shutdown đã bị hủy trước khi đóng.")

        # 8. Phá hủy cửa sổ UI chính
        root_destroy = getattr(self.root, "destroy", None)
        if callable(root_destroy):
            should_destroy = True
            winfo_exists = getattr(self.root, "winfo_exists", None)
            if callable(winfo_exists):
                try:
                    should_destroy = bool(winfo_exists())
                except tk.TclError:
                    logger.debug("Không thể kiểm tra trạng thái tồn tại của root, vẫn tiến hành destroy().")
                    should_destroy = True

            if should_destroy:
                try:
                    root_destroy()
                except tk.TclError:
                    logger.debug("Destroy root thất bại do cửa sổ đã đóng.")
            else:
                logger.debug("Cửa sổ root đã bị hủy trước khi gọi destroy().")
        else:
            logger.debug("Root không hỗ trợ destroy(), bỏ qua bước phá hủy.")
        logger.info("Ứng dụng đã đóng thành công.")

    def _init_tk_variables(self):
        """
        Khởi tạo tất cả các biến trạng thái của Tkinter.
        """
        logger.debug("Khởi tạo các biến Tkinter.")
        # General
        self.folder_path = tk.StringVar(value="")
        # NOTE: Đã xóa trace không chính xác từ folder_path để tránh lỗi khi khởi động
        self.status_var = tk.StringVar(value="Sẵn sàng.")
        self.progress_var = tk.DoubleVar(value=0.0)

        # API & Model
        import json
        api_keys = {
            "google": os.environ.get("GOOGLE_API_KEY", ""),
            "fmp": os.environ.get("FMP_API_KEY", ""),
            "te": os.environ.get("TE_API_KEY", ""),
        }
        if PATHS.ALL_API_KEYS_ENC.exists():
            try:
                decrypted_json = general_utils.deobfuscate_text(
                    PATHS.ALL_API_KEYS_ENC.read_text(encoding="utf-8"), "all_api_keys_salt"
                )
                stored_keys = json.loads(decrypted_json)
                api_keys.update(stored_keys)
            except (json.JSONDecodeError, TypeError):
                logger.warning("Không thể đọc file API keys đã mã hóa, có thể file bị hỏng.")
        # Fallback cho phiên bản cũ
        elif PATHS.API_KEY_ENC.exists():
            api_keys["google"] = general_utils.deobfuscate_text(
                PATHS.API_KEY_ENC.read_text(encoding="utf-8"), "api_key_salt"
            )

        self.api_key_var = tk.StringVar(value=api_keys.get("google", ""))
        self.fmp_api_key_var = tk.StringVar(value=api_keys.get("fmp", ""))
        self.fmp_enabled_var = tk.BooleanVar(value=False)
        self.te_api_key_var = tk.StringVar(value=api_keys.get("te", ""))
        self.te_enabled_var = tk.BooleanVar(value=False)
        self.te_skip_ssl_var = tk.BooleanVar(value=False)

        # Thêm trace để cập nhật UI khi nhà cung cấp tin tức thay đổi
        self.fmp_enabled_var.trace_add("write", lambda *args: self._update_news_widgets_state())
        self.te_enabled_var.trace_add("write", lambda *args: self._update_news_widgets_state())

        self.model_var = tk.StringVar(value=MODELS.DEFAULT_VISION)
        self.api_key_var.trace_add("write", lambda *args: self._configure_gemini_api_and_update_ui())

        # Folder & Run
        self.delete_after_var = tk.BooleanVar(value=True)
        self.max_files_var = tk.IntVar(value=0)
        self.autorun_var = tk.BooleanVar(value=False)
        self.autorun_seconds_var = tk.IntVar(value=60)

        # Context
        self.remember_context_var = tk.BooleanVar(value=True)
        self.context_n_reports_var = tk.IntVar(value=1)
        self.context_limit_chars_var = tk.IntVar(value=2000)
        self.create_ctx_json_var = tk.BooleanVar(value=True)
        self.prefer_ctx_json_var = tk.BooleanVar(value=True)
        self.ctx_json_n_var = tk.IntVar(value=5)

        # Telegram
        self.telegram_enabled_var = tk.BooleanVar(value=False)
        self.telegram_token_var = tk.StringVar(value="")
        self.telegram_chat_id_var = tk.StringVar(value="")
        self.telegram_skip_verify_var = tk.BooleanVar(value=False)
        self.telegram_ca_path_var = tk.StringVar(value="")
        self.telegram_notify_early_exit_var = tk.BooleanVar(value=True)

        # MT5
        self.mt5_enabled_var = tk.BooleanVar(value=False)
        self.mt5_term_path_var = tk.StringVar(value="")
        self.mt5_symbol_var = tk.StringVar(value="")
        self.mt5_symbol_var.trace_add("write", self._on_symbol_changed)
        self.mt5_status_var = tk.StringVar(value="MT5: Chưa kết nối")
        self.mt5_n_M1 = tk.IntVar(value=120)
        self.mt5_n_M5 = tk.IntVar(value=180)
        self.mt5_n_M15 = tk.IntVar(value=96)
        self.mt5_n_H1 = tk.IntVar(value=120)

        # No-Run / No-Trade Conditions
        self.no_run_weekend_enabled_var = tk.BooleanVar(value=True)
        self.norun_killzone_var = tk.BooleanVar(value=True)
        self.no_run_holiday_check_var = tk.BooleanVar(value=True)
        self.no_run_holiday_country_var = tk.StringVar(value="US")
        self.no_run_timezone_var = tk.StringVar(value="Asia/Ho_Chi_Minh")

        sessions = ["asia", "london", "newyork_am", "newyork_pm"]
        self.killzone_summer_vars = {}
        self.killzone_winter_vars = {}
        for session in sessions:
            summer_defaults = mt5_service.DEFAULT_KILLZONE_SUMMER.get(session, {})
            winter_defaults = mt5_service.DEFAULT_KILLZONE_WINTER.get(session, {})
            self.killzone_summer_vars[session] = {
                "start": tk.StringVar(value=summer_defaults.get("start", "")),
                "end": tk.StringVar(value=summer_defaults.get("end", "")),
            }
            self.killzone_winter_vars[session] = {
                "start": tk.StringVar(value=winter_defaults.get("start", "")),
                "end": tk.StringVar(value=winter_defaults.get("end", "")),
            }

        self.no_trade_enabled_var = tk.BooleanVar(value=True)
        self.nt_spread_max_pips_var = tk.DoubleVar(value=2.5)
        self.nt_min_atr_m5_pips_var = tk.DoubleVar(value=3.0)

        # Upload & Image Processing
        self.upload_workers_var = tk.IntVar(value=4)
        self.cache_enabled_var = tk.BooleanVar(value=True)
        self.optimize_lossless_var = tk.BooleanVar(value=False)
        self.only_generate_if_changed_var = tk.BooleanVar(value=False)

        # Image Processing & API
        self.image_max_width_var = tk.IntVar(value=1600)
        self.image_jpeg_quality_var = tk.IntVar(value=85)
        self.api_tries_var = tk.IntVar(value=5)
        self.api_delay_var = tk.DoubleVar(value=2.0)

        # Auto-Trade
        self.auto_trade_enabled_var = tk.BooleanVar(value=False)
        self.trade_strict_bias_var = tk.BooleanVar(value=True)
        self.trade_size_mode_var = tk.StringVar(value="risk_percent")
        self.trade_equity_risk_pct_var = tk.DoubleVar(value=0.5)
        self.trade_split_tp1_pct_var = tk.IntVar(value=50)
        self.trade_deviation_points_var = tk.IntVar(value=20)
        self.trade_magic_var = tk.IntVar(value=26092025)
        self.trade_comment_prefix_var = tk.StringVar(value="AI-ICT")
        self.trade_pending_ttl_min_var = tk.IntVar(value=90)
        self.trade_min_rr_tp2_var = tk.DoubleVar(value=2.0)
        self.trade_min_dist_keylvl_pips_var = tk.DoubleVar(value=5.0)
        self.trade_cooldown_min_var = tk.IntVar(value=10)
        self.trade_dynamic_pending_var = tk.BooleanVar(value=True)
        self.auto_trade_dry_run_var = tk.BooleanVar(value=False)
        self.trade_move_to_be_after_tp1_var = tk.BooleanVar(value=True)
        self.trade_trailing_atr_mult_var = tk.DoubleVar(value=0.5)
        self.trade_filling_type_var = tk.StringVar(value="IOC")
        self.trade_allow_session_asia_var = tk.BooleanVar(value=True)
        self.trade_allow_session_london_var = tk.BooleanVar(value=True)
        self.trade_allow_session_ny_var = tk.BooleanVar(value=True)

        # News
        self.news_block_enabled_var = tk.BooleanVar(value=True)
        self.trade_news_block_before_min_var = tk.IntVar(value=15)
        self.trade_news_block_after_min_var = tk.IntVar(value=15)
        self.news_cache_ttl_var = tk.IntVar(value=300)
        self.news_provider_var = tk.StringVar(value="FMP")
        self.news_priority_keywords_var = tk.StringVar(
            value=", ".join(sorted(DEFAULT_HIGH_IMPACT_KEYWORDS))
        )
        self.news_surprise_threshold_var = tk.DoubleVar(value=0.5)
        self.news_provider_error_threshold_var = tk.IntVar(value=2)
        self.news_provider_backoff_var = tk.IntVar(value=300)
        self.news_currency_aliases_var = tk.StringVar(value="")
        self.news_symbol_overrides_var = tk.StringVar(value="")

        # Persistence
        self.persistence_max_md_reports_var = tk.IntVar(value=10)

        # Prompts
        self.prompt_file_path_var = tk.StringVar(value="")
        self.auto_load_prompt_txt_var = tk.BooleanVar(value=True)
        logger.debug("Các biến Tkinter đã được khởi tạo.")

    def _gather_killzone_schedule(
        self, var_map: dict[str, dict[str, tk.StringVar]]
    ) -> dict[str, dict[str, str]] | None:
        schedule: dict[str, dict[str, str]] = {}
        for session, pair in var_map.items():
            start_val = pair["start"].get().strip()
            end_val = pair["end"].get().strip()
            if start_val and end_val:
                schedule[session] = {"start": start_val, "end": end_val}
        return schedule or None

    def _apply_killzone_schedule(
        self,
        var_map: dict[str, dict[str, tk.StringVar]],
        data: dict[str, dict[str, str]] | None,
        defaults: dict[str, dict[str, str]],
    ) -> None:
        for session, pair in var_map.items():
            default_window = defaults.get(session, {})
            target_window = (data or {}).get(session, {})
            start_val = target_window.get("start", default_window.get("start", ""))
            end_val = target_window.get("end", default_window.get("end", ""))
            pair["start"].set(start_val)
            pair["end"].set(end_val)

    def _get_text_widget_content(
        self, widget: ScrolledText | None, fallback_var: tk.StringVar
    ) -> str:
        if widget is None:
            return fallback_var.get().strip()
        return widget.get("1.0", tk.END).strip()

    def _set_text_widget_content(self, widget: ScrolledText | None, content: str) -> None:
        if widget is None:
            return
        widget.config(state=tk.NORMAL)
        widget.delete("1.0", tk.END)
        if content:
            widget.insert("1.0", content)
        widget.config(state=tk.NORMAL)

    def _parse_priority_keywords(self, raw: str) -> list[str]:
        text = raw.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                keywords = [str(item).strip() for item in parsed if str(item).strip()]
                return keywords
        except json.JSONDecodeError:
            pass
        return [kw.strip() for kw in text.split(",") if kw.strip()]

    def _parse_mapping_string(
        self, raw: str
    ) -> dict[str, list[str]] | None:
        text = raw.strip()
        if not text:
            return None
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            logger.warning("Không thể parse JSON mapping tin tức: %s", exc)
            return None
        if not isinstance(parsed, dict):
            logger.warning("JSON mapping tin tức phải là đối tượng dict, nhận %s", type(parsed))
            return None
        normalized: dict[str, list[str]] = {}
        for key, value in parsed.items():
            if not key:
                continue
            if isinstance(value, (list, tuple, set)):
                cleaned = [str(item).strip() for item in value if str(item).strip()]
            else:
                cleaned = [str(value).strip()] if str(value).strip() else []
            if cleaned:
                normalized[key.strip().upper()] = cleaned
        return normalized or None

    def _collect_config_data(self) -> dict:
        """
        Thu thập tất cả các giá trị cấu hình từ các biến Tkinter và trả về một dictionary.
        """
        logger.debug("Bắt đầu thu thập dữ liệu cấu hình từ UI.")
        summer_schedule = self._gather_killzone_schedule(self.killzone_summer_vars)
        winter_schedule = self._gather_killzone_schedule(self.killzone_winter_vars)
        currency_aliases_raw = self._get_text_widget_content(
            self.news_currency_aliases_text, self.news_currency_aliases_var
        )
        symbol_overrides_raw = self._get_text_widget_content(
            self.news_symbol_overrides_text, self.news_symbol_overrides_var
        )
        self.news_currency_aliases_var.set(currency_aliases_raw)
        self.news_symbol_overrides_var.set(symbol_overrides_raw)
        keywords_list = self._parse_priority_keywords(self.news_priority_keywords_var.get())
        currency_aliases = self._parse_mapping_string(currency_aliases_raw)
        symbol_overrides = self._parse_mapping_string(symbol_overrides_raw)
        no_run_config: dict[str, Any] = {
            "weekend_enabled": self.no_run_weekend_enabled_var.get(),
            "killzone_enabled": self.norun_killzone_var.get(),
            "holiday_check_enabled": self.no_run_holiday_check_var.get(),
            "holiday_check_country": self.no_run_holiday_country_var.get(),
            "timezone": self.no_run_timezone_var.get(),
        }
        if summer_schedule:
            no_run_config["killzone_summer"] = summer_schedule
        if winter_schedule:
            no_run_config["killzone_winter"] = winter_schedule

        return {
            "folder": {
                "folder_path": self.folder_path.get().strip(),
                "delete_after": self.delete_after_var.get(),
                "max_files": self.max_files_var.get(),
                "only_generate_if_changed": self.only_generate_if_changed_var.get(),
            },
            "upload": {
                "upload_workers": self.upload_workers_var.get(),
                "cache_enabled": self.cache_enabled_var.get(),
                "optimize_lossless": self.optimize_lossless_var.get(),
            },
            "image_processing": {
                "max_width": self.image_max_width_var.get(),
                "jpeg_quality": self.image_jpeg_quality_var.get(),
            },
            "api": {
                "tries": self.api_tries_var.get(),
                "delay": self.api_delay_var.get(),
            },
            "fmp": {
                "enabled": self.fmp_enabled_var.get(),
                "api_key": self.fmp_api_key_var.get().strip(),
            },
            "te": {
                "enabled": self.te_enabled_var.get(),
                "api_key": self.te_api_key_var.get().strip(),
                "skip_ssl_verify": self.te_skip_ssl_var.get(),
            },
            "context": {
                "ctx_limit": self.context_limit_chars_var.get(),
                "create_ctx_json": self.create_ctx_json_var.get(),
                "prefer_ctx_json": self.prefer_ctx_json_var.get(),
                "ctx_json_n": self.ctx_json_n_var.get(),
                "remember_context": self.remember_context_var.get(),
                "n_reports": self.context_n_reports_var.get(),
            },
            "telegram": {
                "enabled": self.telegram_enabled_var.get(),
                "token": self.telegram_token_var.get().strip(),
                "chat_id": self.telegram_chat_id_var.get().strip(),
                "skip_verify": self.telegram_skip_verify_var.get(),
                "ca_path": self.telegram_ca_path_var.get().strip(),
                "notify_on_early_exit": self.telegram_notify_early_exit_var.get(),
            },
            "mt5": {
                "enabled": self.mt5_enabled_var.get(),
                "terminal_path": self.mt5_term_path_var.get().strip(),
                "symbol": self.mt5_symbol_var.get().strip(),
                "n_M1": self.mt5_n_M1.get(),
                "n_M5": self.mt5_n_M5.get(),
                "n_M15": self.mt5_n_M15.get(),
                "n_H1": self.mt5_n_H1.get(),
            },
            "no_run": no_run_config,
            "no_trade": {
                "enabled": self.no_trade_enabled_var.get(),
                "spread_max_pips": self.nt_spread_max_pips_var.get(),
                "min_atr_m5_pips": self.nt_min_atr_m5_pips_var.get(),
                "min_dist_keylvl_pips": self.trade_min_dist_keylvl_pips_var.get(),
                "allow_session_asia": self.trade_allow_session_asia_var.get(),
                "allow_session_london": self.trade_allow_session_london_var.get(),
                "allow_session_ny": self.trade_allow_session_ny_var.get(),
            },
            "auto_trade": {
                "enabled": self.auto_trade_enabled_var.get(),
                "strict_bias": self.trade_strict_bias_var.get(),
                "size_mode": self.trade_size_mode_var.get(),
                "risk_per_trade": self.trade_equity_risk_pct_var.get(),
                "split_tp_enabled": self.trade_split_tp1_pct_var.get() > 0,
                "split_tp_ratio": self.trade_split_tp1_pct_var.get(),
                "deviation": self.trade_deviation_points_var.get(),
                "magic_number": self.trade_magic_var.get(),
                "comment": self.trade_comment_prefix_var.get(),
                "pending_ttl_min": self.trade_pending_ttl_min_var.get(),
                "min_rr_tp2": self.trade_min_rr_tp2_var.get(),
                "cooldown_min": self.trade_cooldown_min_var.get(),
                "dynamic_pending": self.trade_dynamic_pending_var.get(),
                "dry_run": self.auto_trade_dry_run_var.get(),
                "move_to_be_after_tp1": self.trade_move_to_be_after_tp1_var.get(),
                "trailing_atr_mult": self.trade_trailing_atr_mult_var.get(),
                "filling_type": self.trade_filling_type_var.get(),
            },
            "news": {
                "block_enabled": self.news_block_enabled_var.get(),
                "block_before_min": self.trade_news_block_before_min_var.get(),
                "block_after_min": self.trade_news_block_after_min_var.get(),
                "cache_ttl_sec": self.news_cache_ttl_var.get(),
                "priority_keywords": keywords_list,
                "surprise_score_threshold": self.news_surprise_threshold_var.get(),
                "provider_error_threshold": self.news_provider_error_threshold_var.get(),
                "provider_error_backoff_sec": self.news_provider_backoff_var.get(),
                "currency_country_overrides": currency_aliases,
                "symbol_country_overrides": symbol_overrides,
            },
            "persistence": {
                "max_md_reports": self.persistence_max_md_reports_var.get(),
            },
            "prompts": {
                "prompt_file_path": self.prompt_file_path_var.get().strip(),
                "auto_load_prompt_txt": self.auto_load_prompt_txt_var.get(),
            },
            "model": self.model_var.get(),
            "autorun": self.autorun_var.get(),
            "autorun_secs": self.autorun_seconds_var.get(),
            # Thêm thu thập dữ liệu từ ChartTab
            "chart": {
                "timeframe": self.chart_tab.tf_var.get() if self.chart_tab else "M15",
                "num_candles": self.chart_tab.n_candles_var.get() if self.chart_tab else 150,
                "chart_type": self.chart_tab.chart_type_var.get() if self.chart_tab else "Nến",
                "refresh_interval_secs": self.chart_tab.refresh_secs_var.get() if self.chart_tab else 5,
            },
        }

    def apply_config(self, config_data: dict):
        """
        Áp dụng các giá trị từ dictionary cấu hình lên các biến Tkinter của UI.
        """
        logger.debug("Bắt đầu áp dụng cấu hình lên UI.")

        # Helper to safely get nested keys
        def get_nested(data, keys, default):
            for key in keys:
                if isinstance(data, dict) and key in data:
                    data = data[key]
                else:
                    return default
            return data

        # Apply config group by group
        folder_cfg = config_data.get("folder", {})
        self.delete_after_var.set(get_nested(folder_cfg, ["delete_after"], True))
        self.max_files_var.set(get_nested(folder_cfg, ["max_files"], 0))
        self.only_generate_if_changed_var.set(get_nested(folder_cfg, ["only_generate_if_changed"], False))
        folder_path = get_nested(folder_cfg, ["folder_path"], "")
        if folder_path and Path(folder_path).exists():
            self.folder_path.set(folder_path)
            self._load_files(folder_path)

        upload_cfg = config_data.get("upload", {})
        self.upload_workers_var.set(get_nested(upload_cfg, ["upload_workers"], 4))
        self.cache_enabled_var.set(get_nested(upload_cfg, ["cache_enabled"], True))
        self.optimize_lossless_var.set(get_nested(upload_cfg, ["optimize_lossless"], False))

        image_cfg = config_data.get("image_processing", {})
        self.image_max_width_var.set(get_nested(image_cfg, ["max_width"], 1600))
        self.image_jpeg_quality_var.set(get_nested(image_cfg, ["jpeg_quality"], 85))

        api_cfg = config_data.get("api", {})
        self.api_tries_var.set(get_nested(api_cfg, ["tries"], 5))
        self.api_delay_var.set(get_nested(api_cfg, ["delay"], 2.0))

        context_cfg = config_data.get("context", {})
        self.context_limit_chars_var.set(get_nested(context_cfg, ["ctx_limit"], 2000))
        self.create_ctx_json_var.set(get_nested(context_cfg, ["create_ctx_json"], True))
        self.prefer_ctx_json_var.set(get_nested(context_cfg, ["prefer_ctx_json"], True))
        self.ctx_json_n_var.set(get_nested(context_cfg, ["ctx_json_n"], 5))
        self.remember_context_var.set(get_nested(context_cfg, ["remember_context"], True))
        self.context_n_reports_var.set(get_nested(context_cfg, ["n_reports"], 1))

        telegram_cfg = config_data.get("telegram", {})
        self.telegram_enabled_var.set(get_nested(telegram_cfg, ["enabled"], False))
        self.telegram_token_var.set(get_nested(telegram_cfg, ["token"], ""))
        self.telegram_chat_id_var.set(get_nested(telegram_cfg, ["chat_id"], ""))
        self.telegram_skip_verify_var.set(get_nested(telegram_cfg, ["skip_verify"], False))
        self.telegram_ca_path_var.set(get_nested(telegram_cfg, ["ca_path"], ""))
        self.telegram_notify_early_exit_var.set(get_nested(telegram_cfg, ["notify_on_early_exit"], True))

        mt5_cfg = config_data.get("mt5", {})
        self.mt5_enabled_var.set(get_nested(mt5_cfg, ["enabled"], False))
        self.mt5_term_path_var.set(get_nested(mt5_cfg, ["terminal_path"], ""))
        self.mt5_symbol_var.set(get_nested(mt5_cfg, ["symbol"], ""))

        self.mt5_n_M1.set(get_nested(mt5_cfg, ["n_M1"], 120))
        self.mt5_n_M5.set(get_nested(mt5_cfg, ["n_M5"], 180))
        self.mt5_n_M15.set(get_nested(mt5_cfg, ["n_M15"], 96))
        self.mt5_n_H1.set(get_nested(mt5_cfg, ["n_H1"], 120))

        no_run_cfg = config_data.get("no_run", {})
        self.no_run_weekend_enabled_var.set(get_nested(no_run_cfg, ["weekend_enabled"], True))
        self.norun_killzone_var.set(get_nested(no_run_cfg, ["killzone_enabled"], True))
        self.no_run_holiday_check_var.set(get_nested(no_run_cfg, ["holiday_check_enabled"], True))
        self.no_run_holiday_country_var.set(get_nested(no_run_cfg, ["holiday_check_country"], "US"))
        self.no_run_timezone_var.set(get_nested(no_run_cfg, ["timezone"], "Asia/Ho_Chi_Minh"))
        self._apply_killzone_schedule(
            self.killzone_summer_vars,
            no_run_cfg.get("killzone_summer"),
            mt5_service.DEFAULT_KILLZONE_SUMMER,
        )
        self._apply_killzone_schedule(
            self.killzone_winter_vars,
            no_run_cfg.get("killzone_winter"),
            mt5_service.DEFAULT_KILLZONE_WINTER,
        )

        no_trade_cfg = config_data.get("no_trade", {})
        self.no_trade_enabled_var.set(get_nested(no_trade_cfg, ["enabled"], True))
        self.nt_spread_max_pips_var.set(get_nested(no_trade_cfg, ["spread_max_pips"], 2.5))
        self.nt_min_atr_m5_pips_var.set(get_nested(no_trade_cfg, ["min_atr_m5_pips"], 3.0))
        self.trade_min_dist_keylvl_pips_var.set(get_nested(no_trade_cfg, ["min_dist_keylvl_pips"], 5.0))
        self.trade_allow_session_asia_var.set(get_nested(no_trade_cfg, ["allow_session_asia"], True))
        self.trade_allow_session_london_var.set(get_nested(no_trade_cfg, ["allow_session_london"], True))
        self.trade_allow_session_ny_var.set(get_nested(no_trade_cfg, ["allow_session_ny"], True))

        auto_trade_cfg = config_data.get("auto_trade", {})
        self.auto_trade_enabled_var.set(get_nested(auto_trade_cfg, ["enabled"], False))
        self.trade_strict_bias_var.set(get_nested(auto_trade_cfg, ["strict_bias"], True))
        self.trade_size_mode_var.set(get_nested(auto_trade_cfg, ["size_mode"], "risk_percent"))
        self.trade_equity_risk_pct_var.set(get_nested(auto_trade_cfg, ["risk_per_trade"], 0.5))
        self.trade_split_tp1_pct_var.set(get_nested(auto_trade_cfg, ["split_tp_ratio"], 50))
        self.trade_deviation_points_var.set(get_nested(auto_trade_cfg, ["deviation"], 20))
        self.trade_magic_var.set(get_nested(auto_trade_cfg, ["magic_number"], 26092025))
        self.trade_comment_prefix_var.set(get_nested(auto_trade_cfg, ["comment"], "AI-ICT"))
        self.trade_pending_ttl_min_var.set(get_nested(auto_trade_cfg, ["pending_ttl_min"], 90))
        self.trade_min_rr_tp2_var.set(get_nested(auto_trade_cfg, ["min_rr_tp2"], 2.0))
        self.trade_cooldown_min_var.set(get_nested(auto_trade_cfg, ["cooldown_min"], 10))
        self.trade_dynamic_pending_var.set(get_nested(auto_trade_cfg, ["dynamic_pending"], True))
        self.auto_trade_dry_run_var.set(get_nested(auto_trade_cfg, ["dry_run"], False))
        self.trade_move_to_be_after_tp1_var.set(get_nested(auto_trade_cfg, ["move_to_be_after_tp1"], True))
        self.trade_trailing_atr_mult_var.set(get_nested(auto_trade_cfg, ["trailing_atr_mult"], 0.5))
        self.trade_filling_type_var.set(get_nested(auto_trade_cfg, ["filling_type"], "IOC"))

        fmp_cfg = config_data.get("fmp", {})
        self.fmp_enabled_var.set(get_nested(fmp_cfg, ["enabled"], False))
        self.fmp_api_key_var.set(get_nested(fmp_cfg, ["api_key"], ""))

        te_cfg = config_data.get("te", {})
        self.te_enabled_var.set(get_nested(te_cfg, ["enabled"], False))
        self.te_api_key_var.set(get_nested(te_cfg, ["api_key"], ""))
        self.te_skip_ssl_var.set(get_nested(te_cfg, ["skip_ssl_verify"], False))

        news_cfg = config_data.get("news", {})
        self.news_block_enabled_var.set(get_nested(news_cfg, ["block_enabled"], True))
        self.trade_news_block_before_min_var.set(get_nested(news_cfg, ["block_before_min"], 15))
        self.trade_news_block_after_min_var.set(get_nested(news_cfg, ["block_after_min"], 15))
        self.news_cache_ttl_var.set(get_nested(news_cfg, ["cache_ttl_sec"], 300))
        keywords_cfg = get_nested(news_cfg, ["priority_keywords"], None)
        if isinstance(keywords_cfg, list):
            keywords_text = ", ".join(str(item) for item in keywords_cfg if str(item).strip())
        elif isinstance(keywords_cfg, str):
            keywords_text = keywords_cfg
        else:
            keywords_text = ""
        if not keywords_text.strip():
            keywords_text = ", ".join(sorted(DEFAULT_HIGH_IMPACT_KEYWORDS))
        self.news_priority_keywords_var.set(keywords_text)
        self.news_surprise_threshold_var.set(
            get_nested(news_cfg, ["surprise_score_threshold"], 0.5)
        )
        self.news_provider_error_threshold_var.set(
            get_nested(news_cfg, ["provider_error_threshold"], 2)
        )
        self.news_provider_backoff_var.set(
            get_nested(news_cfg, ["provider_error_backoff_sec"], 300)
        )
        currency_aliases_cfg = get_nested(news_cfg, ["currency_country_overrides"], None)
        if isinstance(currency_aliases_cfg, dict) and currency_aliases_cfg:
            currency_aliases_text = json.dumps(currency_aliases_cfg, ensure_ascii=False, indent=2)
        else:
            currency_aliases_text = ""
        self.news_currency_aliases_var.set(currency_aliases_text)
        self._set_text_widget_content(self.news_currency_aliases_text, currency_aliases_text)

        symbol_overrides_cfg = get_nested(news_cfg, ["symbol_country_overrides"], None)
        if isinstance(symbol_overrides_cfg, dict) and symbol_overrides_cfg:
            symbol_overrides_text = json.dumps(symbol_overrides_cfg, ensure_ascii=False, indent=2)
        else:
            symbol_overrides_text = ""
        self.news_symbol_overrides_var.set(symbol_overrides_text)
        self._set_text_widget_content(self.news_symbol_overrides_text, symbol_overrides_text)

        persistence_cfg = config_data.get("persistence", {})
        self.persistence_max_md_reports_var.set(get_nested(persistence_cfg, ["max_md_reports"], 10))

        prompts_cfg = config_data.get("prompts", {})
        self.prompt_file_path_var.set(get_nested(prompts_cfg, ["prompt_file_path"], ""))
        self.auto_load_prompt_txt_var.set(get_nested(prompts_cfg, ["auto_load_prompt_txt"], True))

        self.model_var.set(config_data.get("model", MODELS.DEFAULT_VISION))
        self.autorun_var.set(config_data.get("autorun", False))
        self.autorun_seconds_var.set(config_data.get("autorun_secs", 60))

        # Áp dụng cấu hình cho ChartTab
        chart_cfg = config_data.get("chart", {})
        if self.chart_tab:
            self.chart_tab.tf_var.set(get_nested(chart_cfg, ["timeframe"], "M15"))
            self.chart_tab.n_candles_var.set(get_nested(chart_cfg, ["num_candles"], 150))
            self.chart_tab.chart_type_var.set(get_nested(chart_cfg, ["chart_type"], "Nến"))
            self.chart_tab.refresh_secs_var.set(get_nested(chart_cfg, ["refresh_interval_secs"], 5))
            # Vẽ lại biểu đồ với cài đặt mới
            self.chart_tab._reset_and_redraw()

        # Kích hoạt autorun nếu cần
        if self.autorun_var.get():
            self._toggle_autorun()

        # Tải prompt tự động nếu được cấu hình
        if self.auto_load_prompt_txt_var.get():
            self.prompt_manager.load_prompts_from_disk(silent=True)

        # Cập nhật 1: Tự động làm mới tất cả danh sách tệp lịch sử sau khi áp dụng config
        # Điều này đảm bảo UI hiển thị đúng trạng thái khi khởi động
        self.history_manager.refresh_all_lists()

        # Cập nhật 2: Đồng bộ trạng thái của các widget tin tức sau khi áp dụng config
        self._update_news_widgets_state()

        # Cập nhật 3: Cung cấp cấu hình mới cho các service chạy nền
        self._update_services_config()

        logger.info("Đã áp dụng cấu hình lên UI thành công.")
    def _snapshot_config(self) -> "RunConfig":
        """
        Chụp lại toàn bộ trạng thái cấu hình hiện tại từ giao diện người dùng
        và trả về một đối tượng RunConfig đã được nhóm lại.
        """
        logger.debug("Bắt đầu chụp ảnh nhanh cấu hình từ UI.")
        summer_schedule = self._gather_killzone_schedule(self.killzone_summer_vars)
        winter_schedule = self._gather_killzone_schedule(self.killzone_winter_vars)
        currency_aliases_raw = self._get_text_widget_content(
            self.news_currency_aliases_text, self.news_currency_aliases_var
        )
        symbol_overrides_raw = self._get_text_widget_content(
            self.news_symbol_overrides_text, self.news_symbol_overrides_var
        )
        keywords_list = self._parse_priority_keywords(self.news_priority_keywords_var.get())
        currency_aliases = self._parse_mapping_string(currency_aliases_raw)
        symbol_overrides = self._parse_mapping_string(symbol_overrides_raw)
        return RunConfig(
            folder=FolderConfig(
                folder=self.folder_path.get(),
                delete_after=self.delete_after_var.get(),
                max_files=self.max_files_var.get(),
                only_generate_if_changed=self.only_generate_if_changed_var.get(),
            ),
            upload=UploadConfig(
                upload_workers=self.upload_workers_var.get(),
                cache_enabled=self.cache_enabled_var.get(),
                optimize_lossless=self.optimize_lossless_var.get(),
            ),
            image_processing=ImageProcessingConfig(
                max_width=self.image_max_width_var.get(),
                jpeg_quality=self.image_jpeg_quality_var.get(),
            ),
            context=ContextConfig(
                ctx_limit=self.context_limit_chars_var.get(),
                create_ctx_json=self.create_ctx_json_var.get(),
                prefer_ctx_json=self.prefer_ctx_json_var.get(),
                ctx_json_n=self.ctx_json_n_var.get(),
                remember_context=self.remember_context_var.get(),
                n_reports=self.context_n_reports_var.get(),
            ),
            api=ApiConfig(
                tries=self.api_tries_var.get(),
                delay=self.api_delay_var.get(),
            ),
            fmp=FMPConfig(
                enabled=self.fmp_enabled_var.get(),
                api_key=self.fmp_api_key_var.get(),
            ),
            te=TEConfig(
                enabled=self.te_enabled_var.get(),
                api_key=self.te_api_key_var.get(),
                skip_ssl_verify=self.te_skip_ssl_var.get(),
            ),
            telegram=TelegramConfig(
                enabled=self.telegram_enabled_var.get(),
                token=self.telegram_token_var.get(),
                chat_id=self.telegram_chat_id_var.get(),
                skip_verify=self.telegram_skip_verify_var.get(),
                ca_path=self.telegram_ca_path_var.get(),
                notify_on_early_exit=self.telegram_notify_early_exit_var.get(),
            ),
            mt5=MT5Config(
                enabled=self.mt5_enabled_var.get(),
                symbol=self.mt5_symbol_var.get(),
                n_M1=self.mt5_n_M1.get(),
                n_M5=self.mt5_n_M5.get(),
                n_M15=self.mt5_n_M15.get(),
                n_H1=self.mt5_n_H1.get(),
            ),
            no_run=NoRunConfig(
                weekend_enabled=self.no_run_weekend_enabled_var.get(),
                killzone_enabled=self.norun_killzone_var.get(),
                holiday_check_enabled=self.no_run_holiday_check_var.get(),
                holiday_check_country=self.no_run_holiday_country_var.get(),
                timezone=self.no_run_timezone_var.get(),
                killzone_summer=summer_schedule,
                killzone_winter=winter_schedule,
            ),
            no_trade=NoTradeConfig(
                enabled=self.no_trade_enabled_var.get(),
                spread_max_pips=self.nt_spread_max_pips_var.get(),
                min_atr_m5_pips=self.nt_min_atr_m5_pips_var.get(),
                min_dist_keylvl_pips=self.trade_min_dist_keylvl_pips_var.get(),
                allow_session_asia=self.trade_allow_session_asia_var.get(),
                allow_session_london=self.trade_allow_session_london_var.get(),
                allow_session_ny=self.trade_allow_session_ny_var.get(),
            ),
            auto_trade=AutoTradeConfig(
                enabled=self.auto_trade_enabled_var.get(),
                strict_bias=self.trade_strict_bias_var.get(),
                size_mode=self.trade_size_mode_var.get(),
                risk_per_trade=self.trade_equity_risk_pct_var.get(),
                split_tp_enabled=self.trade_split_tp1_pct_var.get() > 0,
                split_tp_ratio=self.trade_split_tp1_pct_var.get(),
                deviation=self.trade_deviation_points_var.get(),
                magic_number=self.trade_magic_var.get(),
                comment=self.trade_comment_prefix_var.get(),
                pending_ttl_min=self.trade_pending_ttl_min_var.get(),
                min_rr_tp2=self.trade_min_rr_tp2_var.get(),
                cooldown_min=self.trade_cooldown_min_var.get(),
                dynamic_pending=self.trade_dynamic_pending_var.get(),
                dry_run=self.auto_trade_dry_run_var.get(),
                move_to_be_after_tp1=self.trade_move_to_be_after_tp1_var.get(),
                trailing_atr_mult=self.trade_trailing_atr_mult_var.get(),
                filling_type=self.trade_filling_type_var.get(),
            ),
            news=NewsConfig(
                block_enabled=self.news_block_enabled_var.get(),
                block_before_min=self.trade_news_block_before_min_var.get(),
                block_after_min=self.trade_news_block_after_min_var.get(),
                cache_ttl_sec=self.news_cache_ttl_var.get(),
                priority_keywords=tuple(keywords_list) if keywords_list else None,
                surprise_score_threshold=self.news_surprise_threshold_var.get(),
                provider_error_threshold=self.news_provider_error_threshold_var.get(),
                provider_error_backoff_sec=self.news_provider_backoff_var.get(),
                currency_country_overrides=currency_aliases,
                symbol_country_overrides=symbol_overrides,
            ),
            persistence=PersistenceConfig(
                max_md_reports=self.persistence_max_md_reports_var.get()
            ),
            chart=ChartConfig(
                timeframe=self.chart_tab.tf_var.get() if self.chart_tab else "M15",
                num_candles=self.chart_tab.n_candles_var.get() if self.chart_tab else 150,
                chart_type=self.chart_tab.chart_type_var.get() if self.chart_tab else "Nến",
                refresh_interval_secs=self.chart_tab.refresh_secs_var.get() if self.chart_tab else 5,
            ),
        )

    def _save_workspace(self):
        """Bắt đầu quá trình lưu cấu hình workspace trong luồng nền."""
        logger.info("Yêu cầu lưu workspace từ UI.")
        self.ui_status("Đang lưu workspace...")
        config_data = self._collect_config_data()
        self.io_controller.run(
            worker=self._save_workspace_worker,
            args=(config_data,),
            group="ui.workspace",
            name="ui.workspace.save",
            metadata={"component": "ui", "operation": "save_workspace"},
        )

    def _save_workspace_worker(self, config_data: dict):
        """Worker chạy nền để ghi file workspace."""
        try:
            workspace_config.save_config_to_file(config_data)
            logger.info("Đã lưu cấu hình workspace thành công.")
            ui_builder.enqueue(self, lambda: ui_builder.show_message("Thành công", "Đã lưu cấu hình workspace."))
            ui_builder.enqueue(self, lambda: self.ui_status("Đã lưu workspace."))
        except Exception as e:
            logger.exception("Lỗi khi lưu cấu hình workspace.")
            ui_builder.enqueue(self, lambda: ui_builder.show_message("Lỗi", f"Không thể lưu cấu hình:\n{e}"))
            ui_builder.enqueue(self, lambda: self.ui_status("Lỗi khi lưu workspace."))

    def _load_workspace(self):
        """Bắt đầu quá trình tải cấu hình workspace trong luồng nền."""
        logger.info("Yêu cầu tải workspace từ UI.")
        self.ui_status("Đang tải workspace...")
        self.io_controller.run(
            worker=self._load_workspace_worker,
            group="ui.workspace",
            name="ui.workspace.load",
            metadata={"component": "ui", "operation": "load_workspace"},
        )

    def _load_workspace_worker(self):
        """Worker chạy nền để đọc file workspace."""
        try:
            config_data = workspace_config.load_config_from_file()
            
            def update_ui():
                if config_data:
                    self.apply_config(config_data)
                    ui_builder.show_message("Thành công", "Đã tải và áp dụng cấu hình workspace.")
                    self.ui_status("Đã tải workspace.")
                    logger.info("Đã tải và áp dụng cấu hình workspace thành công.")
                else:
                    ui_builder.show_message("Thông báo", "Không tìm thấy file workspace hoặc file bị rỗng.")
                    self.ui_status("Không tìm thấy workspace.")
                    logger.info("Không tìm thấy file workspace hoặc file bị rỗng.")

            ui_builder.enqueue(self, update_ui)
        except Exception as e:
            logger.exception("Lỗi khi tải cấu hình workspace.")
            ui_builder.enqueue(self, lambda: ui_builder.show_message("Lỗi", f"Không thể tải cấu hình:\n{e}"))
            ui_builder.enqueue(self, lambda: self.ui_status("Lỗi khi tải workspace."))

    # --- Action Methods ---
    def start_analysis(self, *, source: str = "manual") -> None:
        """Bắt đầu một phiên phân tích mới thông qua AnalysisController."""

        logger.info("Yêu cầu bắt đầu phân tích từ UI (source=%s).", source)

        if source == "autorun":
            self._request_autorun_start()
            return

        if self.is_running or self._pending_session:
            self.show_error_message("Đang chạy", "Một phân tích khác đang chạy hoặc đang được xếp lịch.")
            logger.warning("Bỏ qua start_analysis vì đang có phiên khác xử lý.")
            return

        folder = self.folder_path.get()
        if not folder or not Path(folder).is_dir():
            self.show_error_message("Lỗi", "Vui lòng chọn một thư mục hợp lệ.")
            logger.error("Yêu cầu bắt đầu phân tích bị từ chối: thư mục không hợp lệ.")
            return

        cfg = self._snapshot_config()
        self._update_services_config()
        session_id = datetime.now().strftime("manual-%Y%m%d-%H%M%S")
        self._queued_autorun_session = None
        self._pending_session = True

        def _on_start(sid: str, priority: str) -> None:
            self._handle_session_started(sid, priority, cfg, source)

        self.analysis_controller.start_session(
            session_id,
            self,
            cfg,
            priority="user",
            on_start=_on_start,
        )
        self.ui_status("Đang chuẩn bị chạy phân tích...")
        logger.info("Đã gửi yêu cầu khởi động phiên %s (manual).", session_id)

    def stop_analysis(self):
        """Gửi tín hiệu dừng cho phiên phân tích hiện tại."""

        if not self.is_running or not self._current_session_id:
            return

        logger.info("Yêu cầu dừng phân tích từ UI (session=%s).", self._current_session_id)
        self.stop_flag = True
        self.analysis_controller.stop_session(self._current_session_id)
        self.ui_status("Đang dừng...")
        self._queued_autorun_session = None
        self._pending_session = False

    def _request_autorun_start(self) -> None:
        """Xử lý yêu cầu autorun với cơ chế ưu tiên người dùng."""

        if self.is_running or self._pending_session:
            logger.info("Autorun bỏ qua vì đang có phiên chạy hoặc đang khởi động.")
            self._schedule_next_autorun()
            return
        if self._queued_autorun_session:
            logger.debug(
                "Đã có autorun đang chờ (%s), không enqueue thêm.",
                self._queued_autorun_session,
            )
            return

        folder = self.folder_path.get()
        if not folder or not Path(folder).is_dir():
            logger.warning("Autorun bỏ qua vì thư mục không hợp lệ.")
            self.ui_status("Autorun bỏ qua: thư mục chưa hợp lệ.")
            self._schedule_next_autorun()
            return

        cfg = self._snapshot_config()
        self._update_services_config()
        session_id = datetime.now().strftime("autorun-%Y%m%d-%H%M%S")

        def _on_start(sid: str, priority: str) -> None:
            self._queued_autorun_session = None
            self._handle_session_started(sid, priority, cfg, "autorun")

        status = self.analysis_controller.enqueue_autorun(
            session_id,
            self,
            cfg,
            on_start=_on_start,
        )
        if status == "queued":
            self._queued_autorun_session = session_id
            self._pending_session = False
            self.ui_status("Autorun đã xếp hàng, sẽ chạy sau khi tác vụ hiện tại hoàn tất.")
            logger.info("Autorun %s được xếp hàng chờ.", session_id)
        else:
            self._pending_session = True
            logger.info("Autorun %s bắt đầu ngay lập tức.", session_id)

    def _handle_session_started(self, session_id: str, priority: str, cfg: RunConfig, source: str) -> None:
        """Cập nhật trạng thái UI khi một phiên thực sự bắt đầu."""

        self.is_running = True
        self._pending_session = False
        self.stop_flag = False
        self._current_session_id = session_id
        self.run_config = cfg
        ui_builder.toggle_controls_state(self, "disabled")

        if priority == "autorun":
            message = "Autorun đang chạy phân tích..."
        else:
            message = "Đang chạy phân tích..."
        self.ui_status(message)
        logger.info(
            "Phiên %s bắt đầu (priority=%s, source=%s).", session_id, priority, source
        )

    def choose_folder(self):
        """Mở hộp thoại cho người dùng chọn thư mục chứa ảnh."""
        logger.debug("Mở hộp thoại chọn thư mục.")
        folder = filedialog.askdirectory(title="Chọn thư mục gốc chứa các Symbol (ví dụ: .../MQL5/Files/Screenshots)")
        if not folder:
            logger.debug("Người dùng đã hủy chọn thư mục.")
            return
        self.folder_path.set(folder)
        self._load_files(folder)
        logger.info(f"Đã chọn thư mục: {folder}")

    def _load_files(self, folder: str):
        """
        Xóa kết quả cũ và bắt đầu một luồng mới để quét file ảnh.
        (Cải tiến: Chạy quét file trong luồng riêng để tránh treo UI)
        """
        logger.debug(f"Bắt đầu quá trình tải file từ thư mục: {folder}.")
        self.results.clear()
        self.combined_report_text = ""
        if self.tree:
            self.tree.delete(*self.tree.get_children())

        self.ui_status(f"Đang quét thư mục {folder}...")
        self.ui_progress(0)
        if self.detail_text:
            self.ui_detail_replace("Báo cáo tổng hợp sẽ hiển thị tại đây.")

        # Chạy tác vụ quét thư mục trong một luồng riêng thông qua facade
        self.io_controller.run(
            worker=self._scan_folder_worker,
            args=(folder,),
            group="ui.io.scan",
            name="ui.io.scan_folder",
            metadata={"component": "ui", "operation": "scan_folder"},
            cancel_previous=True,
        )

    def _scan_folder_worker(self, folder: str):
        """
        Worker chạy trong luồng riêng để quét thư mục và cập nhật UI.
        """
        logger.debug(f"Luồng quét thư mục bắt đầu cho: {folder}.")
        count = 0
        try:
            image_paths = [
                p for p in sorted(Path(folder).rglob("*"))
                if p.is_file() and p.suffix.lower() in FILES.SUPPORTED_EXTS
            ]

            for p in image_paths:
                result_item = {"path": p, "name": p.name, "status": "Chưa xử lý", "text": ""}
                self.results.append(result_item)
                idx = len(self.results)

                def update_tree(item_idx=idx, item_name=p.name):
                    if self.tree:
                        self.tree.insert("", "end", iid=str(item_idx - 1), values=(item_idx, item_name, "Chưa xử lý"))

                ui_builder.enqueue(self, update_tree)
                count += 1

            msg = f"Đã nạp {count} ảnh. Sẵn sàng." if count else "Không tìm thấy ảnh phù hợp."
            ui_builder.enqueue(self, lambda: self.ui_status(msg))
            logger.info(f"Luồng quét đã hoàn tất, tìm thấy {count} file.")

            # Logic cuối cùng: Sau khi quét file, luôn làm mới danh sách
            # báo cáo và context dựa trên symbol hiện tại trong UI.
            ui_builder.enqueue(self, self.history_manager.refresh_all_lists)
            ui_builder.enqueue(self, lambda: self._guess_symbol_from_results(auto=True))

        except Exception:
            logger.exception(f"Lỗi trong luồng quét thư mục {folder}.")
            ui_builder.enqueue(self, lambda: self.ui_status("Lỗi khi đọc thư mục."))

    def clear_results(self):
        """Xóa tất cả các kết quả phân tích hiện có."""
        logger.debug("Đang xóa kết quả phân tích.")
        self.results.clear()
        self.combined_report_text = ""
        if self.tree:
            self.tree.delete(*self.tree.get_children())
        if self.detail_text:
            self.ui_detail_replace("Báo cáo tổng hợp sẽ hiển thị tại đây.")
        self.ui_progress(0)
        self.ui_status("Đã xoá kết quả.")

    def export_markdown(self):
        """Mở hộp thoại lưu file và bắt đầu quá trình xuất Markdown trong luồng nền."""
        logger.debug("Yêu cầu xuất báo cáo Markdown.")
        if not self.combined_report_text.strip():
            self.show_error_message("Trống", "Không có nội dung báo cáo để xuất.")
            return

        out_path_str = filedialog.asksaveasfilename(
            title="Lưu báo cáo Markdown",
            defaultextension=".md",
            filetypes=[("Markdown", "*.md")],
            initialdir=self.folder_path.get(),
            initialfile=f"bao_cao_{datetime.now():%Y%m%d_%H%M%S}.md",
        )
        if not out_path_str:
            logger.debug("Người dùng đã hủy lưu báo cáo Markdown.")
            return

        self.ui_status("Đang xuất báo cáo Markdown...")
        self.io_controller.run(
            worker=self._export_markdown_worker,
            args=(out_path_str, self.combined_report_text),
            group="ui.io.export",
            name="ui.io.export_markdown",
            metadata={"component": "ui", "operation": "export_markdown"},
        )

    def _export_markdown_worker(self, path_str: str, content: str):
        """Worker chạy nền để ghi báo cáo ra file Markdown."""
        try:
            Path(path_str).write_text(content, encoding="utf-8")
            logger.info(f"Đã lưu báo cáo Markdown thành công tại: {path_str}.")
            ui_builder.enqueue(self, lambda: self.show_error_message("Thành công", f"Đã lưu báo cáo tại:\n{path_str}"))
            ui_builder.enqueue(self, lambda: self.ui_status("Đã xuất báo cáo Markdown."))
        except Exception as e:
            logger.exception("Lỗi khi ghi báo cáo Markdown.")
            ui_builder.enqueue(self, lambda: self.show_error_message("Lỗi ghi file", f"Không thể lưu báo cáo:\n{e}"))
            ui_builder.enqueue(self, lambda: self.ui_status("Lỗi khi xuất báo cáo."))

    # --- UI Callbacks and Helpers ---
    def _on_tree_select(self, _evt: tk.Event):
        """
        Xử lý sự kiện khi người dùng chọn một hàng trong bảng.
        Hiển thị báo cáo chi tiết cho mục được chọn.
        """
        if not self.tree:
            return
        selection = self.tree.selection()
        if not selection:
            # Khi không có gì được chọn, hiển thị báo cáo tổng hợp nếu có
            if self.combined_report_text.strip():
                self.ui_detail_replace(self.combined_report_text)
            else:
                self.ui_detail_replace("Báo cáo tổng hợp sẽ hiển thị tại đây.")
            return

        try:
            selected_iid = selection[0]
            item_index = int(selected_iid)
            if 0 <= item_index < len(self.results):
                item_data = self.results[item_index]
                report_text = item_data.get("text", "").strip()
                if report_text:
                    # Hiển thị báo cáo chi tiết của file được chọn
                    self.ui_detail_replace(report_text)
                else:
                    # Nếu file được chọn chưa có báo cáo, hiển thị báo cáo tổng hợp làm fallback
                    if self.combined_report_text.strip():
                        self.ui_detail_replace(
                            f"Chưa có báo cáo chi tiết cho tệp này.\n\n"
                            f"--- BÁO CÁO TỔNG HỢP ---\n{self.combined_report_text}"
                        )
                    else:
                        self.ui_detail_replace("Chưa có báo cáo cho tệp này. Hãy bấm 'Bắt đầu'.")
            else:
                logger.warning(f"Chỉ mục treeview không hợp lệ: {item_index}")
        except (ValueError, IndexError) as e:
            logger.error(f"Lỗi khi xử lý lựa chọn treeview: {e}")
            self.ui_detail_replace("Lỗi khi hiển thị chi tiết báo cáo.")

    def _toggle_api_visibility(self):
        """Chuyển đổi trạng thái hiển thị của tất cả các ô nhập API key."""
        entries = [self.api_entry, self.fmp_api_entry, self.te_api_entry]
        # Xác định trạng thái mới dựa trên entry đầu tiên
        is_hidden = entries[0] and entries[0].cget("show") == "*"
        new_show_char = "" if is_hidden else "*"
        
        for entry in entries:
            if entry:
                entry.configure(show=new_show_char)

    def _configure_gemini_api_and_update_ui(self):
        """
        Sử dụng gemini_service để lấy danh sách model và cập nhật UI.
        Hàm này được gọi mỗi khi API key thay đổi.
        """
        api_key = self.api_key_var.get()
        if not api_key:
            self.ui_status("Vui lòng nhập Google AI API Key.")
            if self.model_combo:
                self.model_combo["values"] = []
            return

        # Chạy trong luồng riêng để không làm treo UI
        self.io_controller.run(
            worker=self._update_model_list_worker,
            args=(api_key,),
            group="ui.io.models",
            name="ui.io.update_models",
            metadata={"component": "ui", "operation": "update_models"},
            cancel_previous=True,
        )

    def _update_model_list_worker(self, api_key: str):
        """
        Worker chạy trong luồng nền để lấy danh sách model và cập nhật UI.
        """
        logger.debug("Bắt đầu worker cập nhật danh sách mô hình AI.")
        self.ui_queue.put(lambda: self.ui_status("Đang xác thực API key và lấy model..."))
        try:
            # Gọi hàm mới từ service
            available_models = gemini_service.configure_and_get_models(api_key)

            def update_ui_success():
                if not self.model_combo:
                    return
                self.model_combo["values"] = available_models
                if available_models:
                    # Nếu model hiện tại không có trong danh sách mới, reset về mặc định
                    if self.model_var.get() not in available_models:
                        self.model_var.set(MODELS.DEFAULT_VISION)
                    self.ui_status("Đã cập nhật danh sách mô hình AI.")
                else:
                    self.ui_status("Không tìm thấy mô hình AI nào.")

            self.ui_queue.put(update_ui_success)

        except exceptions.PermissionDenied:
            msg = "Lỗi API: Key không đủ quyền hoặc không hợp lệ."
            logger.error("Lỗi quyền API khi liệt kê model.")

            def update_ui_on_auth_error():
                self.ui_status(msg)
                if self.model_combo:
                    # Cung cấp danh sách mặc định để người dùng vẫn có thể chọn
                    self.model_combo["values"] = [MODELS.DEFAULT_VISION]
                    self.model_var.set(MODELS.DEFAULT_VISION)

            self.ui_queue.put(update_ui_on_auth_error)
        except Exception as e:
            logger.error(f"Lỗi không xác định khi cập nhật danh sách mô hình: {e}")
            self.ui_queue.put(lambda: self.ui_status("Lỗi khi lấy danh sách mô hình."))

    # --- UI Update Methods (Worker-Safe) ---
    def ui_status(self, message: str):
        """Cập nhật thanh trạng thái một cách an toàn từ các luồng khác."""
        self.status_var.set(message)

    def ui_progress(self, value: float):
        """Cập nhật thanh tiến trình một cách an toàn."""
        self.progress_var.set(value)

    def ui_detail_replace(self, text: str):
        """Thay thế toàn bộ nội dung trong ô chi tiết một cách an toàn."""
        if self.detail_text:
            self.detail_text.config(state=tk.NORMAL)
            self.detail_text.delete("1.0", tk.END)
            self.detail_text.insert(tk.END, text)
            self.detail_text.config(state=tk.DISABLED)
            self.detail_text.see(tk.END)

    def show_error_message(self, title: str, message: str):
        """Hiển thị một hộp thoại thông báo lỗi."""
        ui_builder.show_message(title=title, message=message, parent=self.root)

    def _on_symbol_changed(self, *args):
        """
        Được gọi mỗi khi symbol thay đổi. Đồng bộ hóa tất cả các thành phần phụ thuộc.
        """
        new_symbol = self.mt5_symbol_var.get()
        logger.debug(f"Symbol đã thay đổi thành: {new_symbol}, đang đồng bộ hóa các thành phần.")

        # 1. Cập nhật HistoryManager
        self.history_manager.refresh_all_lists()

        # 2. Cập nhật ChartTab
        if self.chart_tab:
            logger.debug("Thông báo cho ChartTab để vẽ lại biểu đồ.")
            self.chart_tab._reset_and_redraw()

    def _update_news_widgets_state(self):
        """
        Bật/tắt các widget con trong phần cài đặt tin tức dựa trên việc
        có nhà cung cấp nào (FMP/TE) được bật hay không.
        """
        any_provider_enabled = self.fmp_enabled_var.get() or self.te_enabled_var.get()
        new_state = "normal" if any_provider_enabled else "disabled"

        # Danh sách các widget cần thay đổi trạng thái
        widgets_to_toggle = [
            self.news_block_check,
            self.news_before_spin,
            self.news_after_spin,
            self.news_cache_spin,
            self.news_provider_combo,
            self.news_keywords_entry,
            self.news_surprise_spin,
            self.news_error_threshold_spin,
            self.news_backoff_spin,
            self.news_currency_aliases_text,
            self.news_symbol_overrides_text,
        ]

        for widget in widgets_to_toggle:
            if widget:
                widget.config(state=new_state)

        # Cập nhật cả tiêu đề của card để cung cấp phản hồi trực quan
        if self.news_card:
            if not any_provider_enabled:
                self.news_card.config(text="Chặn tin tức (Cần bật FMP hoặc TE)")
            else:
                self.news_card.config(text="Chặn giao dịch theo tin tức (News)")

    def _update_progress(self, current_step: int, total_steps: int):
        """Cập nhật thanh tiến trình dựa trên bước hiện tại và tổng số bước."""
        if total_steps > 0:
            progress = (current_step / total_steps) * 100
            self.ui_progress(progress)

    def _update_tree_row(self, index: int, status: str):
        """Cập nhật trạng thái của một hàng trong cây file."""
        if self.tree and self.tree.exists(str(index)):
            self.tree.set(str(index), "Status", status)

    def _finalize_stopped(self):
        """Hoàn tất tác vụ khi bị dừng."""
        self.is_running = False
        self.stop_flag = False
        self._current_session_id = None
        self._pending_session = False
        self._queued_autorun_session = None
        self.ui_status("Đã dừng bởi người dùng.")
        self.ui_progress(0)
        ui_builder.toggle_controls_state(self, "normal")
        self._schedule_next_autorun()

    def _finalize_done(self):
        """Hoàn tất tác vụ khi chạy xong."""
        self.is_running = False
        self.stop_flag = False
        self._current_session_id = None
        self._pending_session = False
        self._queued_autorun_session = None
        self.ui_status("Hoàn tất.")
        self.ui_progress(100)
        ui_builder.toggle_controls_state(self, "normal")
        self._schedule_next_autorun()

    # --- Autorun Methods ---
    def _toggle_autorun(self):
        """Bật hoặc tắt chế độ tự động chạy phân tích."""
        is_autorun_on = self.autorun_var.get()
        logger.info(f"Chuyển đổi Autorun sang: {'Bật' if is_autorun_on else 'Tắt'}")
        if is_autorun_on:
            self._schedule_next_autorun()
            self.ui_status(f"Tự động chạy Bật. Chờ {self.autorun_seconds_var.get()} giây...")
        elif self._autorun_job:
            self.root.after_cancel(self._autorun_job)
            self._autorun_job = None
            self.ui_status("Tự động chạy Tắt.")

    def _autorun_interval_changed(self, *_):
        """Xử lý khi khoảng thời gian tự động chạy thay đổi."""
        if self.autorun_var.get():
            logger.info("Khoảng thời gian Autorun thay đổi, đặt lại lịch.")
            if self._autorun_job:
                self.root.after_cancel(self._autorun_job)
            self._schedule_next_autorun()

    def _schedule_next_autorun(self):
        """Lên lịch cho lần chạy tự động tiếp theo."""
        if not self.autorun_var.get() or self.is_running or self._pending_session:
            return
        interval_ms = self.autorun_seconds_var.get() * 1000
        logger.debug(f"Lên lịch chạy tự động tiếp theo sau {interval_ms}ms.")
        self._autorun_job = self.root.after(interval_ms, self._autorun_tick)

    def _autorun_tick(self):
        """
        Hàm được gọi khi đến thời gian tự động chạy.
        Kích hoạt một worker nền để kiểm tra các điều kiện và bắt đầu phân tích.
        """
        logger.info("Autorun tick: Kích hoạt worker kiểm tra.")
        # Chỉ kích hoạt worker nếu chưa có phân tích nào chạy,
        # để tránh tạo ra quá nhiều luồng không cần thiết.
        if self.is_running or self._pending_session:
            logger.warning("Autorun tick: Bỏ qua vì đang có phiên chạy hoặc đang khởi động.")
            self._schedule_next_autorun()
            return

        self.io_controller.run(
            worker=self._autorun_tick_worker,
            group="ui.autorun",
            name="ui.autorun.guard",
            metadata={"component": "analysis", "operation": "autorun_guard"},
        )

    def _autorun_tick_worker(self):
        """
        Worker chạy nền để kiểm tra các điều kiện (đặc biệt là kết nối MT5)
        trước khi bắt đầu một phiên phân tích tự động.
        """
        logger.debug("Autorun tick worker: Bắt đầu kiểm tra điều kiện.")
        
        # Kiểm tra lại is_running bên trong luồng để tránh race condition
        if self.is_running or self._pending_session:
            logger.warning("Autorun tick worker: Bỏ qua vì đang có tiến trình chạy.")
            self.ui_queue.put(self._schedule_next_autorun)
            return

        # Kiểm tra kết nối MT5 (tác vụ có thể bị chặn)
        is_mt5_ok = self.mt5_enabled_var.get() and mt5_service.is_connected()

        if not is_mt5_ok:
            logger.warning("Autorun tick worker: Bỏ qua vì MT5 chưa được kết nối hoặc chưa bật.")
            # Lên lịch lại cho lần chạy tiếp theo từ luồng chính
            self.ui_queue.put(self._schedule_next_autorun)
            return

        logger.info("Autorun tick worker: Điều kiện hợp lệ, yêu cầu bắt đầu phân tích trên luồng UI.")
        # Yêu cầu start_analysis chạy trên luồng chính để đảm bảo an toàn cho UI
        self.ui_queue.put(self._request_autorun_start)

    # --- MT5 Methods ---
    def _pick_mt5_terminal(self):
        """Mở hộp thoại chọn file terminal64.exe."""
        logger.debug("Mở hộp thoại chọn MT5 terminal.")
        filepath = filedialog.askopenfilename(
            title="Chọn file terminal64.exe",
            filetypes=[("MT5 Terminal", "terminal64.exe"), ("All files", "*.*")]
        )
        if filepath:
            self.mt5_term_path_var.set(filepath)
            logger.info(f"Đã chọn đường dẫn MT5: {filepath}")

    def _guess_symbol_from_results(self, auto: bool = False) -> bool:
        """Thử đoán symbol dựa trên danh sách ảnh đã nạp."""

        if not self.results:
            if not auto:
                self.show_error_message("Đoán Symbol", "Vui lòng nạp ảnh trước.")
            return False

        filenames = [item.get("name", "") for item in self.results if item.get("name")]
        guessed_symbol, stats = general_utils.guess_symbol_from_filenames(filenames)

        if not guessed_symbol:
            if not auto:
                self.show_error_message("Đoán Symbol", "Không thể đoán symbol từ tên file.")
            logger.info("Không thể đoán symbol từ danh sách ảnh. auto=%s", auto)
            return False

        current_symbol = (self.mt5_symbol_var.get() or "").strip().upper()
        occurrences = stats.get(guessed_symbol, 0)
        message = (
            f"Đã đoán symbol {guessed_symbol} từ {occurrences} ảnh."
            if occurrences
            else f"Đã đoán symbol {guessed_symbol}."
        )

        if auto and current_symbol:
            if current_symbol == guessed_symbol:
                self.ui_status(f"Symbol hiện tại đã khớp với ảnh ({guessed_symbol}).")
            else:
                self.ui_status(
                    f"Phát hiện symbol {guessed_symbol} từ {occurrences} ảnh (giữ {current_symbol})."
                )
            logger.info(
                "Phát hiện symbol %s từ ảnh (auto=%s, giữ symbol hiện tại %s).",
                guessed_symbol,
                auto,
                current_symbol,
            )
            return False

        self.mt5_symbol_var.set(guessed_symbol)

        if auto:
            self.ui_status(message)
        else:
            self.show_error_message("Đoán Symbol", message)

        logger.info(
            "Đã đặt symbol về %s dựa trên tên ảnh (auto=%s, xuất hiện %s lần).",
            guessed_symbol,
            auto,
            occurrences,
        )
        return True

    def _mt5_guess_symbol(self):
        """Đoán symbol từ tên file ảnh theo yêu cầu của người dùng."""

        if not self._guess_symbol_from_results(auto=False):
            logger.info("Người dùng yêu cầu đoán symbol nhưng không tìm được kết quả phù hợp.")

    def _mt5_connect(self):
        """Thực hiện kết nối đến MetaTrader 5 trong một luồng riêng."""
        logger.info("Yêu cầu kết nối MT5 từ UI.")
        path = self.mt5_term_path_var.get()
        if not path or not Path(path).exists():
            self.show_error_message("Lỗi MT5", "Đường dẫn terminal64.exe không hợp lệ.")
            return

        self.ui_status("Đang kết nối đến MT5...")
        self.mt5_controller.connect(path, self._mt5_connect_worker)

    def _mt5_connect_worker(self, path: str):
        """Worker để thực hiện kết nối MT5."""
        ok, msg = mt5_service.connect(path=path)
        
        def update_ui():
            self.mt5_status_var.set(str(msg) if msg else "Kết nối thành công.")
            if ok:
                self.show_error_message("MT5", "Kết nối thành công.")
                # Sau khi kết nối thành công, bắt đầu lại lịch kiểm tra
                self._schedule_mt5_connection_check()
            else:
                self.show_error_message("MT5", str(msg))
            self.ui_status("Sẵn sàng.")

        self.ui_queue.put(update_ui)

    def _schedule_mt5_connection_check(self):
        """Lên lịch kiểm tra kết nối MT5 định kỳ (chạy trong luồng riêng)."""
        if self._mt5_check_connection_job:
            self.root.after_cancel(self._mt5_check_connection_job)

        if self.mt5_enabled_var.get():
            # Chạy kiểm tra trong luồng nền
            self.mt5_controller.check_status(self._mt5_check_connection_worker)

        # Lên lịch cho lần kiểm tra tiếp theo
        self._mt5_check_connection_job = self.root.after(15000, self._schedule_mt5_connection_check)

    def _mt5_check_connection_worker(self):
        """Worker để kiểm tra trạng thái kết nối MT5."""
        is_connected = mt5_service.is_connected()
        
        def update_ui():
            status = "MT5: Đã kết nối" if is_connected else "MT5: Mất kết nối"
            self.mt5_status_var.set(status)
            if not is_connected:
                logger.warning("Mất kết nối MT5, sẽ thử kết nối lại trong lần kiểm tra tiếp theo.")
                # Không gọi _mt5_connect trực tiếp để tránh vòng lặp vô hạn,
                # thay vào đó, lần kiểm tra theo lịch tiếp theo sẽ xử lý.

        self.ui_queue.put(update_ui)

    def _mt5_snapshot_popup(self):
        """Yêu cầu snapshot dữ liệu MT5 và hiển thị nó (chạy trong luồng riêng)."""
        logger.debug("Yêu cầu snapshot dữ liệu MT5.")
        if not mt5_service.is_connected():
            self.show_error_message("MT5", "Chưa kết nối MT5.")
            return
        
        self.ui_status("Đang lấy snapshot dữ liệu MT5...")
        self.mt5_controller.snapshot(self._mt5_snapshot_worker)

    def _update_services_config(self):
        """
        Lấy cấu hình hiện tại và cập nhật cho các service chạy nền.
        """
        current_config = self._snapshot_config()
        if self.news_service:
            self.news_service.update_config(current_config)
        if self.news_controller:
            if not self._news_polling_started:
                # Khởi động polling ngay lần đầu tiên có cấu hình hợp lệ
                self.news_controller.start_polling(self._handle_news_refresh_payload)
                self._news_polling_started = True
            else:
                # Các lần cập nhật tiếp theo chỉ cần kích hoạt refresh lại
                self.news_controller.trigger_autorun(force=True)

    def _handle_news_refresh_payload(self, payload: Dict[str, Any]) -> None:
        """Cập nhật trạng thái UI khi NewsController hoàn tất một vòng refresh."""

        events = payload.get("events", [])
        source = payload.get("source", "unknown")
        priority = payload.get("priority", "autorun")
        latency = payload.get("latency_sec", 0.0)

        self.news_events = events
        self.news_fetch_time = latency
        status = f"Tin tức cập nhật ({source}/{priority}, {len(events)} sự kiện)."
        if latency:
            status += f" Độ trễ: {latency:.2f}s."
        self.ui_status(status)

    def _on_news_updated(self, events: List[Dict[str, Any]]):
        """
        Callback được gọi từ NewsService khi cache tin tức được làm mới.
        """
        logger.debug(f"Callback nhận được {len(events)} sự kiện tin tức mới.")
        
        def update_ui():
            # Lọc lại danh sách tin tức dựa trên symbol hiện tại của UI
            symbol = self.mt5_symbol_var.get()
            if self.news_service and self.news_tab and symbol:
                filtered_events = self.news_service.get_upcoming_events(symbol)
                self.news_tab.update_news_list(filtered_events)
                self.ui_status(f"Tin tức được tự động cập nhật ({len(filtered_events)} sự kiện).")
            elif self.news_tab:
                # Xử lý trường hợp không có symbol
                self.news_tab.update_news_list([])

        self.ui_queue.put(update_ui)

    def _mt5_snapshot_worker(self):
        """Worker để lấy dữ liệu snapshot MT5."""
        cfg = self._snapshot_config()
        # Sử dụng kiến trúc timeout tương tự như AnalysisWorker
        mt5_data = None
        error_msg = None
        with ThreadPoolExecutor(max_workers=1) as executor:
            try:
                future = executor.submit(
                    mt5_service.get_market_data,
                    cfg.mt5,
                    timezone_name=cfg.no_run.timezone,
                )
                mt5_data_untyped = future.result(timeout=20)
                if isinstance(mt5_data_untyped, SafeData):
                    mt5_data = mt5_data_untyped
            except TimeoutError:
                error_msg = "Lấy dữ liệu snapshot thất bại (Timeout). Terminal có thể bị treo."
                logger.error(error_msg)
            except Exception as e:
                error_msg = f"Lỗi khi lấy snapshot: {e}"
                logger.exception(error_msg)

        def update_ui():
            self.ui_status("Sẵn sàng.")
            if mt5_data and mt5_data.is_valid():
                ui_builder.show_json_popup(self.root, "MT5 Data Snapshot", mt5_data.to_dict())
            else:
                # Hiển thị lỗi cụ thể nếu có, hoặc lỗi chung
                final_error = error_msg or "Không thể lấy dữ liệu snapshot hợp lệ."
                self.show_error_message("Lỗi Snapshot MT5", final_error)

        self.ui_queue.put(update_ui)

    # --- API Key & Env Methods ---
    def _load_env(self):
        """Mở hộp thoại chọn file .env và bắt đầu quá trình tải trong luồng nền."""
        logger.debug("Mở hộp thoại chọn file .env.")
        env_path_str = filedialog.askopenfilename(
            title="Chọn file .env", filetypes=[(".env files", "*.env")]
        )
        if not (env_path_str and Path(env_path_str).exists()):
            logger.debug("Người dùng đã hủy chọn file .env.")
            return

        self.ui_status("Đang tải file .env...")
        self.io_controller.run(
            worker=self._load_env_worker,
            args=(env_path_str,),
            group="ui.io.env",
            name="ui.io.load_env",
            metadata={"component": "ui", "operation": "load_env"},
        )

    def _load_env_worker(self, env_path: str):
        """Worker chạy nền để đọc và áp dụng các biến từ file .env."""
        try:
            # Tải các biến môi trường vào một dict tạm thời thay vì os.environ
            # để tránh các vấn đề về thread-safety với biến môi trường toàn cục.
            env_vars = load_dotenv(dotenv_path=env_path, override=True)
            
            keys_found = {}
            if key := os.environ.get("GOOGLE_API_KEY"):
                keys_found["google"] = key
            if key := os.environ.get("FMP_API_KEY"):
                keys_found["fmp"] = key
            if key := os.environ.get("TE_API_KEY"):
                keys_found["te"] = key

            def update_ui():
                self.ui_status("Sẵn sàng.")
                if not keys_found:
                    ui_builder.show_message("Không tìm thấy", "Không tìm thấy key API nào trong file .env.")
                    return

                keys_loaded_names = []
                if "google" in keys_found:
                    self.api_key_var.set(keys_found["google"])
                    keys_loaded_names.append("GOOGLE_API_KEY")
                if "fmp" in keys_found:
                    self.fmp_api_key_var.set(keys_found["fmp"])
                    keys_loaded_names.append("FMP_API_KEY")
                if "te" in keys_found:
                    self.te_api_key_var.set(keys_found["te"])
                    keys_loaded_names.append("TE_API_KEY")

                msg = f"Đã tải các key sau từ .env:\n- " + "\n- ".join(keys_loaded_names)
                ui_builder.show_message("Thành công", msg)
                logger.info(msg)

            self.ui_queue.put(update_ui)

        except Exception as e:
            logger.exception(f"Lỗi khi tải file .env: {env_path}")
            self.ui_queue.put(lambda: self.show_error_message("Lỗi", f"Không thể tải file .env:\n{e}"))
            self.ui_queue.put(lambda: self.ui_status("Lỗi khi tải .env."))

    def _save_api_safe(self):
        """Bắt đầu quá trình lưu API key an toàn trong luồng nền."""
        logger.debug("Yêu cầu lưu API keys.")
        import json
        keys_to_save = {
            "google": self.api_key_var.get().strip(),
            "fmp": self.fmp_api_key_var.get().strip(),
            "te": self.te_api_key_var.get().strip(),
        }
        keys_to_save = {k: v for k, v in keys_to_save.items() if v}

        if not keys_to_save:
            ui_builder.show_message("Thiếu key", "Vui lòng nhập ít nhất một API key trước khi lưu.")
            return
        
        self.ui_status("Đang lưu API keys...")
        self.io_controller.run(
            worker=self._save_api_safe_worker,
            args=(keys_to_save,),
            group="ui.io.api_keys",
            name="ui.io.save_api_keys",
            metadata={"component": "ui", "operation": "save_api_keys"},
        )

    def _save_api_safe_worker(self, keys_to_save: dict):
        """Worker chạy nền để mã hóa và ghi API keys vào file."""
        import json
        try:
            json_string = json.dumps(keys_to_save, indent=2)
            encrypted_content = general_utils.obfuscate_text(json_string, "all_api_keys_salt")
            PATHS.ALL_API_KEYS_ENC.write_text(encrypted_content, encoding="utf-8")
            logger.info("Đã lưu các API key đã mã hóa.")
            ui_builder.enqueue(self, lambda: ui_builder.show_message("Thành công", "Đã mã hóa và lưu các API key."))
            ui_builder.enqueue(self, lambda: self.ui_status("Đã lưu API keys."))
        except Exception as e:
            logger.exception("Lỗi khi lưu API keys.")
            ui_builder.enqueue(self, lambda: ui_builder.show_message("Lỗi", f"Không thể lưu API keys: {e}"))
            ui_builder.enqueue(self, lambda: self.ui_status("Lỗi khi lưu API keys."))

    def _delete_api_safe(self):
        """Bắt đầu quá trình xóa API key an toàn trong luồng nền."""
        logger.debug("Yêu cầu xóa API keys.")
        self.ui_status("Đang xóa API keys...")
        self.io_controller.run(
            worker=self._delete_api_safe_worker,
            group="ui.io.api_keys",
            name="ui.io.delete_api_keys",
            metadata={"component": "ui", "operation": "delete_api_keys"},
        )

    def _delete_api_safe_worker(self):
        """Worker chạy nền để xóa file API key."""
        file_to_delete = PATHS.ALL_API_KEYS_ENC
        if not file_to_delete.exists() and PATHS.API_KEY_ENC.exists():
            file_to_delete = PATHS.API_KEY_ENC
        
        if not file_to_delete.exists():
            ui_builder.enqueue(self, lambda: ui_builder.show_message("Thông báo", "Không có API key nào được lưu."))
            ui_builder.enqueue(self, lambda: self.ui_status("Sẵn sàng."))
            return

        try:
            file_to_delete.unlink()
            
            def update_ui():
                self.api_key_var.set("")
                self.fmp_api_key_var.set("")
                self.te_api_key_var.set("")
                ui_builder.show_message("Thành công", "Đã xóa các API key đã lưu.")
                self.ui_status("Đã xóa API keys.")
            
            ui_builder.enqueue(self, update_ui)
            logger.info("Đã xóa tệp API key đã mã hóa.")
        except Exception as e:
            logger.exception("Lỗi khi xóa API key.")
            ui_builder.enqueue(self, lambda: ui_builder.show_message("Lỗi", f"Không thể xóa API key: {e}"))
            ui_builder.enqueue(self, lambda: self.ui_status("Lỗi khi xóa API keys."))

    def _telegram_test(self):
        """Gửi tin nhắn thử nghiệm qua Telegram."""
        # Placeholder for actual implementation
        ui_builder.show_message("Telegram", "Chức năng gửi thử Telegram chưa được cài đặt.")
        logger.info("Nút gửi thử Telegram đã được nhấn.")

    def _delete_workspace(self):
        """Bắt đầu quá trình xóa file workspace trong luồng nền."""
        logger.debug("Yêu cầu xóa workspace.")
        if ui_builder.ask_confirmation(
            title="Xác nhận Xóa",
            message="Bạn có chắc chắn muốn xóa file workspace hiện tại không?",
        ):
            self.ui_status("Đang xóa workspace...")
            self.io_controller.run(
                worker=self._delete_workspace_worker,
                group="ui.workspace",
                name="ui.workspace.delete",
                metadata={"component": "ui", "operation": "delete_workspace"},
            )

    def _delete_workspace_worker(self):
        """Worker chạy nền để xóa file workspace."""
        try:
            workspace_config.delete_workspace()
            logger.info("Đã xóa file workspace.")
            ui_builder.enqueue(self, lambda: ui_builder.show_message("Thành công", "Đã xóa file workspace."))
            ui_builder.enqueue(self, lambda: self.ui_status("Đã xóa workspace."))
        except Exception as e:
            logger.exception("Lỗi khi xóa file workspace.")
            ui_builder.enqueue(self, lambda: ui_builder.show_message("Lỗi", f"Không thể xóa file workspace:\n{e}"))
            ui_builder.enqueue(self, lambda: self.ui_status("Lỗi khi xóa workspace."))
