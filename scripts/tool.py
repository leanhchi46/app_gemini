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
import subprocess
from pathlib import Path

# Thêm thư mục gốc của dự án vào sys.path để có thể import các module từ `src`
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

import json
import queue
import re
import threading
import time
import logging
from datetime import datetime
from typing import Optional
import ast
from tkinter.scrolledtext import ScrolledText
from src.utils import report_parser
from src.core import auto_trade
from src.utils import mt5_utils

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
from src.utils.safe_data import SafeMT5Data
from src.config.config import RunConfig
from src.core import worker
from src.core.chart_tab import ChartTabTV
from src.utils import ui_utils
from src.utils import ui_builder
from src.services import news, telegram_client
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

        # Khóa thread để đảm bảo an toàn khi truy cập tài nguyên dùng chung từ nhiều luồng
        self._trade_log_lock = threading.Lock()
        self._proposed_trade_log_lock = threading.Lock()
        self._vector_db_lock = threading.Lock()
        self._ui_log_lock = threading.Lock()

        self._init_tk_variables()

        self.ff_cache_events_local = []
        self.ff_cache_fetch_time   = 0.0

        self.last_no_trade_ok = None
        self.last_no_trade_reasons = []

        self._news_refresh_lock = threading.Lock()
        self._news_refresh_inflight = False

        self.is_running = False
        self.stop_flag = False
        self.results = []
        self.combined_report_text = ""
        self.ui_queue = queue.Queue()

        # Thêm các thuộc tính để theo dõi luồng worker và executor
        self.active_worker_thread = None
        self.active_executor = None

        # Thêm lại các phương thức giữ chỗ bị thiếu để tránh lỗi AttributeError
        self._telegram_test = lambda: ui_utils.ui_message(self, "info", "Telegram", "Chức năng này chưa được cài đặt.")
        self._pick_ca_bundle = lambda: ui_utils.ui_message(self, "info", "Telegram", "Chức năng này chưa được cài đặt.")

        # Gọi hàm từ ui_builder để xây dựng toàn bộ giao diện người dùng
        ui_builder.build_ui(self)
        # Tải lại các cài đặt từ lần làm việc trước (nếu có)
        self._load_workspace()
        # Bắt đầu vòng lặp kiểm tra hàng đợi UI để xử lý các cập nhật từ luồng phụ
        ui_utils._poll_ui_queue(self)

    def _init_tk_variables(self):
        """Khởi tạo tất cả các biến trạng thái của Tkinter."""
        # Các biến trạng thái, được liên kết với các widget trong giao diện người dùng
        self.folder_path = tk.StringVar(value="")
        # Ưu tiên nạp API key đã được mã hóa, nếu không có thì tìm trong biến môi trường
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

        self.norun_weekend_var = tk.BooleanVar(value=True)
        self.norun_killzone_var = tk.BooleanVar(value=True)

        self.prompt_file_path_var = tk.StringVar(value="")
        self.auto_load_prompt_txt_var = tk.BooleanVar(value=True)

    def _refresh_news_cache(self, ttl: int = 300, *, async_fetch: bool = True, cfg: RunConfig | None = None) -> None:
        # Làm mới bộ đệm tin tức từ Forex Factory nếu dữ liệu đã cũ (quá thời gian `ttl`)
        try:
            now_ts = time.time()
            last_ts = float(self.ff_cache_fetch_time or 0.0)
            if (now_ts - last_ts) <= max(0, int(ttl or 0)):
                return

            # Tạo snapshot config ở luồng chính để đảm bảo an toàn thread
            final_cfg = cfg or self._snapshot_config()

            if async_fetch:
                with self._news_refresh_lock:
                    if self._news_refresh_inflight:
                        return
                    self._news_refresh_inflight = True

                def _do_async(config: RunConfig):
                    try:
                        ev = news.fetch_high_impact_events_for_cfg(config, timeout=20)
                        self.ff_cache_events_local = ev or []
                        self.ff_cache_fetch_time = time.time()
                    except Exception as e:
                        logging.warning(f"Lỗi khi làm mới tin tức (async): {e}")
                    finally:
                        with self._news_refresh_lock:
                            self._news_refresh_inflight = False

                threading.Thread(target=_do_async, args=(final_cfg,), daemon=True).start()
                return

            # Logic chạy đồng bộ (synchronous)
            if not self._news_refresh_lock.acquire(blocking=False):
                return

            try:
                self._news_refresh_inflight = True
                ev = news.fetch_high_impact_events_for_cfg(final_cfg, timeout=20)
                self.ff_cache_events_local = ev or []
                self.ff_cache_fetch_time = time.time()
            except Exception as e:
                logging.warning(f"Lỗi khi làm mới tin tức (sync): {e}")
            finally:
                self._news_refresh_inflight = False
                self._news_refresh_lock.release()
        except Exception as e:
            logging.error(f"Lỗi không mong muốn trong _refresh_news_cache: {e}")

    def _toggle_api_visibility(self):
        # Chuyển đổi trạng thái hiển thị (ẩn/hiện) của ô nhập API key
        # Logic được chuyển trực tiếp vào đây sau khi tái cấu trúc ui_builder
        self.api_entry.configure(show="" if self.api_entry.cget("show") == "*" else "*")

    def _log_trade_decision(self, data: dict, folder_override: str | None = None):
        """Ghi lại các quyết định hoặc sự kiện quan trọng vào file log JSONL."""
        try:
            d = self._get_reports_dir(folder_override=folder_override)
            if not d:
                return
            
            log_file = d / f"trade_log_{datetime.now().strftime('%Y%m%d')}.jsonl"
            line = json.dumps(data, ensure_ascii=False)
            
            # Sử dụng lock để đảm bảo ghi file an toàn từ nhiều luồng
            with self._trade_log_lock:
                with open(log_file, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
        except Exception as e:
            logging.error(f"Lỗi khi ghi trade log: {e}")

    def _quick_be_trailing_sweep(self, cfg: RunConfig):
        """Chạy nhanh việc quản lý BE/Trailing cho các lệnh đang mở."""
        if not (self.mt5_enabled_var.get() and self.auto_trade_enabled_var.get()):
            return
        
        def _sweep(c):
            try:
                # Xây dựng ngữ cảnh MT5 để lấy dữ liệu mới nhất
                safe_data = self._mt5_build_context(plan=None, cfg=c)
                if safe_data and safe_data.raw:
                    auto_trade.mt5_manage_be_trailing(self, safe_data.raw, c)
            except Exception as e:
                logging.warning(f"Lỗi trong _quick_be_trailing_sweep: {e}")

        # Chạy trong một luồng riêng để không chặn worker
        threading.Thread(target=_sweep, args=(cfg,), daemon=True).start()

    def _maybe_notify_telegram(self, report_text: str, report_path: Path | None, cfg: RunConfig):
        """Gửi thông báo qua Telegram nếu được bật và có kết quả xác suất cao."""
        if not cfg.telegram_enabled or not report_text:
            return
        
        # Chỉ gửi nếu có tín hiệu "HIGH PROBABILITY" trong báo cáo
        if "HIGH PROBABILITY" not in report_text.upper():
            return

        # Tạo một "chữ ký" cho báo cáo để tránh gửi trùng lặp
        signature = report_parser.create_report_signature(report_text)
        if signature == self._last_telegram_signature:
            return
        self._last_telegram_signature = signature

        # Gửi thông báo trong một luồng riêng biệt
        threading.Thread(
            target=telegram_client.send_telegram_message,
            args=(report_text, report_path, cfg),
            daemon=True
        ).start()

    def _snapshot_config(self) -> RunConfig:
        # Chụp lại toàn bộ trạng thái cấu hình hiện tại từ giao diện người dùng.
        # Điều này đảm bảo rằng luồng worker chạy với một cấu hình nhất quán,
        # ngay cả khi người dùng thay đổi cài đặt trên giao diện trong lúc đang chạy.
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
        # Mở hộp thoại để người dùng chọn tệp .env và tải biến môi trường từ đó
        path = filedialog.askopenfilename(title="Chọn file .env", filetypes=[("ENV", ".env"), ("Tất cả", "*.*")])
        if not path:
            return
        # Nếu thư viện python-dotenv không được cài đặt, đọc tệp theo cách thủ công
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
        # Nếu có python-dotenv, sử dụng nó để tải tất cả các biến
        else:
            load_dotenv(path)
            val = os.environ.get("GOOGLE_API_KEY", "")
            if val:
                self.api_key_var.set(val)
                ui_utils.ui_message(self, "info", "ENV", "Đã nạp GOOGLE_API_KEY từ .env")

    def _save_api_safe(self):
        # Mã hóa và lưu API key vào tệp để sử dụng trong các lần chạy sau
        try:
            API_KEY_ENC.write_text(obfuscate_text(self.api_key_var.get().strip()), encoding="utf-8")
            ui_utils.ui_message(self, "info", "API", f"Đã lưu an toàn vào: {API_KEY_ENC}")
        except Exception as e:
            ui_utils.ui_message(self, "error", "API", str(e))

    def _delete_api_safe(self):
        # Xóa tệp chứa API key đã mã hóa
        try:
            if API_KEY_ENC.exists():
                API_KEY_ENC.unlink()
            ui_utils.ui_message(self, "info", "API", "Đã xoá API key đã lưu.")
        except Exception as e:
            ui_utils.ui_message(self, "error", "API", str(e))

    def _get_reports_dir(self, folder_override: str | None = None) -> Path:
        # Lấy đường dẫn đến thư mục "Reports" bên trong thư mục ảnh, tạo nó nếu chưa tồn tại
        folder = Path(folder_override) if folder_override else (Path(self.folder_path.get().strip()) if self.folder_path.get().strip() else None)
        if not folder:
            return None
        d = folder / "Reports"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def choose_folder(self):
        # Mở hộp thoại cho người dùng chọn thư mục và sau đó tải danh sách tệp
        folder = filedialog.askdirectory(title="Chọn thư mục chứa ảnh")
        if not folder:
            return
        self.folder_path.set(folder)
        self._load_files(folder)
        self._refresh_history_list()
        self._refresh_json_list()

    def _load_files(self, folder):
        # Xóa kết quả cũ và quét thư mục được chọn để tìm các tệp ảnh hợp lệ
        self.results.clear()
        self.combined_report_text = ""
        if hasattr(self, "tree"):
            self.tree.delete(*self.tree.get_children())
        count = 0
        # Lặp qua tất cả các tệp trong thư mục và các thư mục con
        for p in sorted(Path(folder).rglob("*")):
            # Chỉ xử lý các tệp có phần mở rộng được hỗ trợ
            if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS:
                self.results.append({"path": p, "name": p.name, "status": "Chưa xử lý", "text": ""})
                idx = len(self.results)
                # Thêm tệp vào cây hiển thị trên giao diện
                if hasattr(self, "tree"):
                    self.tree.insert("", "end", iid=str(idx - 1), values=(idx, p.name, "Chưa xử lý"))
                count += 1
        ui_utils.ui_status(self,
            f"Đã nạp {count} ảnh. Sẵn sàng phân tích 1 lần."
            if count
            else "Không tìm thấy ảnh phù hợp trong thư mục đã chọn."
        )
        ui_utils.ui_progress(self, 0)
        if hasattr(self, "detail_text"):
            ui_utils.ui_detail_replace(self, "Báo cáo tổng hợp sẽ hiển thị tại đây sau khi phân tích.")

    def start_analysis(self):
        # Bắt đầu một phiên phân tích mới
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
            # Cấu hình API key cho thư viện Gemini
            genai.configure(api_key=api_key)
        except Exception as e:
            ui_utils.ui_message(self, "error", "Gemini", f"Lỗi cấu hình API: {e}")
            return

        # Đặt lại trạng thái của các kết quả trước khi bắt đầu
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

        # Chạy logic phân tích chính trong một luồng riêng biệt
        # và lưu lại tham chiếu đến luồng này
        self.active_worker_thread = threading.Thread(
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
        self.active_worker_thread.start()

    def stop_analysis(self):
        """
        Gửi tín hiệu dừng cho luồng worker và hủy các tác vụ upload đang chờ.
        """
        if not self.is_running:
            return

        self.stop_flag = True
        ui_utils.ui_status(self, "Đang gửi yêu cầu dừng...")

        # Hủy các tác vụ upload đang chờ trong executor
        if self.active_executor:
            try:
                # Hủy tất cả các future chưa bắt đầu chạy.
                # wait=False để không chặn luồng UI.
                self.active_executor.shutdown(wait=False, cancel_futures=True)
                ui_utils.ui_status(self, "Đã yêu cầu hủy các tác vụ upload đang chờ.")
            except Exception as e:
                logging.warning(f"Lỗi khi shutdown executor: {e}")
        else:
            ui_utils.ui_status(self, "Đang dừng... (Không có tác vụ upload nào đang hoạt động)")

    def _find_balanced_json_after(self, text: str, start_idx: int):
        return report_parser.find_balanced_json_after(text, start_idx)

    def _extract_json_block_prefer(self, text: str):
        return report_parser.extract_json_block_prefer(text)

    def _coerce_setup_from_json(self, obj):
        return report_parser.coerce_setup_from_json(obj)

    def _parse_float(self, s: str):
        return report_parser.parse_float(s)

    def _parse_direction_from_line1(self, line1: str):
        return report_parser.parse_direction_from_line1(line1)

    def _maybe_delete(self, uploaded_file):
        try:
            genai.delete_file(uploaded_file.name)
        except Exception:
            pass

    def _update_progress(self, done_steps, total_steps):
        pct = (done_steps / max(total_steps, 1)) * 100.0
        ui_utils._enqueue(self, lambda: (self.progress_var.set(pct), self.status_var.set(f"Tiến độ: {pct:.1f}%")))

    def _update_tree_row(self, idx, status):
        def action():
            iid = str(idx)
            if self.tree.exists(iid):
                vals = list(self.tree.item(iid, "values"))
                vals = [idx + 1, self.results[idx]["name"], status] if len(vals) < 3 else [vals[0], vals[1], status]
                self.tree.item(iid, values=vals)
        ui_utils._enqueue(self, action)

    def _finalize_done(self):
        try:
            self._log_trade_decision({
                "stage": "run-end",
                "t": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }, folder_override=(self.mt5_symbol_var.get().strip() or None))
        except Exception:
            pass

        self.is_running = False
        self.stop_flag = False
        self.active_worker_thread = None
        self.active_executor = None
        self.stop_btn.configure(state="disabled")
        ui_utils.ui_status(self, "Đã hoàn tất phân tích toàn bộ thư mục.")
        self._schedule_next_autorun()

    def _finalize_stopped(self):
        self.is_running = False
        self.stop_flag = False
        self.active_worker_thread = None
        self.active_executor = None
        self.stop_btn.configure(state="disabled")
        ui_utils.ui_status(self, "Đã dừng.")
        self._schedule_next_autorun()

    def _on_tree_select(self, _evt):
        self.detail_text.delete("1.0", "end")
        if self.combined_report_text.strip():
            self.detail_text.insert("1.0", self.combined_report_text)
        else:
            self.detail_text.insert("1.0", "Chưa có báo cáo. Hãy bấm 'Bắt đầu'.")

    def export_markdown(self):
        report_text = self.combined_report_text or ""
        folder = self.folder_path.get()
        files = [r["name"] for r in self.results if r.get("path")]
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        md = [
            f"# Báo cáo phân tích toàn bộ thư mục",
            f"- Thời gian: {ts}",
            f"- Model: {self.model_var.get()}",
            f"- Thư mục: {folder}",
            f"- Số ảnh: {len(files)}",
            "",
            "## Danh sách ảnh",
        ]
        md += [f"- {name}" for name in files]
        md += ["", "## Kết quả phân tích tổng hợp", report_text or "_(trống)_"]
        out_path = filedialog.asksaveasfilename(
            title="Lưu báo cáo Markdown",
            defaultextension=".md",
            filetypes=[("Markdown", "*.md")],
            initialfile="bao_cao_gemini_folder.md",
        )
        if not out_path:
            return
        try:
            Path(out_path).write_text("\n".join(md), encoding="utf-8")
            ui_utils.ui_message(self, "info", "Thành công", f"Đã lưu: {out_path}")
        except Exception as e:
            ui_utils.ui_message(self, "error", "Lỗi ghi file", str(e))

    def clear_results(self):
        self.results.clear()
        self.combined_report_text = ""
        if hasattr(self, "tree"):
            self.tree.delete(*self.tree.get_children())
        if hasattr(self, "detail_text"):
            ui_utils.ui_detail_replace(self, "Báo cáo tổng hợp sẽ hiển thị tại đây sau khi phân tích.")
        ui_utils.ui_progress(self, 0)
        ui_utils.ui_status(self, "Đã xoá kết quả khỏi giao diện.")

    def _refresh_history_list(self):
        if not hasattr(self, "history_list"):
            return
        self.history_list.delete(0, "end")
        d = self._get_reports_dir()
        files = sorted(d.glob("report_*.md"), reverse=True) if d else []
        self._history_files = list(files)
        for p in files:
            self.history_list.insert("end", p.name)

    def _preview_history_selected(self):
        sel = getattr(self, "history_list", None).curselection() if hasattr(self, "history_list") else None
        if not sel:
            return
        p = self._history_files[sel[0]]
        try:
            txt = p.read_text(encoding="utf-8", errors="ignore")
            self.detail_text.config(state="normal")
            self.detail_text.delete("1.0", "end")
            self.detail_text.insert("1.0", txt)
            ui_utils.ui_status(self, f"Xem: {p.name}")
        except Exception as e:
            ui_utils.ui_message(self, "error", "History", str(e))

    def _open_history_selected(self):
        sel = self.history_list.curselection()
        if not sel:
            return
        p = self._history_files[sel[0]]
        try:
            self._open_path(p)
        except Exception as e:
            ui_utils.ui_message(self, "error", "History", str(e))

    def _open_path(self, path: Path):
        """Mở một tệp hoặc thư mục bằng ứng dụng mặc định của hệ điều hành."""
        try:
            if sys.platform == "win32":
                os.startfile(path)
            elif sys.platform == "darwin": # macOS
                subprocess.Popen(["open", path])
            else: # linux
                subprocess.Popen(["xdg-open", path])
        except Exception as e:
            ui_utils.ui_message(self, "error", "Lỗi Mở Tệp", str(e))

    def _delete_history_selected(self):
        sel = self.history_list.curselection()
        if not sel:
            return
        p = self._history_files[sel[0]]
        try:
            p.unlink()
            self._refresh_history_list()
            self.detail_text.delete("1.0", "end")
        except Exception as e:
            ui_utils.ui_message(self, "error", "History", str(e))

    def _open_reports_folder(self):
        d = self._get_reports_dir()
        if d:
            self._open_path(d)

    def _refresh_json_list(self):
        if not hasattr(self, "json_list"):
            return
        self.json_list.delete(0, "end")
        d = self._get_reports_dir()
        files = sorted(d.glob("ctx_*.json"), reverse=True) if d else []
        self.json_files = list(files)
        for p in files:
            self.json_list.insert("end", p.name)

    def _preview_json_selected(self):
        sel = getattr(self, "json_list", None).curselection() if hasattr(self, "json_list") else None
        if not sel:
            return
        p = self.json_files[sel[0]]
        try:
            txt = p.read_text(encoding="utf-8", errors="ignore")
            self.detail_text.config(state="normal")
            self.detail_text.delete("1.0", "end")
            self.detail_text.insert("1.0", txt)
            ui_utils.ui_status(self, f"Xem JSON: {p.name}")
        except Exception as e:
            ui_utils.ui_message(self, "error", "JSON", str(e))

    def _load_json_selected(self):
        sel = self.json_list.curselection()
        if not sel:
            return
        p = self.json_files[sel[0]]
        try:
            self._open_path(p)
        except Exception as e:
            ui_utils.ui_message(self, "error", "JSON", str(e))

    def _delete_json_selected(self):
        sel = self.json_list.curselection()
        if not sel:
            return
        p = self.json_files[sel[0]]
        try:
            p.unlink()
            self._refresh_json_list()
            self.detail_text.delete("1.0", "end")
        except Exception as e:
            ui_utils.ui_message(self, "error", "JSON", str(e))

    def _open_json_folder(self):
        d = self._get_reports_dir()
        if d:
            self._open_path(d)

    def _detect_timeframe_from_name(self, name: str) -> str:
        s = Path(name).stem.lower()

        # Các mẫu regex để nhận dạng khung thời gian từ tên tệp.
        # `(?<![a-z0-9])` và `(?![a-z0-9])` đảm bảo rằng chúng ta khớp toàn bộ từ (ví dụ: "m5" chứ không phải "m50").
        patterns = [
            ("MN1", r"(?<![a-z0-9])(?:mn1|1mo|monthly)(?![a-z0-9])"),
            ("W1",  r"(?<![a-z0-9])(?:w1|1w|weekly)(?![a-z0-9])"),
            ("D1",  r"(?<![a-z0-9])(?:d1|1d|daily)(?![a-z0-9])"),
            ("H4",  r"(?<![a-z0-9])(?:h4|4h)(?![a-z0-9])"),
            ("H1",  r"(?<![a-z0-9])(?:h1|1h)(?![a-z0-9])"),
            ("M30", r"(?<![a-z0-9])(?:m30|30m)(?![a-z0-9])"),
            ("M15", r"(?<![a-z0-9])(?:m15|15m)(?![a-z0-9])"),
            ("M5",  r"(?<![a-z0-9])(?:m5|5m)(?![a-z0-9])"),

            ("M1",  r"(?<![a-z0-9])(?:m1|1m)(?![a-z0-9])"),
        ]

        for tf, pat in patterns:
            if re.search(pat, s):
                return tf
        return "?"

    def _build_timeframe_section(self, names):
        lines = []
        for n in names:
            tf = self._detect_timeframe_from_name(n)
            lines.append(f"- {n} ⇒ {tf}")
        return "\n".join(lines)

    def _toggle_autorun(self):
        if self.autorun_var.get():
            self._schedule_next_autorun()
        else:
            if self._autorun_job:
                self.root.after_cancel(self._autorun_job)
                self._autorun_job = None
            ui_utils.ui_status(self, "Đã tắt auto-run.")

    def _autorun_interval_changed(self):
        if self.autorun_var.get():
            self._schedule_next_autorun()

    def _schedule_next_autorun(self):
        if not self.autorun_var.get():
            return
        if self._autorun_job:
            self.root.after_cancel(self._autorun_job)
        secs = max(5, int(self.autorun_seconds_var.get()))
        self._autorun_job = self.root.after(secs * 1000, self._autorun_tick)
        ui_utils.ui_status(self, f"Tự động chạy sau {secs}s.")

    def _autorun_tick(self):
        self._autorun_job = None
        # Nếu không có phân tích nào đang chạy, bắt đầu một phân tích mới.
        if not self.is_running:
            self.start_analysis()
        else:
            # Nếu một phân tích đang chạy, thực hiện các tác vụ nền (nếu được bật)
            # như quản lý trailing stop cho các lệnh đang mở.
            if self.mt5_enabled_var.get() and self.auto_trade_enabled_var.get():

                cfg_snapshot = self._snapshot_config()
                def _sweep(c):
                    try:
                        ctx = self._mt5_build_context(plan=None, cfg=c) or ""
                        if ctx:
                            data = json.loads(ctx).get("MT5_DATA", {})
                            if data:
                                auto_trade.mt5_manage_be_trailing(self,data, c)
                    except Exception:
                        pass
                threading.Thread(target=_sweep, args=(cfg_snapshot,), daemon=True).start()
            # Lên lịch cho lần chạy tự động tiếp theo.
            self._schedule_next_autorun()

    def _pick_mt5_terminal(self):
        p = filedialog.askopenfilename(
            title="Chọn terminal64.exe hoặc terminal.exe",
            filetypes=[("MT5 terminal", "terminal*.exe"), ("Tất cả", "*.*")],
        )
        if p:
            self.mt5_term_path_var.set(p)

    def _mt5_guess_symbol(self):
        try:
            tfs = {"M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1", "MN1"}
            names = [r["name"] for r in self.results]
            cands = []
            for n in names:
                base = Path(n).stem
                parts = base.split("_")
                if len(parts) >= 2 and parts[-1].upper() in tfs:
                    cands.append("_".join(parts[:-1]))
            if not cands:
                for n in names:
                    s = Path(n).stem
                    head = "".join([ch for ch in s if ch.isalpha()])
                    if head:
                        cands.append(head)
            if cands:
                from collections import Counter
                self.mt5_symbol_var.set(Counter(cands).most_common(1)[0][0])
                ui_utils.ui_status(self, f"Đã đoán symbol: {self.mt5_symbol_var.get()}")
            else:
                ui_utils.ui_message(self, "info", "MT5", "Không đoán được symbol từ tên file.")
        except Exception:
            pass

    def _mt5_connect(self):
        if mt5 is None:
            ui_utils.ui_message(self, "error", "MT5", "Chưa cài thư viện MetaTrader5.\nHãy chạy: pip install MetaTrader5")
            return
        term = self.mt5_term_path_var.get().strip() or None
        try:
            ok = mt5.initialize(path=term) if term else mt5.initialize()
            self.mt5_initialized = bool(ok)
            if not ok:
                err = f"MT5: initialize() thất bại: {mt5.last_error()}"
                ui_utils._enqueue(self, lambda: self.mt5_status_var.set(err))
                ui_utils.ui_message(self, "error", "MT5", f"initialize() lỗi: {mt5.last_error()}")
            else:
                v = mt5.version()
                ui_utils._enqueue(self, lambda: self.mt5_status_var.set(f"MT5: đã kết nối (build {v[0]})"))
                ui_utils.ui_message(self, "info", "MT5", "Kết nối thành công.")
        except Exception as e:
            ui_utils._enqueue(self, lambda: self.mt5_status_var.set(f"MT5: lỗi kết nối: {e}"))
            ui_utils.ui_message(self, "error", "MT5", f"Lỗi kết nối: {e}")

    def _mt5_build_context(self, plan=None, cfg: RunConfig | None = None) -> Optional[SafeMT5Data]:
        sym = (cfg.mt5_symbol if cfg else (self.mt5_symbol_var.get() or "").strip())
        if not ((cfg.mt5_enabled if cfg else self.mt5_enabled_var.get()) and sym) or mt5 is None:
            return None
        if not self.mt5_initialized:
            self._mt5_connect()
            if not self.mt5_initialized:
                return None

        # Ủy quyền cho mt5_utils để xây dựng đối tượng ngữ cảnh MT5
        try:
            return mt5_utils.build_context(
                sym,
                n_m1=(cfg.mt5_n_M1 if cfg else int(self.mt5_n_M1.get())),
                n_m5=(cfg.mt5_n_M5 if cfg else int(self.mt5_n_M5.get())),
                n_m15=(cfg.mt5_n_M15 if cfg else int(self.mt5_n_M15.get())),
                n_h1=(cfg.mt5_n_H1 if cfg else int(self.mt5_n_H1.get())),
                plan=plan,
                return_json=False, # Đảm bảo chúng ta nhận được đối tượng Python, không phải chuỗi JSON
            )
        except Exception:
            return None

    def _mt5_snapshot_popup(self):
        safe_data = self._mt5_build_context(plan=None)
        if not safe_data or not safe_data.raw:
            ui_utils.ui_message(self, "warning", "MT5", "Không thể lấy dữ liệu. Kiểm tra kết nối/biểu tượng (Symbol).")
            return
        
        # Chuyển đổi dữ liệu thô sang chuỗi JSON có định dạng để hiển thị
        try:
            json_text = json.dumps(safe_data.raw, ensure_ascii=False, indent=2)
        except Exception as e:
            json_text = f"Lỗi khi định dạng JSON: {e}\n\nDữ liệu thô:\n{safe_data.raw}"

        win = tk.Toplevel(self.root)
        win.title("MT5 snapshot")
        win.geometry("760x520")
        st = ScrolledText(win, wrap="none")
        st.pack(fill="both", expand=True)
        st.insert("1.0", json_text)

    def _extract_text_from_obj(self, obj):
        parts = []

        def walk(x):
            if isinstance(x, str):
                parts.append(x)
                return
            if isinstance(x, dict):

                for k in ("text", "content", "prompt", "body", "value"):
                    v = x.get(k)
                    if isinstance(v, str) and v.strip():
                        parts.append(v)
                for v in x.values():
                    if v is not None and not isinstance(v, str):
                        walk(v)
            elif isinstance(x, list):
                for v in x:
                    walk(v)

        walk(obj)
        text = "\n\n".join(t.strip() for t in parts if t and t.strip())

        if text and text.count("") > 0 and text.count("\n") <= text.count(""):
            text = (text.replace("", "\n")
                        .replace("\\t", "\t")
                        .replace('\\"', '"')
                        .replace("\\'", "'"))
        return text or json.dumps(obj, ensure_ascii=False, indent=2)

    def _normalize_prompt_text(self, raw: str) -> str:
        s = raw.strip()
        if not s:
            return ""

        # Cố gắng phân tích văn bản đầu vào theo các định dạng khác nhau.
        # Ưu tiên 1: Phân tích dưới dạng một chuỗi JSON hoàn chỉnh.
        try:
            obj = json.loads(s)
            return self._extract_text_from_obj(obj)
        except Exception:
            pass

        # Ưu tiên 2: Phân tích dưới dạng một đối tượng Python (ví dụ: dict, list).
        try:
            obj = ast.literal_eval(s)
            return self._extract_text_from_obj(obj)
        except Exception:
            pass

        # Nếu cả hai cách trên đều thất bại, trả về chuỗi văn bản gốc.
        return s

    def _reformat_prompt_area(self):
        try:
            selected_tab_index = self.prompt_nb.index(self.prompt_nb.select())
            if selected_tab_index == 0:
                widget = self.prompt_no_entry_text
            else:
                widget = self.prompt_entry_run_text
            
            raw = widget.get("1.0", "end")
            pretty = self._normalize_prompt_text(raw)
            widget.delete("1.0", "end")
            widget.insert("1.0", pretty)
        except Exception:
            pass

    def _load_prompts_from_disk(self, silent=False):
        files_to_load = {
            "no_entry": (APP_DIR / "prompt_no_entry.txt", self.prompt_no_entry_text),
            "entry_run": (APP_DIR / "prompt_entry_run.txt", self.prompt_entry_run_text),
        }
        loaded_count = 0
        for key, (path, widget) in files_to_load.items():
            try:
                if path.exists():
                    raw = path.read_text(encoding="utf-8", errors="ignore")
                    text = self._normalize_prompt_text(raw)
                    widget.delete("1.0", "end")
                    widget.insert("1.0", text)
                    loaded_count += 1
                elif not silent:
                    widget.delete("1.0", "end")
                    widget.insert("1.0", f"[LỖI] Không tìm thấy file: {path.name}")
            except Exception as e:
                if not silent:
                    ui_utils.ui_message(self, "error", "Prompt", f"Lỗi nạp {path.name}: {e}")
        
        if loaded_count > 0 and not silent:
            ui_utils.ui_status(self, f"Đã nạp {loaded_count} prompt từ file.")

    def _save_current_prompt_to_disk(self):
        try:
            selected_tab_index = self.prompt_nb.index(self.prompt_nb.select())
            if selected_tab_index == 0:
                widget = self.prompt_no_entry_text
                path = APP_DIR / "prompt_no_entry.txt"
            else:
                widget = self.prompt_entry_run_text
                path = APP_DIR / "prompt_entry_run.txt"

            # Lấy nội dung từ widget, "-1c" để loại bỏ ký tự xuống dòng thừa ở cuối
            content = widget.get("1.0", "end-1c") 
            path.write_text(content, encoding="utf-8")
            ui_utils.ui_message(self, "info", "Prompt", f"Đã lưu thành công vào {path.name}")

        except Exception as e:
            ui_utils.ui_message(self, "error", "Prompt", f"Lỗi lưu file: {e}")

    def _save_workspace(self):
        data = {
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
            "telegram_token_enc": obfuscate_text(self.telegram_token_var.get().strip())
            if self.telegram_token_var.get().strip()
            else "",
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

            "norun_weekend": bool(self.norun_weekend_var.get()),
            "norun_killzone": bool(self.norun_killzone_var.get()),
        }
        try:
            WORKSPACE_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            ui_utils.ui_message(self, "info", "Workspace", "Đã lưu workspace.")
        except Exception as e:
            ui_utils.ui_message(self, "error", "Workspace", str(e))

    def _load_workspace(self):
        if not WORKSPACE_JSON.exists():
            return
        try:
            data = json.loads(WORKSPACE_JSON.read_text(encoding="utf-8"))
        except Exception:
            return

        self.prompt_file_path_var.set(data.get("prompt_file_path", ""))
        self.auto_load_prompt_txt_var.set(bool(data.get("auto_load_prompt_txt", True)))
        folder = data.get("folder_path", "")
        if folder and Path(folder).exists():
            self.folder_path.set(folder)
            self._load_files(folder)
            self._refresh_history_list()
            self._refresh_json_list()

        self.model_var.set(data.get("model", DEFAULT_MODEL))
        self.delete_after_var.set(bool(data.get("delete_after", True)))
        self.max_files_var.set(int(data.get("max_files", 0)))
        self.autorun_var.set(bool(data.get("autorun", False)))
        self.autorun_seconds_var.set(int(data.get("autorun_secs", 60)))

        self.remember_context_var.set(bool(data.get("remember_ctx", True)))
        self.context_n_reports_var.set(int(data.get("ctx_n_reports", 1)))
        self.context_limit_chars_var.set(int(data.get("ctx_limit_chars", 2000)))
        self.create_ctx_json_var.set(bool(data.get("create_ctx_json", True)))
        self.prefer_ctx_json_var.set(bool(data.get("prefer_ctx_json", True)))
        self.ctx_json_n_var.set(int(data.get("ctx_json_n", 5)))

        self.telegram_enabled_var.set(bool(data.get("telegram_enabled", False)))
        self.telegram_token_var.set(deobfuscate_text(data.get("telegram_token_enc", "")))
        self.telegram_chat_id_var.set(data.get("telegram_chat_id", ""))
        self.telegram_skip_verify_var.set(bool(data.get("telegram_skip_verify", False)))
        self.telegram_ca_path_var.set(data.get("telegram_ca_path", ""))

        self.mt5_enabled_var.set(bool(data.get("mt5_enabled", False)))
        self.mt5_term_path_var.set(data.get("mt5_term_path", ""))
        self.mt5_symbol_var.set(data.get("mt5_symbol", ""))
        self.mt5_n_M1.set(int(data.get("mt5_n_M1", 120)))
        self.mt5_n_M5.set(int(data.get("mt5_n_M5", 180)))
        self.mt5_n_M15.set(int(data.get("mt5_n_M15", 96)))
        self.mt5_n_H1.set(int(data.get("mt5_n_H1", 120)))

        self.no_trade_enabled_var.set(bool(data.get("no_trade_enabled", True)))
        self.nt_spread_factor_var.set(float(data.get("nt_spread_factor", 1.2)))
        self.nt_min_atr_m5_pips_var.set(float(data.get("nt_min_atr_m5_pips", 3.0)))
        self.nt_min_ticks_per_min_var.set(int(data.get("nt_min_ticks_per_min", 5)))

        self.upload_workers_var.set(int(data.get("upload_workers", 4)))
        self.cache_enabled_var.set(bool(data.get("cache_enabled", True)))
        self.optimize_lossless_var.set(bool(data.get("opt_lossless", False)))
        self.only_generate_if_changed_var.set(bool(data.get("only_generate_if_changed", False)))

        self.auto_trade_enabled_var.set(bool(data.get("auto_trade_enabled", False)))
        self.trade_strict_bias_var.set(bool(data.get("trade_strict_bias", True)))
        self.trade_size_mode_var.set(data.get("trade_size_mode", "lots"))
        self.trade_lots_total_var.set(float(data.get("trade_lots_total", 0.10)))
        self.trade_equity_risk_pct_var.set(float(data.get("trade_equity_risk_pct", 1.0)))
        self.trade_money_risk_var.set(float(data.get("trade_money_risk", 10.0)))
        self.trade_split_tp1_pct_var.set(int(data.get("trade_split_tp1_pct", 50)))
        self.trade_deviation_points_var.set(int(data.get("trade_deviation_points", 20)))
        self.trade_pending_threshold_points_var.set(int(data.get("trade_pending_threshold_points", 60)))
        self.trade_magic_var.set(int(data.get("trade_magic", 26092025)))
        self.trade_comment_prefix_var.set(data.get("trade_comment_prefix", "AI-ICT"))

        before_val = data.get("news_block_before_min")
        after_val  = data.get("news_block_after_min")
        legacy_val = data.get("trade_news_block_min")

        try:
            before = int(before_val) if before_val is not None else None
        except Exception:
            before = None
        try:
            after = int(after_val) if after_val is not None else None
        except Exception:
            after = None
        try:
            legacy = int(legacy_val) if legacy_val is not None else None
        except Exception:
            legacy = None

        if before is None and legacy is not None:
            before = legacy
        if after is None and legacy is not None:
            after = legacy

        if before is None:
            before = 15
        if after is None:
            after = 15

        self.trade_news_block_before_min_var.set(before)
        self.trade_news_block_after_min_var.set(after)

        self.norun_weekend_var.set(bool(data.get("norun_weekend", True)))
        self.norun_killzone_var.set(bool(data.get("norun_killzone", True)))

    def _delete_workspace(self):
        try:
            if WORKSPACE_JSON.exists():
                WORKSPACE_JSON.unlink()
            ui_utils.ui_message(self, "info", "Workspace", "Đã xoá workspace.")
        except Exception as e:
            ui_utils.ui_message(self, "error", "Workspace", str(e))

def main():
    """
    Hàm chính để khởi tạo và chạy ứng dụng.
    """
    log_file_path = APP_DIR / "app_debug.log"
    try:
        # Cấu hình ghi log ra file để dễ dàng gỡ lỗi
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
