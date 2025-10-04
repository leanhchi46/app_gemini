from __future__ import annotations

import json
import logging
import os
import queue
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import TYPE_CHECKING, Optional

import google.generativeai as genai
from dotenv import load_dotenv

from APP.configs import workspace_config
from APP.configs.app_config import RunConfig
from APP.configs.constants import DEFAULT_MODEL, SUPPORTED_EXTS
from APP.core import analysis_worker
from APP.services import mt5_service, telegram_service, news_service
from APP.analysis import report_parser, image_processor
from APP.ui.components import history_manager, prompt_manager
from APP.ui.utils import timeframe_detector, ui_builder
from APP.utils import general_utils

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from APP.utils.safe_data import SafeMT5Data


class AppUI(tk.Frame):
    def __init__(self, root: tk.Tk):
        super().__init__(root)
        self.root = root
        self.root.title("TOOL GIAO DỊCH TỰ ĐỘNG")
        self.root.geometry("1180x780")
        
        self.ui_queue = queue.Queue()
        self._init_tk_variables()

        self.ff_cache_events_local: list = []
        self.ff_cache_fetch_time: float = 0.0
        self._news_refresh_lock = threading.Lock()
        self._news_refresh_inflight = False

        self.is_running = False
        self.stop_flag = False
        self.results: list[dict] = []
        self.combined_report_text = ""

        self.active_worker_thread: Optional[threading.Thread] = None
        self.active_executor = None
        
        self._autorun_job: Optional[str] = None
        self._mt5_reconnect_job: Optional[str] = None
        self._mt5_check_connection_job: Optional[str] = None
        self._mt5_reconnect_attempts = 0
        self._mt5_max_reconnect_attempts = 5
        self._mt5_reconnect_delay_sec = 5

        ui_builder.build_ui(self)
        self._configure_gemini_api()
        self._load_workspace()
        self._poll_ui_queue()
        self._schedule_mt5_connection_check()

        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)

    def _init_tk_variables(self):
        # This method combines all tk variable initializations
        self.folder_path = tk.StringVar(value="")
        self.api_key_var = tk.StringVar(value=os.environ.get("GOOGLE_API_KEY", ""))
        self.model_var = tk.StringVar(value=DEFAULT_MODEL)
        self.api_key_var.trace_add("write", lambda *args: self._configure_gemini_api())
        # ... (all other tk.StringVar, tk.BooleanVar, etc. from TradingToolApp)
        self.delete_after_var = tk.BooleanVar(value=True)
        self.max_files_var = tk.IntVar(value=0)
        self.status_var = tk.StringVar(value="Chưa chọn thư mục.")
        self.progress_var = tk.DoubleVar(value=0.0)
        self.autorun_var = tk.BooleanVar(value=False)
        self.autorun_seconds_var = tk.IntVar(value=60)
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

    # ... (All methods from AppLogic and TradingToolApp will be merged here) ...
    # For example, start_analysis from AppLogic becomes a method of AppUI
    def start_analysis(self):
        if self.is_running:
            return
        # ... (logic from AppLogic.start_analysis, replacing `app` with `self`)
        folder = self.folder_path.get().strip()
        if not folder:
            messagebox.showwarning("Thiếu thư mục", "Vui lòng chọn thư mục ảnh trước.")
            return

        self.clear_results()
        self._load_files(folder)
        if not self.results:
            return

        prompt_no_entry = self.prompt_no_entry_text.get("1.0", "end").strip()
        prompt_entry_run = self.prompt_entry_run_text.get("1.0", "end").strip()
        if not prompt_no_entry or not prompt_entry_run:
            messagebox.showwarning("Thiếu prompt", "Vui lòng nhập nội dung cho cả hai tab prompt.")
            return

        cfg = self._snapshot_config()
        
        self.stop_flag = False
        self.is_running = True
        self.stop_btn.configure(state="normal")

        self.active_worker_thread = threading.Thread(
            target=analysis_worker.run_analysis_worker,
            args=(self, prompt_no_entry, prompt_entry_run, self.model_var.get(), cfg),
            daemon=True,
        )
        self.active_worker_thread.start()

    # ... (and so on for all other methods)
    def _on_closing(self):
        if self._mt5_reconnect_job: self.root.after_cancel(self._mt5_reconnect_job)
        if self._mt5_check_connection_job: self.root.after_cancel(self._mt5_check_connection_job)
        self._save_workspace()
        self.root.destroy()

    def _poll_ui_queue(self):
        try:
            while True:
                callback = self.ui_queue.get_nowait()
                callback()
        except queue.Empty:
            pass
        self.root.after(100, self._poll_ui_queue)
        
    # ... (The rest of the methods from both classes, refactored)
    def _configure_gemini_api(self):
        api_key = self.api_key_var.get().strip()
        if not api_key:
            self.status_var.set("Thiếu API key để cấu hình Gemini.")
            return
        
        def _task():
            try:
                genai.configure(api_key=api_key)
                self.ui_queue.put(lambda: self.status_var.set("Đã cấu hình Gemini API."))
                self._update_model_list_in_ui()
            except Exception as e:
                self.ui_queue.put(lambda: self.status_var.set(f"Lỗi cấu hình Gemini: {e}"))
        
        threading.Thread(target=_task, daemon=True).start()

    def _update_model_list_in_ui(self):
        def _task():
            try:
                models = [m.name for m in genai.list_models() if "generateContent" in m.supported_generation_methods]
                if models:
                    self.ui_queue.put(lambda: self.model_combo.configure(values=models))
            except Exception as e:
                logger.error(f"Lỗi khi cập nhật danh sách model: {e}")
        threading.Thread(target=_task, daemon=True).start()
        
    def _load_workspace(self):
        # This will now use functions from workspace_config and populate self's variables
        pass # Placeholder for brevity

    def _save_workspace(self):
        # This will gather all self's variables and save them using workspace_config
        pass # Placeholder for brevity

    def clear_results(self):
        self.results.clear()
        self.combined_report_text = ""
        if hasattr(self, "tree"):
            self.tree.delete(*self.tree.get_children())
        if hasattr(self, "detail_text"):
            self.detail_text.delete("1.0", "end")
            self.detail_text.insert("1.0", "Báo cáo tổng hợp sẽ hiển thị tại đây.")
        self.progress_var.set(0)
        self.status_var.set("Đã xoá kết quả.")

    def _load_files(self, folder):
        self.results.clear()
        if hasattr(self, "tree"): self.tree.delete(*self.tree.get_children())
        count = 0
        for p in sorted(Path(folder).rglob("*")):
            if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS:
                self.results.append({"path": p, "name": p.name, "status": "Chưa xử lý"})
                if hasattr(self, "tree"):
                    self.tree.insert("", "end", iid=str(count), values=(count + 1, p.name, "Chưa xử lý"))
                count += 1
        self.status_var.set(f"Đã nạp {count} ảnh.")

    def get_reports_dir(self, folder_override: str | None = None) -> Path:
        base_folder = Path(folder_override or self.folder_path.get())
        reports_dir = base_folder / "Reports"
        reports_dir.mkdir(exist_ok=True)
        return reports_dir

    def images_tf_map(self, names: list[str]) -> dict[str, str]:
        return {name: timeframe_detector.detect_from_name(name) for name in names}
        
    # ... and many other methods ...
