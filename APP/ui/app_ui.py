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
from tkinter import filedialog
from typing import TYPE_CHECKING, Optional

import google.generativeai as genai
from dotenv import load_dotenv

from APP.configs import workspace_config
from APP.configs.app_config import (AutoTradeConfig, ContextConfig,
                                    FolderConfig, ImageProcessingConfig,
                                    MT5Config, NewsConfig, NoRunConfig,
                                    NoTradeConfig, PersistenceConfig,
                                    RunConfig, TelegramConfig, UploadConfig)
from APP.configs.constants import FILES, MODELS, PATHS
from APP.core.analysis_worker import AnalysisWorker
from APP.persistence import log_handler, md_handler
from APP.services import mt5_service, news_service
from APP.ui.components.history_manager import HistoryManager
from APP.ui.components.prompt_manager import PromptManager
from APP.ui.utils import ui_builder
from APP.ui.utils.timeframe_detector import TimeframeDetector
from APP.utils import general_utils

if TYPE_CHECKING:
    from APP.utils.safe_data import SafeData

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

        # Locks and Queues
        self._trade_log_lock = threading.Lock()
        self.ui_queue = queue.Queue()

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

        # Build the UI layout
        ui_builder.build_ui(self)

        # Initialize component managers
        self.history_manager = HistoryManager(self)
        self.prompt_manager = PromptManager(self)
        self.timeframe_detector = TimeframeDetector()

        # Post-UI setup
        self._configure_gemini_api_and_update_ui()
        self.apply_config(self.initial_config)
        ui_builder.poll_ui_queue(self)
        self._schedule_mt5_connection_check()

        # Load initial data through managers
        self.history_manager.refresh_history_list()
        self.history_manager.refresh_json_list()
        self.prompt_manager.load_prompts_from_disk()

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
        self.status_var = tk.StringVar(value="Sẵn sàng.")
        self.progress_var = tk.DoubleVar(value=0.0)

        # API & Model
        api_init = ""
        if PATHS.API_KEY_ENC.exists():
            api_init = general_utils.deobfuscate_text(PATHS.API_KEY_ENC.read_text(encoding="utf-8"))
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
        self.mt5_status_var = tk.StringVar(value="MT5: Chưa kết nối")
        self.mt5_n_M1 = tk.IntVar(value=120)
        self.mt5_n_M5 = tk.IntVar(value=180)
        self.mt5_n_M15 = tk.IntVar(value=96)
        self.mt5_n_H1 = tk.IntVar(value=120)

        # No-Run / No-Trade Conditions
        self.no_run_weekend_enabled_var = tk.BooleanVar(value=True)
        self.norun_killzone_var = tk.BooleanVar(value=True)
        self.no_run_holiday_check_var = tk.BooleanVar(value=True)
        self.no_trade_enabled_var = tk.BooleanVar(value=True)
        self.nt_spread_max_pips_var = tk.DoubleVar(value=2.5)
        self.nt_min_atr_m5_pips_var = tk.DoubleVar(value=3.0)

        # Upload & Image Processing
        self.upload_workers_var = tk.IntVar(value=4)
        self.cache_enabled_var = tk.BooleanVar(value=True)
        self.optimize_lossless_var = tk.BooleanVar(value=False)
        self.only_generate_if_changed_var = tk.BooleanVar(value=False)

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
            "context": {
                "ctx_limit": self.context_limit_chars_var.get(),
                "create_ctx_json": self.create_ctx_json_var.get(),
                "prefer_ctx_json": self.prefer_ctx_json_var.get(),
                "ctx_json_n": self.ctx_json_n_var.get(),
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
            self.history_manager.refresh_history_list()
            self.history_manager.refresh_json_list()
        self.delete_after_var.set(get_nested(folder_cfg, ["delete_after"], True))
        self.max_files_var.set(get_nested(folder_cfg, ["max_files"], 0))
        self.only_generate_if_changed_var.set(get_nested(folder_cfg, ["only_generate_if_changed"], False))

        upload_cfg = config_data.get("upload", {})
        self.upload_workers_var.set(get_nested(upload_cfg, ["upload_workers"], 4))
        self.cache_enabled_var.set(get_nested(upload_cfg, ["cache_enabled"], True))
        self.optimize_lossless_var.set(get_nested(upload_cfg, ["optimize_lossless"], False))

        context_cfg = config_data.get("context", {})
        self.context_limit_chars_var.set(get_nested(context_cfg, ["ctx_limit"], 2000))
        self.create_ctx_json_var.set(get_nested(context_cfg, ["create_ctx_json"], True))
        self.prefer_ctx_json_var.set(get_nested(context_cfg, ["prefer_ctx_json"], True))
        self.ctx_json_n_var.set(get_nested(context_cfg, ["ctx_json_n"], 5))

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
            image_processing=ImageProcessingConfig(),
            context=ContextConfig(
                ctx_limit=self.context_limit_chars_var.get(),
                create_ctx_json=self.create_ctx_json_var.get(),
                prefer_ctx_json=self.prefer_ctx_json_var.get(),
                ctx_json_n=self.ctx_json_n_var.get(),
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
                terminal_path=self.mt5_term_path_var.get(),
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
            model=self.model_var.get(),
            prompts=self.prompt_manager.get_prompts(),
        )

    def _save_workspace(self):
        """Thu thập cấu hình hiện tại từ UI và lưu vào file workspace."""
        logger.info("Yêu cầu lưu workspace từ UI.")
        try:
            config_data = self._collect_config_data()
            workspace_config.save_config_to_file(config_data)
            ui_builder.ui_message(self, "info", "Thành công", "Đã lưu cấu hình workspace.")
            logger.info("Đã lưu cấu hình workspace thành công.")
        except Exception:
            logger.exception("Lỗi khi lưu cấu hình workspace.")
            ui_builder.message(self, "error", "Lỗi", "Không thể lưu cấu hình workspace.")

    def _load_workspace(self):
        """Tải cấu hình từ file workspace và áp dụng lên UI."""
        logger.info("Yêu cầu tải workspace từ UI.")
        try:
            config_data = workspace_config.load_config_from_file()
            if config_data:
                self.apply_config(config_data)
                ui_builder.ui_message(self, "info", "Thành công", "Đã tải và áp dụng cấu hình workspace.")
                logger.info("Đã tải và áp dụng cấu hình workspace thành công.")
            else:
                ui_builder.ui_message(self, "info", "Thông báo", "Không tìm thấy file workspace hoặc file bị rỗng.")
                logger.info("Không tìm thấy file workspace hoặc file bị rỗng.")
        except Exception:
            logger.exception("Lỗi khi tải cấu hình workspace.")
            ui_builder.message(self, "error", "Lỗi", "Không thể tải hoặc áp dụng cấu hình workspace.")

    # --- Action Methods ---
    def start_analysis(self):
        """Bắt đầu một phiên phân tích mới."""
        logger.info("Yêu cầu bắt đầu phân tích từ UI.")
        if self.is_running:
            ui_builder.ui_message(self, "warning", "Đang chạy", "Một phân tích khác đang chạy.")
            logger.warning("Yêu cầu bắt đầu phân tích bị từ chối: một tiến trình khác đang chạy.")
            return
        folder = self.folder_path.get()
        if not folder or not Path(folder).is_dir():
            ui_builder.ui_message(self, "error", "Lỗi", "Vui lòng chọn một thư mục hợp lệ.")
            logger.error("Yêu cầu bắt đầu phân tích bị từ chối: thư mục không hợp lệ.")
            return

        self.is_running = True
        self.stop_flag = False
        ui_builder.toggle_controls_state(self, "disabled")
        cfg = self._snapshot_config()

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
        ui_builder.ui_status(self, "Đang dừng...")

    def choose_folder(self):
        """Mở hộp thoại cho người dùng chọn thư mục chứa ảnh."""
        logger.debug("Mở hộp thoại chọn thư mục.")
        folder = filedialog.askdirectory(title="Chọn thư mục chứa ảnh")
        if not folder:
            logger.debug("Người dùng đã hủy chọn thư mục.")
            return
        self.folder_path.set(folder)
        self._load_files(folder)
        self.history_manager.refresh_history_list()
        self.history_manager.refresh_json_list()
        logger.info(f"Đã chọn thư mục: {folder}")

    def _load_files(self, folder: str):
        """
        Xóa kết quả cũ và bắt đầu một luồng mới để quét file ảnh.
        (Cải tiến: Chạy quét file trong luồng riêng để tránh treo UI)
        """
        logger.debug(f"Bắt đầu quá trình tải file từ thư mục: {folder}.")
        self.results.clear()
        self.combined_report_text = ""
        if hasattr(self, "tree"):
            self.tree.delete(*self.tree.get_children())

        ui_builder.ui_status(self, f"Đang quét thư mục {folder}...")
        ui_builder.ui_progress(self, 0)
        if hasattr(self, "detail_text"):
            ui_builder.ui_detail_replace(self, "Báo cáo tổng hợp sẽ hiển thị tại đây.")

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
                    if hasattr(self, "tree"):
                        self.tree.insert("", "end", iid=str(item_idx - 1), values=(item_idx, item_name, "Chưa xử lý"))

                ui_builder.enqueue(self, update_tree)
                count += 1

            msg = f"Đã nạp {count} ảnh. Sẵn sàng." if count else "Không tìm thấy ảnh phù hợp."
            ui_builder.enqueue(self, lambda: ui_builder.ui_status(self, msg))
            logger.info(f"Luồng quét đã hoàn tất, tìm thấy {count} file.")

        except Exception:
            logger.exception(f"Lỗi trong luồng quét thư mục {folder}.")
            ui_builder.enqueue(self, lambda: ui_builder.ui_status(self, "Lỗi khi đọc thư mục."))

    def clear_results(self):
        """Xóa tất cả các kết quả phân tích hiện có."""
        logger.debug("Đang xóa kết quả phân tích.")
        self.results.clear()
        self.combined_report_text = ""
        if hasattr(self, "tree"):
            self.tree.delete(*self.tree.get_children())
        if hasattr(self, "detail_text"):
            ui_builder.ui_detail_replace(self, "Báo cáo tổng hợp sẽ hiển thị tại đây.")
        ui_builder.ui_progress(self, 0)
        ui_builder.ui_status(self, "Đã xoá kết quả.")

    def export_markdown(self):
        """Xuất báo cáo phân tích tổng hợp ra file Markdown."""
        logger.debug("Chuẩn bị xuất báo cáo Markdown.")
        if not self.combined_report_text.strip():
            ui_builder.ui_message(self, "info", "Trống", "Không có nội dung báo cáo để xuất.")
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
            md_handler.save_full_report(
                Path(out_path_str),
                self.combined_report_text,
                self.model_var.get(),
                self.folder_path.get(),
                [r["name"] for r in self.results if r.get("path")]
            )
            ui_builder.ui_message(self, "info", "Thành công", f"Đã lưu: {out_path_str}")
            logger.info(f"Đã lưu báo cáo Markdown thành công tại: {out_path_str}.")
        except Exception:
            logger.exception("Lỗi khi ghi báo cáo Markdown.")
            ui_builder.ui_message(self, "error", "Lỗi ghi file", "Không thể lưu báo cáo.")

    # --- UI Callbacks and Helpers ---
    def _on_tree_select(self, _evt: tk.Event):
        """Xử lý sự kiện khi người dùng chọn một hàng trong bảng."""
        if self.combined_report_text.strip():
            ui_builder.ui_detail_replace(self, self.combined_report_text)
        else:
            ui_builder.ui_detail_replace(self, "Chưa có báo cáo. Hãy bấm 'Bắt đầu'.")

    def _toggle_api_visibility(self):
        """Chuyển đổi trạng thái hiển thị của ô nhập API key."""
        if hasattr(self, 'api_entry'):
            self.api_entry.configure(show="" if self.api_entry.cget("show") == "*" else "*")

    def _configure_gemini_api_and_update_ui(self):
        """Cấu hình Gemini API và cập nhật danh sách model trên UI."""
        api_key = self.api_key_var.get()
        if not api_key:
            ui_builder.ui_status(self, "Vui lòng nhập Google AI API Key.")
            return
        try:
            genai.configure(api_key=api_key)
            logger.info("Đã cấu hình Gemini API thành công.")
            threading.Thread(target=self._update_model_list_in_ui, daemon=True).start()
        except Exception as e:
            logger.error(f"Lỗi cấu hình Gemini API: {e}")
            ui_builder.ui_status(self, f"Lỗi API: {e}")

    def _update_model_list_in_ui(self):
        """Lấy danh sách model từ Gemini và cập nhật combobox."""
        logger.debug("Bắt đầu cập nhật danh sách mô hình AI.")
        try:
            available_models = [m.name for m in genai.list_models() if "generateContent" in m.supported_generation_methods]
            if available_models:
                def update_combo():
                    self.model_combo['values'] = available_models
                    if self.model_var.get() not in available_models:
                        self.model_var.set(MODELS.DEFAULT_VISION)
                    ui_builder.ui_status(self, "Đã cập nhật danh sách mô hình AI.")
                ui_builder.enqueue(self, update_combo)
                logger.info(f"Đã tìm thấy {len(available_models)} mô hình AI.")
            else:
                ui_builder.enqueue(self, lambda: ui_builder.ui_status(self, "Không tìm thấy mô hình AI nào."))
                logger.warning("Không tìm thấy mô hình AI khả dụng nào.")
        except Exception as e:
            logger.error(f"Lỗi khi cập nhật danh sách mô hình AI: {e}")
            ui_builder.enqueue(self, lambda: ui_builder.ui_status(self, "Lỗi khi lấy danh sách mô hình."))

    # --- Autorun Methods ---
    def _toggle_autorun(self):
        """Bật hoặc tắt chế độ tự động chạy phân tích."""
        is_autorun_on = self.autorun_var.get()
        logger.info(f"Chuyển đổi Autorun sang: {'Bật' if is_autorun_on else 'Tắt'}")
        if is_autorun_on:
            self._schedule_next_autorun()
            ui_builder.ui_status(self, f"Tự động chạy Bật. Chờ {self.autorun_seconds_var.get()} giây...")
        elif self._autorun_job:
            self.root.after_cancel(self._autorun_job)
            self._autorun_job = None
            ui_builder.ui_status(self, "Tự động chạy Tắt.")

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
            ui_builder.ui_message(self, "info", "Đoán Symbol", "Vui lòng nạp ảnh trước.")
            return
        first_name = self.results[0].get("name", "")
        symbol = general_utils.extract_symbol_from_filename(first_name)
        if symbol:
            self.mt5_symbol_var.set(symbol)
            logger.info(f"Đã đoán được symbol: {symbol}")
        else:
            ui_builder.ui_message(self, "warning", "Đoán Symbol", "Không thể đoán symbol từ tên file.")

    def _mt5_connect(self):
        """Thực hiện kết nối đến MetaTrader 5."""
        logger.info("Yêu cầu kết nối MT5 từ UI.")
        path = self.mt5_term_path_var.get()
        if not path or not Path(path).exists():
            ui_builder.ui_message(self, "error", "Lỗi MT5", "Đường dẫn terminal64.exe không hợp lệ.")
            return

        ok, msg = mt5_service.initialize(terminal_path=path)
        self.mt5_status_var.set(msg)
        if ok:
            ui_builder.ui_message(self, "info", "MT5", "Kết nối thành công.")
            self._schedule_mt5_connection_check()
        else:
            ui_builder.ui_message(self, "error", "MT5", msg)

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
            ui_builder.ui_message(self, "warning", "MT5", "Chưa kết nối MT5.")
            return
        cfg = self._snapshot_config()
        mt5_data = mt5_service.get_market_data(cfg.mt5)
        if mt5_data:
            ui_builder.show_json_popup(self.root, "MT5 Data Snapshot", mt5_data.to_dict())
        else:
            ui_builder.ui_message(self, "error", "MT5", "Không thể lấy dữ liệu snapshot.")

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
                ui_builder.ui_message(self, "info", "Thành công", "Đã tải GOOGLE_API_KEY từ .env.")
                logger.info("Đã tải GOOGLE_API_KEY từ file .env.")
            else:
                ui_builder.ui_message(self, "warning", "Thiếu key", "Không tìm thấy GOOGLE_API_KEY trong file .env.")

    def _save_api_safe(self):
        """Mã hóa và lưu API key vào tệp."""
        api_key = self.api_key_var.get()
        if not api_key:
            ui_builder.ui_message(self, "warning", "Thiếu key", "Vui lòng nhập API key trước khi lưu.")
            return
        try:
            encrypted_key = general_utils.obfuscate_text(api_key)
            PATHS.API_KEY_ENC.write_text(encrypted_key, encoding="utf-8")
            ui_builder.ui_message(self, "info", "Thành công", "Đã mã hóa và lưu API key.")
            logger.info("Đã lưu API key đã mã hóa.")
        except Exception as e:
            logger.exception("Lỗi khi lưu API key.")
            ui_builder.ui_message(self, "error", "Lỗi", f"Không thể lưu API key: {e}")

    def _delete_api_safe(self):
        """Xóa tệp chứa API key đã mã hóa."""
        if PATHS.API_KEY_ENC.exists():
            try:
                PATHS.API_KEY_ENC.unlink()
                ui_builder.ui_message(self, "info", "Thành công", "Đã xóa API key đã lưu.")
                logger.info("Đã xóa tệp API key đã mã hóa.")
            except Exception as e:
                logger.exception("Lỗi khi xóa API key.")
                ui_builder.ui_message(self, "error", "Lỗi", f"Không thể xóa API key: {e}")
        else:
            ui_builder.ui_message(self, "info", "Thông báo", "Không có API key nào được lưu.")
