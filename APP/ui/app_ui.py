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

from APP.configs import workspace_config
from APP.configs.constants import FILES, MODELS, PATHS
from APP.core.analysis_worker import AnalysisWorker
from APP.persistence import json_handler, md_handler, log_handler
from APP.services import mt5_service, telegram_service, news_service
from APP.ui.components import history_manager, prompt_manager
from APP.ui.utils import timeframe_detector, ui_builder
from APP.utils import general_utils
from APP.utils.safe_data import SafeData

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from APP.configs.app_config import (
        RunConfig, FolderConfig, UploadConfig, ContextConfig, TelegramConfig,
        MT5Config, NoTradeConfig, AutoTradeConfig, NewsConfig, ScheduleConfig
    )
    from APP.utils.safe_data import SafeMT5Data


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
        logger.debug("Khởi tạo AppUI.")
        self.root = root
        self.initial_config = initial_config
        self.root.title("TOOL GIAO DỊCH TỰ ĐỘNG")
        self.root.geometry("1180x780")
        self.root.minsize(1024, 660)

        self._trade_log_lock = threading.Lock()
        self._proposed_trade_log_lock = threading.Lock()
        self._vector_db_lock = threading.Lock()
        self._ui_log_lock = threading.Lock()
        self.ui_queue = queue.Queue()

        self._init_tk_variables()

        self.ff_cache_events_local: list = []
        self.ff_cache_fetch_time: float = 0.0

        self.last_no_trade_ok: Optional[bool] = None
        self.last_no_trade_reasons: list[str] = []

        self._news_refresh_lock = threading.Lock()
        self._news_refresh_inflight = False

        self.is_running = False
        self.stop_flag = False
        self.results: list[dict] = []
        self.combined_report_text = ""

        self.active_worker_thread: Optional[threading.Thread] = None
        self.active_executor = None

        self._telegram_test = lambda: ui_builder.ui_message(self, "info", "Telegram", "Chức năng này chưa được cài đặt.")
        self._pick_ca_bundle = lambda: ui_builder.ui_message(self, "info", "Telegram", "Chức năng này chưa được cài đặt.")

        ui_builder.build_ui(self)
        self._configure_gemini_api_and_update_ui()
        
        # Áp dụng cấu hình ban đầu nếu có
        if self.initial_config:
            self.apply_config(self.initial_config)
            
        ui_builder._poll_ui_queue(self)
        self._schedule_mt5_connection_check()

        self.root.protocol("WM_DELETE_WINDOW", self.shutdown)
        logger.debug("AppUI đã khởi tạo xong.")

    def shutdown(self):
        """
        Xử lý sự kiện đóng cửa sổ ứng dụng.
        Thu thập cấu hình, lưu vào file, và hủy các tác vụ đang chạy.
        """
        logger.debug("Đang xử lý sự kiện đóng cửa sổ (shutdown).")
        
        # Thu thập và lưu cấu hình
        config_data = self._collect_config_data()
        workspace_config.save_config_to_file(config_data)

        # Hủy các tác vụ hẹn giờ
        if hasattr(self, '_mt5_reconnect_job') and self._mt5_reconnect_job:
            self.root.after_cancel(self._mt5_reconnect_job)
            self._mt5_reconnect_job = None
        if hasattr(self, '_mt5_check_connection_job') and self._mt5_check_connection_job:
            self.root.after_cancel(self._mt5_check_connection_job)
            self._mt5_check_connection_job = None
        
        self.root.destroy()

    def _init_tk_variables(self):
        """
        Khởi tạo tất cả các biến trạng thái của Tkinter.
        """
        logger.debug("Khởi tạo các biến Tkinter.")
        self.folder_path = tk.StringVar(value="")
        api_init = ""
        if PATHS.API_KEY_ENC.exists():
            api_init = general_utils.deobfuscate_text(PATHS.API_KEY_ENC.read_text(encoding="utf-8"))
        api_init = api_init or os.environ.get("GOOGLE_API_KEY", "")
        self.api_key_var = tk.StringVar(value=api_init)
        self.model_var = tk.StringVar(value=MODELS.DEFAULT_VISION)

        self.api_key_var.trace_add("write", lambda *args: self._configure_gemini_api_and_update_ui())
        logger.debug("Đã thêm trace callback cho api_key_var.")

        self.delete_after_var = tk.BooleanVar(value=True)
        self.max_files_var = tk.IntVar(value=0)
        self.status_var = tk.StringVar(value="Chưa chọn thư mục.")
        self.progress_var = tk.DoubleVar(value=0.0)

        self.autorun_var = tk.BooleanVar(value=False)
        self.autorun_seconds_var = tk.IntVar(value=60)
        self._autorun_job: Optional[str] = None

        self.remember_context_var = tk.BooleanVar(value=True)
        self.context_n_reports_var = tk.IntVar(value=1)
        self.context_limit_chars_var = tk.IntVar(value=2000)
        self.create_ctx_json_var = tk.BooleanVar(value=True)
        self.prefer_ctx_json_var = tk.BooleanVar(value=True)
        self.ctx_json_n_var = tk.IntVar(value=5)

        self.telegram_enabled_var = tk.BooleanVar(value=False)
        self.telegram_token_var = tk.StringVar(value="")
        self.telegram_chat_id_var = tk.StringVar(value="")
        self.telegram_skip_verify_var = tk.BooleanVar(value=False)
        self.telegram_ca_path_var = tk.StringVar(value="")
        self._last_telegram_signature: Optional[str] = None

        self.mt5_enabled_var = tk.BooleanVar(value=False)
        self.mt5_term_path_var = tk.StringVar(value="")
        self.mt5_symbol_var = tk.StringVar(value="")
        self.mt5_status_var = tk.StringVar(value="MT5: chưa kết nối")
        self.mt5_n_M1 = tk.IntVar(value=120)
        self.mt5_n_M5 = tk.IntVar(value=180)
        self.mt5_n_M15 = tk.IntVar(value=96)
        self.mt5_n_H1 = tk.IntVar(value=120)
        self.mt5_initialized = False

        self.no_trade_enabled_var = tk.BooleanVar(value=True)
        self.nt_spread_factor_var = tk.DoubleVar(value=1.2)
        self.nt_min_atr_m5_pips_var = tk.DoubleVar(value=3.0)
        self.nt_min_ticks_per_min_var = tk.IntVar(value=5)

        self.upload_workers_var = tk.IntVar(value=4)
        self.cache_enabled_var = tk.BooleanVar(value=True)
        self.optimize_lossless_var = tk.BooleanVar(value=False)
        self.only_generate_if_changed_var = tk.BooleanVar(value=False)

        self.auto_trade_enabled_var = tk.BooleanVar(value=False)
        self.trade_strict_bias_var = tk.BooleanVar(value=True)
        self.trade_size_mode_var = tk.StringVar(value="lots")
        self.trade_lots_total_var = tk.DoubleVar(value=0.10)
        self.trade_equity_risk_pct_var = tk.DoubleVar(value=1.0)
        self.trade_money_risk_var = tk.DoubleVar(value=10.0)
        self.trade_split_tp1_pct_var = tk.IntVar(value=50)
        self.trade_deviation_points_var = tk.IntVar(value=20)
        self.trade_pending_threshold_points_var = tk.IntVar(value=60)
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

        self.trade_news_block_before_min_var = tk.IntVar(value=15)
        self.trade_news_block_after_min_var = tk.IntVar(value=15)

        self.no_run_weekend_enabled_var = tk.BooleanVar(value=True)
        self.norun_killzone_var = tk.BooleanVar(value=True)

        self.prompt_file_path_var = tk.StringVar(value="")
        self.auto_load_prompt_txt_var = tk.BooleanVar(value=True)
        logger.debug("Các biến Tkinter đã được khởi tạo.")

    def _configure_gemini_api_and_update_ui(self):
        # This logic is now self-contained within AppUI
        pass

    def _collect_config_data(self) -> dict:
        """
        Thu thập tất cả các giá trị cấu hình từ các biến Tkinter và trả về một dictionary.
        """
        logger.debug("Bắt đầu thu thập dữ liệu cấu hình từ UI.")
        return {
            "prompt_file_path": self.prompt_file_path_var.get().strip(),
            "auto_load_prompt_txt": bool(self.auto_load_prompt_txt_var.get()),
            "folder_path": self.folder_path.get().strip(),
            "model": self.model_var.get(),
            "delete_after": bool(self.delete_after_var.get()),
            "max_files": int(self.max_files_var.get()),
            "autorun": bool(self.autorun_var.get()),
            "autorun_secs": int(self.autorun_seconds_var.get()),
            "remember_ctx": bool(self.remember_context_var.get()),
            "ctx_n_reports": int(self.context_n_reports_var.get()),
            "ctx_limit_chars": int(self.context_limit_chars_var.get()),
            "create_ctx_json": bool(self.create_ctx_json_var.get()),
            "prefer_ctx_json": bool(self.prefer_ctx_json_var.get()),
            "ctx_json_n": int(self.ctx_json_n_var.get()),
            "telegram_enabled": bool(self.telegram_enabled_var.get()),
            "telegram_token": self.telegram_token_var.get().strip(),
            "telegram_chat_id": self.telegram_chat_id_var.get().strip(),
            "telegram_skip_verify": bool(self.telegram_skip_verify_var.get()),
            "telegram_ca_path": self.telegram_ca_path_var.get().strip(),
            "mt5_enabled": bool(self.mt5_enabled_var.get()),
            "mt5_term_path": self.mt5_term_path_var.get().strip(),
            "mt5_symbol": self.mt5_symbol_var.get().strip(),
            "mt5_n_M1": int(self.mt5_n_M1.get()),
            "mt5_n_M5": int(self.mt5_n_M5.get()),
            "mt5_n_M15": int(self.mt5_n_M15.get()),
            "mt5_n_H1": int(self.mt5_n_H1.get()),
            "no_trade_enabled": bool(self.no_trade_enabled_var.get()),
            "nt_spread_factor": float(self.nt_spread_factor_var.get()),
            "nt_min_atr_m5_pips": float(self.nt_min_atr_m5_pips_var.get()),
            "nt_min_ticks_per_min": int(self.nt_min_ticks_per_min_var.get()),
            "upload_workers": int(self.upload_workers_var.get()),
            "cache_enabled": bool(self.cache_enabled_var.get()),
            "opt_lossless": bool(self.optimize_lossless_var.get()),
            "only_generate_if_changed": bool(self.only_generate_if_changed_var.get()),
            "auto_trade_enabled": bool(self.auto_trade_enabled_var.get()),
            "trade_strict_bias": bool(self.trade_strict_bias_var.get()),
            "trade_size_mode": self.trade_size_mode_var.get(),
            "trade_lots_total": float(self.trade_lots_total_var.get()),
            "trade_equity_risk_pct": float(self.trade_equity_risk_pct_var.get()),
            "trade_money_risk": float(self.trade_money_risk_var.get()),
            "trade_split_tp1_pct": int(self.trade_split_tp1_pct_var.get()),
            "trade_deviation_points": int(self.trade_deviation_points_var.get()),
            "trade_pending_threshold_points": int(self.trade_pending_threshold_points_var.get()),
            "trade_magic": int(self.trade_magic_var.get()),
            "trade_comment_prefix": self.trade_comment_prefix_var.get(),
            "trade_pending_ttl_min": int(self.trade_pending_ttl_min_var.get()),
            "trade_min_rr_tp2": float(self.trade_min_rr_tp2_var.get()),
            "trade_min_dist_keylvl_pips": float(self.trade_min_dist_keylvl_pips_var.get()),
            "trade_cooldown_min": int(self.trade_cooldown_min_var.get()),
            "trade_dynamic_pending": bool(self.trade_dynamic_pending_var.get()),
            "auto_trade_dry_run": bool(self.auto_trade_dry_run_var.get()),
            "trade_move_to_be_after_tp1": bool(self.trade_move_to_be_after_tp1_var.get()),
            "trade_trailing_atr_mult": float(self.trade_trailing_atr_mult_var.get()),
            "trade_allow_session_asia": bool(self.trade_allow_session_asia_var.get()),
            "trade_allow_session_london": bool(self.trade_allow_session_london_var.get()),
            "trade_allow_session_ny": bool(self.trade_allow_session_ny_var.get()),
            "news_block_before_min": int(self.trade_news_block_before_min_var.get()),
            "news_block_after_min": int(self.trade_news_block_after_min_var.get()),
            "no_run_weekend_enabled": bool(self.no_run_weekend_enabled_var.get()),
            "no_run_killzone_enabled": bool(self.norun_killzone_var.get()),
        }

    def apply_config(self, config_data: dict):
        """
        Áp dụng các giá trị từ dictionary cấu hình lên các biến Tkinter của UI.
        """
        logger.debug("Bắt đầu áp dụng cấu hình lên UI.")
        self.prompt_file_path_var.set(config_data.get("prompt_file_path", ""))
        self.auto_load_prompt_txt_var.set(bool(config_data.get("auto_load_prompt_txt", True)))

        folder = config_data.get("folder_path", "")
        if folder and Path(folder).exists():
            self.folder_path.set(folder)
            self._load_files(folder)
            history_manager.refresh_history_list(self)
            history_manager.refresh_json_list(self)

        self.model_var.set(config_data.get("model", MODELS.DEFAULT_VISION))
        self.delete_after_var.set(bool(config_data.get("delete_after", True)))
        self.max_files_var.set(int(config_data.get("max_files", 0)))
        self.autorun_var.set(bool(config_data.get("autorun", False)))
        self.autorun_seconds_var.set(int(config_data.get("autorun_secs", 60)))

        self.remember_context_var.set(bool(config_data.get("remember_ctx", True)))
        self.context_n_reports_var.set(int(config_data.get("ctx_n_reports", 1)))
        self.context_limit_chars_var.set(int(config_data.get("ctx_limit_chars", 2000)))
        self.create_ctx_json_var.set(bool(config_data.get("create_ctx_json", True)))
        self.prefer_ctx_json_var.set(bool(config_data.get("prefer_ctx_json", True)))
        self.ctx_json_n_var.set(int(config_data.get("ctx_json_n", 5)))

        self.telegram_enabled_var.set(bool(config_data.get("telegram_enabled", False)))
        self.telegram_token_var.set(config_data.get("telegram_token", ""))
        self.telegram_chat_id_var.set(config_data.get("telegram_chat_id", ""))
        self.telegram_skip_verify_var.set(bool(config_data.get("telegram_skip_verify", False)))
        self.telegram_ca_path_var.set(config_data.get("telegram_ca_path", ""))

        self.mt5_enabled_var.set(bool(config_data.get("mt5_enabled", False)))
        self.mt5_term_path_var.set(config_data.get("mt5_term_path", ""))
        self.mt5_symbol_var.set(config_data.get("mt5_symbol", ""))
        self.mt5_n_M1.set(int(config_data.get("mt5_n_M1", 120)))
        self.mt5_n_M5.set(int(config_data.get("mt5_n_M5", 180)))
        self.mt5_n_M15.set(int(config_data.get("mt5_n_M15", 96)))
        self.mt5_n_H1.set(int(config_data.get("mt5_n_H1", 120)))

        self.no_trade_enabled_var.set(bool(config_data.get("no_trade_enabled", True)))
        self.nt_spread_factor_var.set(float(config_data.get("nt_spread_factor", 1.2)))
        self.nt_min_atr_m5_pips_var.set(float(config_data.get("nt_min_atr_m5_pips", 3.0)))
        self.nt_min_ticks_per_min_var.set(int(config_data.get("nt_min_ticks_per_min", 5)))

        self.upload_workers_var.set(int(config_data.get("upload_workers", 4)))
        self.cache_enabled_var.set(bool(config_data.get("cache_enabled", True)))
        self.optimize_lossless_var.set(bool(config_data.get("opt_lossless", False)))
        self.only_generate_if_changed_var.set(bool(config_data.get("only_generate_if_changed", False)))

        self.auto_trade_enabled_var.set(bool(config_data.get("auto_trade_enabled", False)))
        self.trade_strict_bias_var.set(bool(config_data.get("trade_strict_bias", True)))
        self.trade_size_mode_var.set(config_data.get("trade_size_mode", "lots"))
        self.trade_lots_total_var.set(float(config_data.get("trade_lots_total", 0.10)))
        self.trade_equity_risk_pct_var.set(float(config_data.get("trade_equity_risk_pct", 1.0)))
        self.trade_money_risk_var.set(float(config_data.get("trade_money_risk", 10.0)))
        self.trade_split_tp1_pct_var.set(int(config_data.get("trade_split_tp1_pct", 50)))
        self.trade_deviation_points_var.set(int(config_data.get("trade_deviation_points", 20)))
        self.trade_pending_threshold_points_var.set(int(config_data.get("trade_pending_threshold_points", 60)))
        self.trade_magic_var.set(int(config_data.get("trade_magic", 26092025)))
        self.trade_comment_prefix_var.set(config_data.get("trade_comment_prefix", "AI-ICT"))

        self.trade_pending_ttl_min_var.set(int(config_data.get("trade_pending_ttl_min", 90)))
        self.trade_min_rr_tp2_var.set(float(config_data.get("trade_min_rr_tp2", 2.0)))
        self.trade_min_dist_keylvl_pips_var.set(float(config_data.get("trade_min_dist_keylvl_pips", 5.0)))
        self.trade_cooldown_min_var.set(int(config_data.get("trade_cooldown_min", 10)))
        self.trade_dynamic_pending_var.set(bool(config_data.get("trade_dynamic_pending", True)))
        self.auto_trade_dry_run_var.set(bool(config_data.get("auto_trade_dry_run", False)))
        self.trade_move_to_be_after_tp1_var.set(bool(config_data.get("trade_move_to_be_after_tp1", True)))
        self.trade_trailing_atr_mult_var.set(float(config_data.get("trade_trailing_atr_mult", 0.5)))
        self.trade_allow_session_asia_var.set(bool(config_data.get("trade_allow_session_asia", True)))
        self.trade_allow_session_london_var.set(bool(config_data.get("trade_allow_session_london", True)))
        self.trade_allow_session_ny_var.set(bool(config_data.get("trade_allow_session_ny", True)))

        self.trade_news_block_before_min_var.set(int(config_data.get("news_block_before_min", 15)))
        self.trade_news_block_after_min_var.set(int(config_data.get("news_block_after_min", 15)))

        self.no_run_weekend_enabled_var.set(bool(config_data.get("no_run_weekend_enabled", True)))
        self.norun_killzone_var.set(bool(config_data.get("no_run_killzone_enabled", True)))
        logger.info("Đã áp dụng cấu hình lên UI thành công.")
        
    def _get_reports_dir(self, folder_override: str | None = None) -> Path:
        # Logic này không phụ thuộc vào AppUI, nhưng để nó ở đây cho tiện
        # vì nó liên quan đến folder_path.
        base_path = folder_override or self.folder_path.get()
        return workspace_config.get_reports_dir(base_path)

    def choose_folder(self):
        """Mở hộp thoại cho người dùng chọn thư mục chứa ảnh."""
        folder = filedialog.askdirectory(title="Chọn thư mục chứa ảnh")
        if not folder:
            return
        self.folder_path.set(folder)
        self._load_files(folder)
        history_manager.refresh_history_list(self)
        history_manager.refresh_json_list(self)

    def _load_files(self, folder: str):
        """Tải các file ảnh từ thư mục đã chọn."""
        self.results.clear()
        self.combined_report_text = ""
        if hasattr(self, "tree"):
            self.tree.delete(*self.tree.get_children())
        count = 0
        for p in sorted(Path(folder).rglob("*")):
            if p.is_file() and p.suffix.lower() in FILES.SUPPORTED_EXTS:
                self.results.append({"path": p, "name": p.name, "status": "Chưa xử lý", "text": ""})
                idx = len(self.results)
                if hasattr(self, "tree"):
                    self.tree.insert("", "end", iid=str(idx - 1), values=(idx, p.name, "Chưa xử lý"))
                count += 1
        ui_builder.ui_status(self, f"Đã nạp {count} ảnh.")
        ui_builder.ui_progress(self, 0)
        if hasattr(self, "detail_text"):
            ui_builder.ui_detail_replace(self, "Báo cáo sẽ hiển thị ở đây.")

    def start_analysis(self):
        """Bắt đầu phân tích."""
        if self.is_running:
            ui_builder.ui_message(self, "warning", "Đang chạy", "Một phân tích khác đang chạy.")
            return
        if not self.folder_path.get() or not Path(self.folder_path.get()).is_dir():
            ui_builder.ui_message(self, "error", "Lỗi", "Vui lòng chọn một thư mục hợp lệ.")
            return
        
        self.is_running = True
        self.stop_flag = False
        ui_builder.toggle_controls_state(self, "disabled")
        
        cfg = self._snapshot_config()
        
        # Tạo một instance của AnalysisWorker
        worker_instance = AnalysisWorker(app=self, cfg=cfg)
        
        # Chạy phương thức run của instance đó trong một luồng mới
        self.active_worker_thread = threading.Thread(
            target=worker_instance.run, daemon=True
        )
        self.active_worker_thread.start()

    def stop_analysis(self):
        """Dừng phân tích."""
        if not self.is_running:
            return
        self.stop_flag = True
        if self.active_executor:
            self.active_executor.shutdown(wait=False, cancel_futures=True)
        ui_builder.ui_status(self, "Đang dừng...")

    def _snapshot_config(self) -> "RunConfig":
        """
        Chụp lại toàn bộ trạng thái cấu hình hiện tại từ giao diện người dùng 
        và trả về một đối tượng RunConfig đã được nhóm lại.
        """
        return RunConfig(
            folder=FolderConfig(
                folder=self.folder_path.get(),
                delete_after=self.delete_after_var.get(),
                max_files=self.max_files_var.get(),
            ),
            upload=UploadConfig(
                upload_workers=self.upload_workers_var.get(),
                cache_enabled=self.cache_enabled_var.get(),
                optimize_lossless=self.optimize_lossless_var.get(),
                only_generate_if_changed=self.only_generate_if_changed_var.get(),
            ),
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
            ),
            mt5=MT5Config(
                enabled=self.mt5_enabled_var.get(),
                symbol=self.mt5_symbol_var.get(),
                n_M1=self.mt5_n_M1.get(),
                n_M5=self.mt5_n_M5.get(),
                n_M15=self.mt5_n_M15.get(),
                n_H1=self.mt5_n_H1.get(),
            ),
            no_trade=NoTradeConfig(
                enabled=self.no_trade_enabled_var.get(),
                spread_factor=self.nt_spread_factor_var.get(),
                min_atr_m5_pips=self.nt_min_atr_m5_pips_var.get(),
                min_ticks_per_min=self.nt_min_ticks_per_min_var.get(),
            ),
            auto_trade=AutoTradeConfig(
                enabled=self.auto_trade_enabled_var.get(),
                strict_bias=self.trade_strict_bias_var.get(),
                size_mode=self.trade_size_mode_var.get(),
                lots_total=self.trade_lots_total_var.get(),
                equity_risk_pct=self.trade_equity_risk_pct_var.get(),
                money_risk=self.trade_money_risk_var.get(),
                split_tp1_pct=self.trade_split_tp1_pct_var.get(),
                deviation_points=self.trade_deviation_points_var.get(),
                pending_threshold_points=self.trade_pending_threshold_points_var.get(),
                magic=self.trade_magic_var.get(),
                comment_prefix=self.trade_comment_prefix_var.get(),
                pending_ttl_min=self.trade_pending_ttl_min_var.get(),
                min_rr_tp2=self.trade_min_rr_tp2_var.get(),
                min_dist_keylvl_pips=self.trade_min_dist_keylvl_pips_var.get(),
                cooldown_min=self.trade_cooldown_min_var.get(),
                dynamic_pending=self.trade_dynamic_pending_var.get(),
                dry_run=self.auto_trade_dry_run_var.get(),
                move_to_be_after_tp1=self.trade_move_to_be_after_tp1_var.get(),
                trailing_atr_mult=self.trade_trailing_atr_mult_var.get(),
                allow_session_asia=self.trade_allow_session_asia_var.get(),
                allow_session_london=self.trade_allow_session_london_var.get(),
                allow_session_ny=self.trade_allow_session_ny_var.get(),
            ),
            news=NewsConfig(
                block_enabled=True, # This seems to be missing a variable in the UI, assuming True
                block_before_min=self.trade_news_block_before_min_var.get(),
                block_after_min=self.trade_news_block_after_min_var.get(),
                cache_ttl_sec=300, # This seems to be missing a variable in the UI, using default
            ),
            schedule=ScheduleConfig(
                no_run_weekend_enabled=self.no_run_weekend_enabled_var.get(),
                no_run_killzone_enabled=self.norun_killzone_var.get(),
            ),
        )

    def _schedule_mt5_connection_check(self):
        # Logic to schedule MT5 connection check
        pass
        
    # ... (other methods will be moved here and adapted) ...
