# -*- coding: utf-8 -*-
"""
ỨNG DỤNG: PHÂN TÍCH ẢNH HÀNG LOẠT VÀ GIAO DỊCH TỰ ĐỘNG
================================================================
Mục tiêu:
- Tự động nạp và phân tích ảnh từ một thư mục.
- Tích hợp dữ liệu từ MetaTrader 5 để làm giàu ngữ cảnh.
- Sử dụng Google Gemini để tạo báo cáo phân tích theo mẫu.
- Hỗ trợ các tính năng nâng cao: cache ảnh, gửi thông báo Telegram, và tự động giao dịch.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Thêm thư mục gốc của dự án vào sys.path để có thể import các module từ `src`
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

import json
import queue
import threading
import logging
from datetime import datetime
from typing import Optional

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from tkinter.scrolledtext import ScrolledText

# Kiểm tra và import các thư viện tùy chọn
try:
    import matplotlib
    HAS_MPL = True
except ImportError:
    HAS_MPL = False

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

try:
    import google.generativeai as genai
except ImportError:
    print("Lỗi: Cần cài đặt Google Gemini SDK. Chạy lệnh: pip install google-generativeai")
    sys.exit(1)

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None

# Import các module nội bộ của dự án
from src.config.constants import (
    DEFAULT_MODEL,
    APP_DIR,
    WORKSPACE_JSON,
    API_KEY_ENC,
    SUPPORTED_EXTS,
)
from src.utils.utils import (
    obfuscate_text,
    deobfuscate_text,
)
from src.config.config import RunConfig
from src.core import worker
from src.core.chart_tab import ChartTabTV
from src.utils import ui_utils
from src.utils import ui_builder
from src.services import news

class TradingToolApp:
    """
    Lớp chính điều khiển giao diện và luồng hoạt động của ứng dụng.
    """
    def __init__(self, root: tk.Tk):
        """
        Khởi tạo giao diện chính và các biến trạng thái của ứng dụng.
        """
        self.root = root
        self.root.title("TOOL GIAO DỊCH TỰ ĐỘNG")
        self.root.geometry("1180x780")
        self.root.minsize(1024, 660)

        # Khóa thread
        self._trade_log_lock = threading.Lock()
        self._proposed_trade_log_lock = threading.Lock()
        self._vector_db_lock = threading.Lock()
        self._ui_log_lock = threading.Lock()

        # Biến trạng thái
        self.folder_path = tk.StringVar(value="")
        api_init = ""
        if API_KEY_ENC.exists():
            api_init = deobfuscate_text(API_KEY_ENC.read_text(encoding="utf-8"))
        api_init = api_init or os.environ.get("GOOGLE_API_KEY", "")
        self.api_key_var = tk.StringVar(value=api_init)
        self.model_var = tk.StringVar(value=DEFAULT_MODEL)

        self.delete_after_var = tk.BooleanVar(value=True)
        self.max_files_var = tk.IntVar(value=0)
        self.status_var = tk.StringVar(value="Chưa chọn thư mục.")
        self.progress_var = tk.DoubleVar(value=0.0)

        self.autorun_var = tk.BooleanVar(value=False)
        self.autorun_seconds_var = tk.IntVar(value=60)
        self._autorun_job = None

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
        self._last_telegram_signature = None

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

        self.trade_pending_ttl_min_var      = tk.IntVar(value=90)
        self.trade_min_rr_tp2_var           = tk.DoubleVar(value=2.0)
        self.trade_min_dist_keylvl_pips_var = tk.DoubleVar(value=5.0)
        self.trade_cooldown_min_var         = tk.IntVar(value=10)
        self.trade_dynamic_pending_var      = tk.BooleanVar(value=True)
        self.auto_trade_dry_run_var         = tk.BooleanVar(value=False)
        self.trade_move_to_be_after_tp1_var = tk.BooleanVar(value=True)
        self.trade_trailing_atr_mult_var    = tk.DoubleVar(value=0.5)
        self.trade_allow_session_asia_var   = tk.BooleanVar(value=True)
        self.trade_allow_session_london_var = tk.BooleanVar(value=True)
        self.trade_allow_session_ny_var     = tk.BooleanVar(value=True)

        self.trade_news_block_before_min_var = tk.IntVar(value=15)
        self.trade_news_block_after_min_var  = tk.IntVar(value=15)

        self.ff_cache_events_local = []
        self.ff_cache_fetch_time   = 0.0

        self.norun_weekend_var = tk.BooleanVar(value=True)
        self.norun_killzone_var = tk.BooleanVar(value=True)

        self.last_no_trade_ok = None
        self.last_no_trade_reasons = []

        self._news_refresh_lock = threading.Lock()
        self._news_refresh_inflight = False

        self.is_running = False
        self.stop_flag = False
        self.results = []
        self.combined_report_text = ""
        self.ui_queue = queue.Queue()

        self.prompt_file_path_var = tk.StringVar(value="")
        self.auto_load_prompt_txt_var = tk.BooleanVar(value=True)

        # Add placeholder methods that are called by the UI builder
        self.export_markdown = lambda: None
        self._on_tree_select = lambda e: None
        self._open_history_selected = lambda: None
        self._delete_history_selected = lambda: None
        self._open_reports_folder = lambda: None
        self._preview_history_selected = lambda: None
        self._load_json_selected = lambda: None
        self._delete_json_selected = lambda: None
        self._open_json_folder = lambda: None
        self._preview_json_selected = lambda: None
        self._load_prompts_from_disk = lambda: None
        self._save_current_prompt_to_disk = lambda: None
        self._reformat_prompt_area = lambda: None
        self._toggle_autorun = lambda: None
        self._autorun_interval_changed = lambda: None
        self._telegram_test = lambda: None
        self._pick_ca_bundle = lambda: None
        self._pick_mt5_terminal = lambda: None
        self._mt5_guess_symbol = lambda: None
        self._mt5_connect = lambda: None
        self._mt5_snapshot_popup = lambda: None
        self._save_workspace = lambda: None
        self._load_workspace = lambda: None
        self._delete_workspace = lambda: None
        self._refresh_history_list = lambda: None
        self._refresh_json_list = lambda: None
        self._update_tree_row = lambda i, status: None


        ui_builder.build_ui(self)
        self._load_workspace()
        ui_utils._poll_ui_queue(self)

    def _refresh_news_cache(self, ttl: int = 300, *, async_fetch: bool = True, cfg: RunConfig | None = None) -> None:
        try:
            now_ts = time.time()
            last_ts = float(self.ff_cache_fetch_time or 0.0)
            if (now_ts - last_ts) <= max(0, int(ttl or 0)):
                return

            if async_fetch:
                with self._news_refresh_lock:
                    if self._news_refresh_inflight:
                        return
                    self._news_refresh_inflight = True

                def _do():
                    try:
                        _cfg = cfg or self._snapshot_config()
                        ev = news.fetch_high_impact_events_for_cfg(_cfg, timeout=20)
                        self.ff_cache_events_local = ev or []
                        self.ff_cache_fetch_time = time.time()
                    except Exception:
                        pass
                    finally:
                        with self._news_refresh_lock:
                            self._news_refresh_inflight = False

                threading.Thread(target=_do, daemon=True).start()
                return

            acquired = False
            try:
                self._news_refresh_lock.acquire()
                acquired = True
                if self._news_refresh_inflight:
                    return
                self._news_refresh_inflight = True
            finally:
                if acquired:
                    self._news_refresh_lock.release()

            try:
                _cfg = cfg or self._snapshot_config()
                ev = news.fetch_high_impact_events_for_cfg(_cfg, timeout=20)
                self.ff_cache_events_local = ev or []
                self.ff_cache_fetch_time = time.time()
            except Exception:
                pass
            finally:
                with self._news_refresh_lock:
                    self._news_refresh_inflight = False
        except Exception:
            pass

    def _toggle_api_visibility(self):
        ui_builder.toggle_api_visibility(self)

    def _snapshot_config(self) -> RunConfig:
        return RunConfig(
            folder=self.folder_path.get().strip(),
            delete_after=bool(self.delete_after_var.get()),
            max_files=int(self.max_files_var.get()),
            upload_workers=int(self.upload_workers_var.get()),
            cache_enabled=bool(self.cache_enabled_var.get()),
            optimize_lossless=bool(self.optimize_lossless_var.get()),
            only_generate_if_changed=bool(self.only_generate_if_changed_var.get()),
            ctx_limit=int(self.context_limit_chars_var.get()),
            create_ctx_json=bool(self.create_ctx_json_var.get()),
            prefer_ctx_json=bool(self.prefer_ctx_json_var.get()),
            ctx_json_n=int(self.ctx_json_n_var.get()),
            telegram_enabled=bool(self.telegram_enabled_var.get()),
            telegram_token=self.telegram_token_var.get().strip(),
            telegram_chat_id=self.telegram_chat_id_var.get().strip(),
            telegram_skip_verify=bool(self.telegram_skip_verify_var.get()),
            telegram_ca_path=self.telegram_ca_path_var.get().strip(),
            mt5_enabled=bool(self.mt5_enabled_var.get()),
            mt5_symbol=self.mt5_symbol_var.get().strip(),
            mt5_n_M1=int(self.mt5_n_M1.get()),
            mt5_n_M5=int(self.mt5_n_M5.get()),
            mt5_n_M15=int(self.mt5_n_M15.get()),
            mt5_n_H1=int(self.mt5_n_H1.get()),
            nt_enabled=bool(self.no_trade_enabled_var.get()),
            nt_spread_factor=float(self.nt_spread_factor_var.get()),
            nt_min_atr_m5_pips=float(self.nt_min_atr_m5_pips_var.get()),
            nt_min_ticks_per_min=int(self.nt_min_ticks_per_min_var.get()),
            auto_trade_enabled=bool(self.auto_trade_enabled_var.get()),
            trade_strict_bias=bool(self.trade_strict_bias_var.get()),
            trade_size_mode=self.trade_size_mode_var.get(),
            trade_lots_total=float(self.trade_lots_total_var.get()),
            trade_equity_risk_pct=float(self.trade_equity_risk_pct_var.get()),
            trade_money_risk=float(self.trade_money_risk_var.get()),
            trade_split_tp1_pct=int(self.trade_split_tp1_pct_var.get()),
            trade_deviation_points=int(self.trade_deviation_points_var.get()),
            trade_pending_threshold_points=int(self.trade_pending_threshold_points_var.get()),
            trade_magic=int(self.trade_magic_var.get()),
            trade_comment_prefix=self.trade_comment_prefix_var.get(),
            trade_pending_ttl_min=int(self.trade_pending_ttl_min_var.get()),
            trade_min_rr_tp2=float(self.trade_min_rr_tp2_var.get()),
            trade_min_dist_keylvl_pips=float(self.trade_min_dist_keylvl_pips_var.get()),
            trade_cooldown_min=int(self.trade_cooldown_min_var.get()),
            trade_dynamic_pending=bool(self.trade_dynamic_pending_var.get()),
            auto_trade_dry_run=bool(self.auto_trade_dry_run_var.get()),
            trade_move_to_be_after_tp1=bool(self.trade_move_to_be_after_tp1_var.get()),
            trade_trailing_atr_mult=float(self.trade_trailing_atr_mult_var.get()),
            trade_allow_session_asia=bool(self.trade_allow_session_asia_var.get()),
            trade_allow_session_london=bool(self.trade_allow_session_london_var.get()),
            trade_allow_session_ny=bool(self.trade_allow_session_ny_var.get()),
            trade_news_block_before_min=int(self.trade_news_block_before_min_var.get()),
            trade_news_block_after_min=int(self.trade_news_block_after_min_var.get()),
            trade_news_block_enabled=True,
            news_cache_ttl_sec=300,
        )

    def _load_env(self):
        path = filedialog.askopenfilename(title="Chọn file .env", filetypes=[("ENV", ".env"), ("Tất cả", "*.*")])
        if not path:
            return
        if load_dotenv is None:
            try:
                for line in Path(path).read_text(encoding="utf-8").splitlines():
                    if "=" in line:
                        k, v = line.split("=", 1)
                        if k.strip() == "GOOGLE_API_KEY":
                            self.api_key_var.set(v.strip())
                            break
                ui_utils.ui_message(self, "info", "ENV", "Đã nạp GOOGLE_API_KEY từ file.")
            except Exception as e:
                ui_utils.ui_message(self, "error", "ENV", str(e))
        else:
            load_dotenv(path)
            val = os.environ.get("GOOGLE_API_KEY", "")
            if val:
                self.api_key_var.set(val)
                ui_utils.ui_message(self, "info", "ENV", "Đã nạp GOOGLE_API_KEY từ .env")

    def _save_api_safe(self):
        try:
            API_KEY_ENC.write_text(obfuscate_text(self.api_key_var.get().strip()), encoding="utf-8")
            ui_utils.ui_message(self, "info", "API", f"Đã lưu an toàn vào: {API_KEY_ENC}")
        except Exception as e:
            ui_utils.ui_message(self, "error", "API", str(e))

    def _delete_api_safe(self):
        try:
            if API_KEY_ENC.exists():
                API_KEY_ENC.unlink()
            ui_utils.ui_message(self, "info", "API", "Đã xoá API key đã lưu.")
        except Exception as e:
            ui_utils.ui_message(self, "error", "API", str(e))

    def _get_reports_dir(self, folder_override: str | None = None) -> Path:
        folder = Path(folder_override) if folder_override else (Path(self.folder_path.get().strip()) if self.folder_path.get().strip() else None)
        if not folder:
            return None
        d = folder / "Reports"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def choose_folder(self):
        folder = filedialog.askdirectory(title="Chọn thư mục chứa ảnh")
        if not folder:
            return
        self.folder_path.set(folder)
        self._load_files(folder)
        self._refresh_history_list()
        self._refresh_json_list()

    def _load_files(self, folder):
        self.results.clear()
        self.combined_report_text = ""
        if hasattr(self, "tree"):
            self.tree.delete(*self.tree.get_children())
        count = 0
        for p in sorted(Path(folder).rglob("*")):
            if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS:
                self.results.append({"path": str(p), "name": p.name, "status": "Chưa xử lý", "text": ""})
                idx = len(self.results)
                if hasattr(self, "tree"):
                    self.tree.insert("", "end", iid=str(idx - 1), values=(idx, p.name, "Chưa xử lý"))
                count += 1
        ui_utils.ui_status(self,
            f"Đã nạp {count} ảnh. Sẵn sàng phân tích 1 lần."
            if count
            else "Không tìm thấy ảnh phù hợp trong thư mục đã chọn."
        )
        ui_utils.ui_progress(self, 0)
        if hasattr(self, "export_btn"):
            self.export_btn.configure(state="disabled")
        if hasattr(self, "detail_text"):
            ui_utils.ui_detail_replace(self, "Báo cáo tổng hợp sẽ hiển thị tại đây sau khi phân tích.")

    def start_analysis(self):
        if self.is_running:
            return
        folder = self.folder_path.get().strip()
        if not folder:
            ui_utils.ui_message(self, "warning", "Thiếu thư mục", "Vui lòng chọn thư mục ảnh trước.")
            return

        if self.cache_enabled_var.get() and self.delete_after_var.get():
            ui_utils.ui_status(self, "Lưu ý: Cache ảnh đang bật, KHÔNG nên xoá file trên Gemini sau phân tích.")

        self.clear_results()
        ui_utils.ui_status(self, "Đang nạp lại ảnh từ thư mục đã chọn...")
        self._load_files(folder)
        if len(self.results) == 0:
            return

        prompt_no_entry = self.prompt_no_entry_text.get("1.0", "end").strip()
        prompt_entry_run = self.prompt_entry_run_text.get("1.0", "end").strip()

        if not prompt_no_entry or not prompt_entry_run:
            ui_utils.ui_message(self, "warning", "Thiếu prompt", "Vui lòng nhập nội dung cho cả hai tab prompt trước khi chạy.")
            return
        
        cfg = self._snapshot_config()

        api_key = self.api_key_var.get().strip() or os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            ui_utils.ui_message(self, "warning", "Thiếu API key", "Vui lòng nhập API key hoặc đặt biến môi trường GOOGLE_API_KEY.")
            return
        try:
            genai.configure(api_key=api_key)
        except Exception as e:
            ui_utils.ui_message(self, "error", "Gemini", f"Lỗi cấu hình API: {e}")
            return

        for i, r in enumerate(self.results):
            r["status"] = "Chưa xử lý"
            r["text"] = ""
            self._update_tree_row(i, r["status"])
        self.combined_report_text = ""
        ui_utils.ui_progress(self, 0)
        ui_utils.ui_detail_replace(self, "Đang chuẩn bị phân tích...")

        self.stop_flag = False
        self.is_running = True
        self.stop_btn.configure(state="normal")
        self.export_btn.configure(state="disabled")

        t = threading.Thread(
            target=worker.run_analysis_worker,
            args=(
                self,
                prompt_no_entry,
                prompt_entry_run,
                self.model_var.get(),
                cfg
            ),
            daemon=True
        )
        t.start()

    def stop_analysis(self):
        if self.is_running:
            self.stop_flag = True
            ui_utils.ui_status(self, "Đang dừng sau khi hoàn tất tác vụ hiện tại...")

    def clear_results(self):
        self.results.clear()
        self.combined_report_text = ""
        if hasattr(self, "tree"):
            self.tree.delete(*self.tree.get_children())
        if hasattr(self, "detail_text"):
            ui_utils.ui_detail_replace(self, "Báo cáo tổng hợp sẽ hiển thị tại đây sau khi phân tích.")
        ui_utils.ui_progress(self, 0)
        ui_utils.ui_status(self, "Đã xoá kết quả khỏi giao diện.")

def main():
    """
    Hàm chính để khởi tạo và chạy ứng dụng.
    """
    log_file_path = APP_DIR / "app_debug.log"
    try:
        logging.basicConfig(
            level=logging.DEBUG,
            format='%(asctime)s - %(levelname)s - %(name)s - %(message)s',
            filename=str(log_file_path),
            filemode='w',
        )
        logging.info("Application starting up.")

        root = tk.Tk()
        app = TradingToolApp(root)
        root.mainloop()
    except Exception:
        logging.exception("An unhandled exception occurred in main.")
        raise

if __name__ == "__main__":
    main()
