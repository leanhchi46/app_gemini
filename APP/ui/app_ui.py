# -*- coding: utf-8 -*-
"""
Lớp giao diện người dùng chính (AppUI).

Chịu trách nhiệm khởi tạo, quản lý trạng thái và điều phối các sự kiện
từ giao diện người dùng, đồng thời ủy quyền các tác vụ xử lý logic
cho các thành phần khác như services, workers, và persistence handlers.
"""

from __future__ import annotations

import logging
import os
import queue
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, ttk
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from dotenv import load_dotenv
from google.api_core import exceptions

from APP.configs import workspace_config
from APP.configs.app_config import (ApiConfig, AutoTradeConfig, ContextConfig,
                                    FolderConfig, ImageProcessingConfig,
                                    MT5Config, NewsConfig, NoRunConfig,
                                    NoTradeConfig, PersistenceConfig,
                                    RunConfig, TelegramConfig, UploadConfig)
from APP.configs.constants import FILES, MODELS, PATHS
from APP.core.analysis_worker import AnalysisWorker
from APP.services import gemini_service, mt5_service
from APP.ui.components.chart_tab import ChartTab
from APP.ui.components.history_manager import HistoryManager
from APP.ui.components.prompt_manager import PromptManager
from APP.ui.utils import ui_builder
from APP.ui.utils.timeframe_detector import TimeframeDetector
from APP.utils import general_utils

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

        # Component Managers (initialized below)
        self.history_manager: HistoryManager
        self.prompt_manager: PromptManager
        self.timeframe_detector: TimeframeDetector

        # Tkinter Variables (initialized in _init_tk_variables)
        self.folder_path: tk.StringVar
        self.status_var: tk.StringVar
        self.progress_var: tk.DoubleVar
        self.api_key_var: tk.StringVar
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
        self.trade_allow_session_asia_var: tk.BooleanVar
        self.trade_allow_session_london_var: tk.BooleanVar
        self.trade_allow_session_ny_var: tk.BooleanVar
        self.news_block_enabled_var: tk.BooleanVar
        self.trade_news_block_before_min_var: tk.IntVar
        self.trade_news_block_after_min_var: tk.IntVar
        self.news_cache_ttl_var: tk.IntVar
        self.persistence_max_md_reports_var: tk.IntVar
        self.prompt_file_path_var: tk.StringVar
        self.auto_load_prompt_txt_var: tk.BooleanVar

        # Locks and Queues
        self._trade_log_lock = threading.Lock()
        self.ui_queue: queue.Queue[Any] = queue.Queue()

        # UI Widget Attributes (khai báo trước để pyright nhận diện)
        self.tree: Optional[ttk.Treeview] = None
        self.detail_text: Optional[tk.Text] = None
        self.nb: Optional[ttk.Notebook] = None
        self.prompt_nb: Optional[ttk.Notebook] = None
        self.model_combo: Optional[ttk.Combobox] = None
        self.api_entry: Optional[tk.Entry] = None
        self.prompt_entry_run_text: Optional[tk.Text] = None
        self.prompt_no_entry_text: Optional[tk.Text] = None
        self.stop_btn: Optional[ttk.Button] = None
        self.folder_label: Optional[ttk.Entry] = None
        self.autorun_interval_spin: Optional[ttk.Spinbox] = None
        self.chart_tab: Optional[ChartTab] = None
        self.history_list: Optional[tk.Listbox] = None
        self.json_list: Optional[tk.Listbox] = None


        # State Variables
        self.is_running = False
        self.stop_flag = False
        self.results: list[dict] = []
        self.combined_report_text = ""
        self.active_worker_thread: Optional[threading.Thread] = None
        self.active_executor = None
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

        # Post-UI setup
        self._configure_gemini_api_and_update_ui()
        self.apply_config(self.initial_config)
        ui_builder.poll_ui_queue(self)
        self._schedule_mt5_connection_check()

        # Load initial data through managers
        self.prompt_manager.load_prompts_from_disk()

        # Cải tiến: Đảm bảo danh sách tệp được làm mới sau khi mọi thứ đã được tải
        # Điều này khắc phục trường hợp UI không hiển thị danh sách tệp khi khởi động
        logger.info("Thực hiện làm mới danh sách báo cáo và JSON lần cuối khi khởi động.")
        self.history_manager.refresh_history_list()
        self.history_manager.refresh_json_list()

        self.root.protocol("WM_DELETE_WINDOW", self.shutdown)
        logger.debug("AppUI đã khởi tạo xong.")

    def shutdown(self):
        """
        Xử lý sự kiện đóng cửa sổ ứng dụng một cách an toàn.
        Thu thập cấu hình, lưu vào file, và hủy các tác vụ đang chạy.
        """
        logger.info("Bắt đầu quy trình tắt ứng dụng.")

        # Hủy các tác vụ hẹn giờ
        if self._autorun_job:
            self.root.after_cancel(self._autorun_job)
            self._autorun_job = None
        if self._mt5_reconnect_job:
            self.root.after_cancel(self._mt5_reconnect_job)
            self._mt5_reconnect_job = None
        if self._mt5_check_connection_job:
            self.root.after_cancel(self._mt5_check_connection_job)
            self._mt5_check_connection_job = None

        # Thu thập và lưu cấu hình
        try:
            config_data = self._collect_config_data()
            workspace_config.save_config_to_file(config_data)
            logger.info("Đã lưu cấu hình workspace thành công.")
        except Exception:
            logger.exception("Lỗi khi lưu cấu hình workspace.")

        self.root.destroy()
        logger.info("Ứng dụng đã đóng.")

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
        api_init = ""
        if PATHS.API_KEY_ENC.exists():
            api_init = general_utils.deobfuscate_text(
                PATHS.API_KEY_ENC.read_text(encoding="utf-8"), "api_key_salt"
            )
        api_init = api_init or os.environ.get("GOOGLE_API_KEY", "")
        self.api_key_var = tk.StringVar(value=api_init)
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

        # Persistence
        self.persistence_max_md_reports_var = tk.IntVar(value=10)

        # Prompts
        self.prompt_file_path_var = tk.StringVar(value="")
        self.auto_load_prompt_txt_var = tk.BooleanVar(value=True)
        logger.debug("Các biến Tkinter đã được khởi tạo.")

    def _collect_config_data(self) -> dict:
        """
        Thu thập tất cả các giá trị cấu hình từ các biến Tkinter và trả về một dictionary.
        """
        logger.debug("Bắt đầu thu thập dữ liệu cấu hình từ UI.")
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
            "no_run": {
                "weekend_enabled": self.no_run_weekend_enabled_var.get(),
                "killzone_enabled": self.norun_killzone_var.get(),
                "holiday_check_enabled": self.no_run_holiday_check_var.get(),
                "holiday_check_country": self.no_run_holiday_country_var.get(),
                "timezone": self.no_run_timezone_var.get(),
            },
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
        folder_path = get_nested(folder_cfg, ["folder_path"], "")
        if folder_path and Path(folder_path).exists():
            self.folder_path.set(folder_path)
            self._load_files(folder_path)

        # ... (các dòng khác)

        mt5_cfg = config_data.get("mt5", {})
        self.mt5_enabled_var.set(get_nested(mt5_cfg, ["enabled"], False))
        self.mt5_term_path_var.set(get_nested(mt5_cfg, ["terminal_path"], ""))
        self.mt5_symbol_var.set(get_nested(mt5_cfg, ["symbol"], ""))
        # SỬA LỖI: Xóa bỏ logic tự động suy luận symbol.
        # Logic này gây ra lỗi khi thư mục được chọn là thư mục cha (ví dụ: Screenshots)
        # thay vì thư mục con của symbol (ví dụ: Screenshots/XAUUSD).
        # Giờ đây, ứng dụng sẽ chỉ dựa vào symbol được lưu trong workspace.

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

        news_cfg = config_data.get("news", {})
        self.news_block_enabled_var.set(get_nested(news_cfg, ["block_enabled"], True))
        self.trade_news_block_before_min_var.set(get_nested(news_cfg, ["block_before_min"], 15))
        self.trade_news_block_after_min_var.set(get_nested(news_cfg, ["block_after_min"], 15))
        self.news_cache_ttl_var.set(get_nested(news_cfg, ["cache_ttl_sec"], 300))

        persistence_cfg = config_data.get("persistence", {})
        self.persistence_max_md_reports_var.set(get_nested(persistence_cfg, ["max_md_reports"], 10))

        prompts_cfg = config_data.get("prompts", {})
        self.prompt_file_path_var.set(get_nested(prompts_cfg, ["prompt_file_path"], ""))
        self.auto_load_prompt_txt_var.set(get_nested(prompts_cfg, ["auto_load_prompt_txt"], True))

        self.model_var.set(config_data.get("model", MODELS.DEFAULT_VISION))
        self.autorun_var.set(config_data.get("autorun", False))
        self.autorun_seconds_var.set(config_data.get("autorun_secs", 60))

        # Kích hoạt autorun nếu cần
        if self.autorun_var.get():
            self._toggle_autorun()

        # Tải prompt tự động nếu được cấu hình
        if self.auto_load_prompt_txt_var.get():
            self.prompt_manager.load_prompts_from_disk(silent=True)

        # Cập nhật 1: Tự động làm mới danh sách history và json sau khi áp dụng config
        # Điều này đảm bảo UI hiển thị đúng trạng thái khi khởi động
        self.history_manager.refresh_history_list()
        self.history_manager.refresh_json_list()

        logger.info("Đã áp dụng cấu hình lên UI thành công.")
    def _snapshot_config(self) -> "RunConfig":
        """
        Chụp lại toàn bộ trạng thái cấu hình hiện tại từ giao diện người dùng
        và trả về một đối tượng RunConfig đã được nhóm lại.
        """
        logger.debug("Bắt đầu chụp ảnh nhanh cấu hình từ UI.")
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
            ),
            persistence=PersistenceConfig(
                max_md_reports=self.persistence_max_md_reports_var.get()
            ),
        )

    def _save_workspace(self):
        """Thu thập cấu hình hiện tại từ UI và lưu vào file workspace."""
        logger.info("Yêu cầu lưu workspace từ UI.")
        try:
            config_data = self._collect_config_data()
            workspace_config.save_config_to_file(config_data)
            ui_builder.show_message("Thành công", "Đã lưu cấu hình workspace.")
            logger.info("Đã lưu cấu hình workspace thành công.")
        except Exception:
            logger.exception("Lỗi khi lưu cấu hình workspace.")
            ui_builder.show_message("Lỗi", "Không thể lưu cấu hình workspace.")

    def _load_workspace(self):
        """Tải cấu hình từ file workspace và áp dụng lên UI."""
        logger.info("Yêu cầu tải workspace từ UI.")
        try:
            config_data = workspace_config.load_config_from_file()
            if config_data:
                self.apply_config(config_data)
                ui_builder.show_message("Thành công", "Đã tải và áp dụng cấu hình workspace.")
                logger.info("Đã tải và áp dụng cấu hình workspace thành công.")
            else:
                ui_builder.show_message("Thông báo", "Không tìm thấy file workspace hoặc file bị rỗng.")
                logger.info("Không tìm thấy file workspace hoặc file bị rỗng.")
        except Exception:
            logger.exception("Lỗi khi tải cấu hình workspace.")
            ui_builder.show_message("Lỗi", "Không thể tải hoặc áp dụng cấu hình workspace.")

    # --- Action Methods ---
    def start_analysis(self):
        """Bắt đầu một phiên phân tích mới."""
        logger.info("Yêu cầu bắt đầu phân tích từ UI.")
        if self.is_running:
            self.show_error_message("Đang chạy", "Một phân tích khác đang chạy.")
            logger.warning("Yêu cầu bắt đầu phân tích bị từ chối: một tiến trình khác đang chạy.")
            return
        folder = self.folder_path.get()
        if not folder or not Path(folder).is_dir():
            self.show_error_message("Lỗi", "Vui lòng chọn một thư mục hợp lệ.")
            logger.error("Yêu cầu bắt đầu phân tích bị từ chối: thư mục không hợp lệ.")
            return

        self.is_running = True
        self.stop_flag = False
        ui_builder.toggle_controls_state(self, "disabled")
        cfg = self._snapshot_config()
        self.run_config = cfg

        worker_instance = AnalysisWorker(app=self, cfg=cfg)
        self.active_worker_thread = threading.Thread(target=worker_instance.run, daemon=True)
        self.active_worker_thread.start()
        logger.info("Đã khởi tạo và bắt đầu luồng AnalysisWorker.")

    def stop_analysis(self):
        """Gửi tín hiệu dừng cho luồng worker đang chạy."""
        if not self.is_running:
            return
        logger.info("Yêu cầu dừng phân tích từ UI.")
        self.stop_flag = True
        if self.active_executor:
            self.active_executor.shutdown(wait=False, cancel_futures=True)
        self.ui_status("Đang dừng...")

    def choose_folder(self):
        """Mở hộp thoại cho người dùng chọn thư mục chứa ảnh."""
        logger.debug("Mở hộp thoại chọn thư mục.")
        folder = filedialog.askdirectory(title="Chọn thư mục chứa ảnh")
        if not folder:
            logger.debug("Người dùng đã hủy chọn thư mục.")
            return
        self.folder_path.set(folder)
        self._load_files(folder)
        logger.info(f"Đã chọn thư mục: {folder}")

        # Cải tiến: Sau khi chọn thư mục mới, làm mới danh sách báo cáo
        logger.debug("Làm mới danh sách báo cáo sau khi chọn thư mục mới.")
        self.history_manager.refresh_history_list()
        self.history_manager.refresh_json_list()

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

        # Chạy tác vụ quét thư mục trong một luồng riêng
        scan_thread = threading.Thread(
            target=self._scan_folder_worker, args=(folder,), daemon=True
        )
        scan_thread.start()

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
        """Xuất báo cáo phân tích tổng hợp ra file Markdown."""
        logger.debug("Chuẩn bị xuất báo cáo Markdown.")
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

        try:
            # Sửa lỗi: Ghi trực tiếp nội dung vào file thay vì gọi hàm không tồn tại
            Path(out_path_str).write_text(self.combined_report_text, encoding="utf-8")
            self.show_error_message("Thành công", f"Đã lưu báo cáo tại:\n{out_path_str}")
            logger.info(f"Đã lưu báo cáo Markdown thành công tại: {out_path_str}.")
        except Exception:
            logger.exception("Lỗi khi ghi báo cáo Markdown.")
            self.show_error_message("Lỗi ghi file", "Không thể lưu báo cáo.")

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
        """Chuyển đổi trạng thái hiển thị của ô nhập API key."""
        if self.api_entry:
            self.api_entry.configure(show="" if self.api_entry.cget("show") == "*" else "*")

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
        threading.Thread(target=self._update_model_list_worker, args=(api_key,), daemon=True).start()

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
        Được gọi mỗi khi symbol thay đổi. Làm mới danh sách lịch sử và json.
        """
        logger.debug(f"Symbol đã thay đổi thành: {self.mt5_symbol_var.get()}, làm mới danh sách tệp.")
        self.history_manager.refresh_history_list()
        self.history_manager.refresh_json_list()

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
        self.ui_status("Đã dừng bởi người dùng.")
        self.ui_progress(0)
        ui_builder.toggle_controls_state(self, "normal")
        self._schedule_next_autorun()

    def _finalize_done(self):
        """Hoàn tất tác vụ khi chạy xong."""
        self.is_running = False
        self.stop_flag = False
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
        if not self.autorun_var.get() or self.is_running:
            return
        interval_ms = self.autorun_seconds_var.get() * 1000
        logger.debug(f"Lên lịch chạy tự động tiếp theo sau {interval_ms}ms.")
        self._autorun_job = self.root.after(interval_ms, self._autorun_tick)

    def _autorun_tick(self):
        """Hàm được gọi khi đến thời gian tự động chạy."""
        logger.info("Autorun tick: Đã đến giờ chạy.")
        if self.is_running:
            logger.warning("Autorun tick: Bỏ qua vì một tiến trình khác đang chạy.")
            self._schedule_next_autorun()
            return
        if not self.mt5_enabled_var.get() or not mt5_service.is_connected():
            logger.warning("Autorun tick: Bỏ qua vì MT5 chưa được kết nối.")
            self._schedule_next_autorun()
            return

        logger.info("Autorun tick: Bắt đầu phân tích tự động.")
        self.start_analysis()

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

    def _mt5_guess_symbol(self):
        """Đoán symbol từ tên file ảnh."""
        if not self.results:
            self.show_error_message("Đoán Symbol", "Vui lòng nạp ảnh trước.")
            return
        first_name = self.results[0].get("name", "")
        symbol = general_utils.extract_symbol_from_filename(first_name)
        if symbol:
            self.mt5_symbol_var.set(symbol)
            logger.info(f"Đã đoán được symbol: {symbol}")
        else:
            self.show_error_message("Đoán Symbol", "Không thể đoán symbol từ tên file.")

    def _mt5_connect(self):
        """Thực hiện kết nối đến MetaTrader 5."""
        logger.info("Yêu cầu kết nối MT5 từ UI.")
        path = self.mt5_term_path_var.get()
        if not path or not Path(path).exists():
            self.show_error_message("Lỗi MT5", "Đường dẫn terminal64.exe không hợp lệ.")
            return

        ok, msg = mt5_service.connect(path=path)
        self.mt5_status_var.set(str(msg))
        if ok:
            self.show_error_message("MT5", "Kết nối thành công.")
            self._schedule_mt5_connection_check()
        else:
            self.show_error_message("MT5", str(msg))

    def _schedule_mt5_connection_check(self):
        """Lên lịch kiểm tra kết nối MT5 định kỳ."""
        if self._mt5_check_connection_job:
            self.root.after_cancel(self._mt5_check_connection_job)

        if self.mt5_enabled_var.get():
            is_connected = mt5_service.is_connected()
            status = "MT5: Đã kết nối" if is_connected else "MT5: Mất kết nối"
            self.mt5_status_var.set(status)
            if not is_connected:
                logger.warning("Mất kết nối MT5, sẽ thử kết nối lại.")
                self._mt5_connect() # Thử kết nối lại ngay

        self._mt5_check_connection_job = self.root.after(15000, self._schedule_mt5_connection_check)

    def _mt5_snapshot_popup(self):
        """Hiển thị cửa sổ popup chứa dữ liệu MT5 hiện tại."""
        logger.debug("Yêu cầu snapshot dữ liệu MT5.")
        if not mt5_service.is_connected():
            self.show_error_message("MT5", "Chưa kết nối MT5.")
            return
        cfg = self._snapshot_config()
        mt5_data = mt5_service.get_market_data(cfg.mt5) # type: ignore
        if mt5_data:
            ui_builder.show_json_popup(self.root, "MT5 Data Snapshot", mt5_data.to_dict()) # type: ignore
        else:
            self.show_error_message("MT5", "Không thể lấy dữ liệu snapshot.")

    # --- API Key & Env Methods ---
    def _load_env(self):
        """Tải biến môi trường từ file .env."""
        logger.debug("Mở hộp thoại chọn file .env.")
        env_path = filedialog.askopenfilename(title="Chọn file .env", filetypes=[(".env files", "*.env")])
        if env_path and Path(env_path).exists():
            load_dotenv(dotenv_path=env_path, override=True)
            api_key = os.environ.get("GOOGLE_API_KEY")
            if api_key:
                self.api_key_var.set(api_key)
                ui_builder.show_message("Thành công", "Đã tải GOOGLE_API_KEY từ .env.")
                logger.info("Đã tải GOOGLE_API_KEY từ file .env.")
            else:
                ui_builder.show_message("Thiếu key", "Không tìm thấy GOOGLE_API_KEY trong file .env.")

    def _save_api_safe(self):
        """Mã hóa và lưu API key vào tệp."""
        api_key = self.api_key_var.get()
        if not api_key:
            ui_builder.show_message("Thiếu key", "Vui lòng nhập API key trước khi lưu.")
            return
        try:
            encrypted_key = general_utils.obfuscate_text(api_key, "api_key_salt")
            PATHS.API_KEY_ENC.write_text(encrypted_key, encoding="utf-8")
            ui_builder.show_message("Thành công", "Đã mã hóa và lưu API key.")
            logger.info("Đã lưu API key đã mã hóa.")
        except Exception as e:
            logger.exception("Lỗi khi lưu API key.")
            ui_builder.show_message("Lỗi", f"Không thể lưu API key: {e}")

    def _delete_api_safe(self):
        """Xóa tệp chứa API key đã mã hóa."""
        if PATHS.API_KEY_ENC.exists():
            try:
                PATHS.API_KEY_ENC.unlink()
                ui_builder.show_message("Thành công", "Đã xóa API key đã lưu.")
                logger.info("Đã xóa tệp API key đã mã hóa.")
            except Exception as e:
                logger.exception("Lỗi khi xóa API key.")
                ui_builder.show_message("Lỗi", f"Không thể xóa API key: {e}")
        else:
            ui_builder.show_message("Thông báo", "Không có API key nào được lưu.")

    def _telegram_test(self):
        """Gửi tin nhắn thử nghiệm qua Telegram."""
        # Placeholder for actual implementation
        ui_builder.show_message("Telegram", "Chức năng gửi thử Telegram chưa được cài đặt.")
        logger.info("Nút gửi thử Telegram đã được nhấn.")

    def _delete_workspace(self):
        """Xóa file workspace."""
        if ui_builder.ask_confirmation(
            title="Xác nhận Xóa",
            message="Bạn có chắc chắn muốn xóa file workspace hiện tại không?",
        ):
            try:
                workspace_config.delete_workspace()
                ui_builder.show_message(
                    title="Thành công", message="Đã xóa file workspace."
                )
                logger.info("Đã xóa file workspace.")
            except Exception as e:
                ui_builder.show_message(
                    title="Lỗi", message=f"Không thể xóa file workspace:\n{e}"
                )
                logger.exception("Lỗi khi xóa file workspace.")
