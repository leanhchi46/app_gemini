# -*- coding: utf-8 -*-
"""\nỨNG DỤNG: Gemini Folder Analyze Once — Phân tích Ảnh Theo Lô (1 lần) + Báo cáo ICT/SMC\n========================================================================================\nMục tiêu:\n- Tự động nạp toàn bộ ảnh trong 1 thư mục (các khung D1/H4/M15/M1 hoặc theo đặt tên).\n- (Tuỳ chọn) Lấy dữ liệu từ MT5 để bổ sung số liệu khách quan (ATR, spread, VWAP, PDH/PDL...).\n- Gọi model Gemini để tạo BÁO CÁO TIÊU CHUẨN (7 dòng + phần A→E + JSON máy-đọc-được).\n- Hỗ trợ cache/upload song song, xuất báo cáo .md, gửi Telegram, NO-TRADE, và auto-trade thử nghiệm.\n\nKiến trúc tổng quan:\n- Tkinter GUI (Notebook: Report/Prompt/Options) + hàng đợi UI để đảm bảo thread-safe.\n- Lớp GeminiFolderOnceApp: chứa toàn bộ trạng thái và quy trình điều phối.\n- RunConfig (dataclass): snapshot cấu hình từ UI để dùng trong worker thread.\n- Các khối chức năng: upload/cache, gọi Gemini, hợp nhất báo cáo, MT5/Telegram/News, auto-trade.\n\nLưu ý:\n- Không thay đổi logic/chức năng gốc; chỉ xoá các comment cũ và thay bằng docstring tiếng Việt.\n- Tất cả docstring đều nhằm giải thích ý tưởng/luồng xử lý; không ảnh hưởng hành vi runtime.\n"""

from __future__ import annotations

import os
import sys
import re
import json
import time
import ssl
import hashlib
import queue
import threading

import ast
from pathlib import Path
import math
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
import platform

import tkinter as tk
from tkinter import ttk, filedialog
from tkinter.scrolledtext import ScrolledText

HAS_MPL = False
try:
    # Only matplotlib is required for the Chart tab; mplfinance is optional.
    import matplotlib  # type: ignore
    HAS_MPL = True
except Exception:
    HAS_MPL = False

try:
    from dotenv import load_dotenv
except Exception:
    load_dotenv = None

try:
    import google.generativeai as genai
except Exception:
    print("Bạn cần cài SDK Gemini: pip install google-generativeai")
    sys.exit(1)

try:
    import MetaTrader5 as mt5
except Exception:
    mt5 = None

try:
    from PIL import Image
except Exception:
    Image = None

from gemini_folder_once.constants import (
    SUPPORTED_EXTS,
    DEFAULT_MODEL,
    APP_DIR,
    WORKSPACE_JSON,
    API_KEY_ENC,
    UPLOAD_CACHE_JSON,
)

from gemini_folder_once.utils import (
    _xor_bytes,
    _machine_key,
    obfuscate_text,
    deobfuscate_text,
)

from gemini_folder_once.telegram_client import TelegramClient, build_ssl_context

from gemini_folder_once.config import RunConfig
from gemini_folder_once import context_builder, report_parser
from gemini_folder_once import no_trade, news, auto_trade
from gemini_folder_once.chart_tab import ChartTabTV
from gemini_folder_once import uploader
from gemini_folder_once import mt5_utils
from gemini_folder_once import no_run
from gemini_folder_once import worker
from gemini_folder_once.utils import _tg_html_escape

class GeminiFolderOnceApp:
    """
    Lớp giao diện và điều phối chính của ứng dụng: quản lý cấu hình, hàng đợi UI, tải ảnh, gọi Gemini, tổng hợp báo cáo, tích hợp MT5/Telegram và (tuỳ chọn) auto-trade.
    Trách nhiệm chính:
      - Khởi tạo UI (Notebook: Report/Prompt/Options, v.v.).
      - Đọc/ghi workspace, cache, prompt.
      - Quy trình phân tích 1 lần: nạp ảnh → (tối ưu/cache) upload → gọi Gemini → gom báo cáo.
      - (Tuỳ chọn) Lấy dữ liệu MT5, tạo JSON ngữ cảnh, lọc NO-TRADE, gửi Telegram.
      - Quản trị thread an toàn với Tkinter thông qua hàng đợi UI.
    """
    def __init__(self, root: tk.Tk):
        """
        Mục đích: Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
        Tham số:
          - root: tk.Tk — (tự suy luận theo ngữ cảnh sử dụng).
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        self.root = root
        self.root.title("PHẦN MỀM GIAO DỊCH TỰ ĐỘNG BY CHÍ")
        self.root.geometry("1180x780")
        self.root.minsize(1024, 660)
        self._trade_log_lock = threading.Lock()
        self._proposed_trade_log_lock = threading.Lock()
        self._vector_db_lock = threading.Lock()

        self._ui_log_lock = threading.Lock()

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

        # Persist last NO-TRADE evaluation for Chart tab
        self.last_no_trade_ok = None
        self.last_no_trade_reasons = []

        # News cache refresh coordination
        self._news_refresh_lock = threading.Lock()
        self._news_refresh_inflight = False

        self.is_running = False
        self.stop_flag = False
        self.results = []
        self.combined_report_text = ""
        self.ui_queue = queue.Queue()

        self.prompt_file_path_var = tk.StringVar(value="")
        self.auto_load_prompt_txt_var = tk.BooleanVar(value=True)

        self._build_ui()
        self._load_workspace()
        self._poll_ui_queue()

        # Warm the news cache shortly after start (non-blocking)
        try:
            self._refresh_news_cache(ttl=300)
        except Exception:
            pass

    def _refresh_news_cache(self, ttl: int = 300, *, async_fetch: bool = True, cfg: RunConfig | None = None) -> None:
        """
        Refresh high-impact news cache if TTL expired.

        - Updates `self.ff_cache_events_local` and `self.ff_cache_fetch_time`.
        - If `async_fetch` is True, spawns a background thread to avoid UI blocking.
        - Accepts optional `cfg`; otherwise snapshots current config.
        """
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

            # Synchronous fetch (avoid duplicate concurrent fetches)
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

    def _build_ui(self):
        """
        Mục đích: Khởi tạo/cấu hình thành phần giao diện hoặc cấu trúc dữ liệu nội bộ.
        Tham số: (không)
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        self.root.columnconfigure(0, weight=1)

        top = ttk.Frame(self.root, padding=(10, 8, 10, 6))
        top.grid(row=0, column=0, sticky="ew")
        for c in (1, 3, 5):
            top.columnconfigure(c, weight=1)

        ttk.Label(top, text="API Key:").grid(row=0, column=0, sticky="w")
        self.api_entry = ttk.Entry(top, textvariable=self.api_key_var, show="*", width=44)
        self.api_entry.grid(row=0, column=1, sticky="ew", padx=(6, 8))
        ttk.Checkbutton(top, text="Hiện", command=self._toggle_api_visibility).grid(row=0, column=2, sticky="w")

        ttk.Button(top, text="Tải .env", command=self._load_env).grid(row=0, column=3, sticky="w")
        ttk.Button(top, text="Lưu an toàn", command=self._save_api_safe).grid(row=0, column=4, sticky="w", padx=(6, 0))
        ttk.Button(top, text="Xoá đã lưu", command=self._delete_api_safe).grid(row=0, column=5, sticky="w", padx=(6, 0))

        ttk.Label(top, text="Model:").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.model_combo = ttk.Combobox(
            top,
            textvariable=self.model_var,
            values=["gemini-1.5-flash", "gemini-1.5-pro", "gemini-2.5-flash", "gemini-2.5-pro"],
            state="readonly",
            width=22,
        )
        self.model_combo.grid(row=1, column=1, sticky="w", padx=(6, 8), pady=(6, 0))

        ttk.Label(top, text="Thư mục ảnh:").grid(row=1, column=2, sticky="e", pady=(6, 0))
        self.folder_label = ttk.Entry(top, textvariable=self.folder_path, state="readonly")
        self.folder_label.grid(row=1, column=3, sticky="ew", padx=(6, 8), pady=(6, 0))
        ttk.Button(top, text="Chọn thư mục…", command=self.choose_folder).grid(row=1, column=4, sticky="w", pady=(6, 0))

        actions = ttk.Frame(top)
        actions.grid(row=1, column=5, sticky="e", pady=(6, 0))
        ttk.Button(actions, text="► Bắt đầu", command=self.start_analysis).pack(side="left")
        self.stop_btn = ttk.Button(actions, text="□ Dừng", command=self.stop_analysis, state="disabled")
        self.stop_btn.pack(side="left", padx=(6, 0))
        self.export_btn = ttk.Button(actions, text="↓ Xuất .md", command=self.export_markdown, state="disabled")
        self.export_btn.pack(side="left", padx=(6, 0))
        ttk.Button(actions, text="✖ Xoá kết quả", command=self.clear_results).pack(side="left", padx=(6, 0))

        prog = ttk.Frame(self.root, padding=(10, 0, 10, 6))
        prog.grid(row=1, column=0, sticky="ew")
        prog.columnconfigure(0, weight=1)
        ttk.Progressbar(prog, variable=self.progress_var, maximum=100).grid(row=0, column=0, sticky="ew")
        ttk.Label(prog, textvariable=self.status_var).grid(row=1, column=0, sticky="w", pady=(3, 0))

        self.nb = ttk.Notebook(self.root)
        self.nb.grid(row=2, column=0, sticky="nsew", padx=8, pady=(0, 8))
        self.root.rowconfigure(2, weight=1)

        tab_report = ttk.Frame(self.nb, padding=8)
        self.nb.add(tab_report, text="Report")

        tab_report.columnconfigure(0, weight=1)
        tab_report.columnconfigure(1, weight=2)
        tab_report.rowconfigure(0, weight=1)

        left_panel = ttk.Frame(tab_report)
        left_panel.grid(row=0, column=0, sticky="nsew")
        left_panel.columnconfigure(0, weight=1)
        left_panel.rowconfigure(0, weight=1)
        left_panel.rowconfigure(1, weight=1)

        cols = ("#", "name", "status")
        self.tree = ttk.Treeview(left_panel, columns=cols, show="headings", selectmode="browse")
        self.tree.heading("#", text="#")
        self.tree.heading("name", text="Tệp ảnh")
        self.tree.heading("status", text="Trạng thái")
        self.tree.column("#", width=56, anchor="e")
        self.tree.column("name", width=320, anchor="w")
        self.tree.column("status", width=180, anchor="w")
        self.tree.grid(row=0, column=0, sticky="nsew")
        scr_y = ttk.Scrollbar(left_panel, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand= scr_y.set)
        scr_y.grid(row=0, column=0, sticky="nse", padx=(0,0))
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)

        archives = ttk.LabelFrame(left_panel, text="History & JSON", padding=6)
        archives.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        archives.columnconfigure(0, weight=1)
        archives.columnconfigure(1, weight=1)
        archives.rowconfigure(1, weight=1)

        hist_col = ttk.Frame(archives)
        hist_col.grid(row=0, column=0, rowspan=2, sticky="nsew", padx=(0, 6))
        hist_col.columnconfigure(0, weight=1)
        hist_col.rowconfigure(1, weight=1)

        ttk.Label(hist_col, text="History (.md)").grid(row=0, column=0, sticky="w")
        self.history_list = tk.Listbox(hist_col, exportselection=False)
        self.history_list.grid(row=1, column=0, sticky="nsew")
        hist_scr = ttk.Scrollbar(hist_col, orient="vertical", command=self.history_list.yview)
        self.history_list.configure(yscrollcommand=hist_scr.set)
        hist_scr.grid(row=1, column=1, sticky="ns")

        hist_btns = ttk.Frame(hist_col); hist_btns.grid(row=2, column=0, sticky="ew", pady=(6,0))
        ttk.Button(hist_btns, text="Mở",   command=self._open_history_selected).pack(side="left")
        ttk.Button(hist_btns, text="Xoá",  command=self._delete_history_selected).pack(side="left", padx=(6,0))
        ttk.Button(hist_btns, text="Thư mục", command=self._open_reports_folder).pack(side="left", padx=(6,0))

        self.history_list.bind("<<ListboxSelect>>", lambda e: self._preview_history_selected())
        self.history_list.bind("<Double-Button-1>", lambda e: self._open_history_selected())

        json_col = ttk.Frame(archives)
        json_col.grid(row=0, column=1, rowspan=2, sticky="nsew", padx=(6, 0))
        json_col.columnconfigure(0, weight=1)
        json_col.rowconfigure(1, weight=1)

        ttk.Label(json_col, text="JSON (ctx_*.json)").grid(row=0, column=0, sticky="w")
        self.json_list = tk.Listbox(json_col, exportselection=False)
        self.json_list.grid(row=1, column=0, sticky="nsew")
        json_scr = ttk.Scrollbar(json_col, orient="vertical", command=self.json_list.yview)
        self.json_list.configure(yscrollcommand=json_scr.set)
        json_scr.grid(row=1, column=1, sticky="ns")

        json_btns = ttk.Frame(json_col); json_btns.grid(row=2, column=0, sticky="ew", pady=(6,0))
        ttk.Button(json_btns, text="Mở",   command=self._load_json_selected).pack(side="left")
        ttk.Button(json_btns, text="Xoá",  command=self._delete_json_selected).pack(side="left", padx=(6,0))
        ttk.Button(json_btns, text="Thư mục", command=self._open_json_folder).pack(side="left", padx=(6,0))

        self.json_list.bind("<<ListboxSelect>>", lambda e: self._preview_json_selected())
        self.json_list.bind("<Double-Button-1>", lambda e: self._load_json_selected())

        detail_box = ttk.LabelFrame(tab_report, text="Chi tiết (Báo cáo Tổng hợp)", padding=8)
        detail_box.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        detail_box.rowconfigure(0, weight=1)
        detail_box.columnconfigure(0, weight=1)
        self.detail_text = ScrolledText(detail_box, wrap="word")
        self.detail_text.grid(row=0, column=0, sticky="nsew")
        self.detail_text.insert("1.0", "Báo cáo tổng hợp sẽ hiển thị tại đây sau khi phân tích.")

        self._refresh_history_list()
        self._refresh_json_list()

        if HAS_MPL:
            self.chart_tab_tv = ChartTabTV(self, self.nb)
        else:

            tab_chart_placeholder = ttk.Frame(self.nb, padding=8)
            self.nb.add(tab_chart_placeholder, text="Chart")
            ttk.Label(
                tab_chart_placeholder,
                text="Chức năng Chart yêu cầu matplotlib + mplfinance.\n"
                    "Cài: pip install matplotlib",
                foreground="#666"
            ).pack(anchor="w")

        tab_prompt = ttk.Frame(self.nb, padding=8)
        self.nb.add(tab_prompt, text="Prompt")
        tab_prompt.columnconfigure(0, weight=1)
        tab_prompt.rowconfigure(1, weight=1)

        pr = ttk.Frame(tab_prompt)
        pr.grid(row=0, column=0, sticky="ew")

        ttk.Button(pr, text="Tải PROMPT.txt", command=self._auto_load_prompt_for_current_folder).pack(side="left")
        ttk.Button(pr, text="Chọn file…", command=self._pick_prompt_file).pack(side="left", padx=(6, 0))
        ttk.Button(pr, text="Định dạng lại", command=self._reformat_prompt_area).pack(side="left", padx=(6, 0))
        ttk.Checkbutton(pr, text="Tự động nạp khi chọn thư mục",
                        variable=self.auto_load_prompt_txt_var).pack(side="left", padx=(10, 0))

        self.prompt_text = ScrolledText(tab_prompt, wrap="word", height=18)
        self.prompt_text.grid(row=1, column=0, sticky="nsew", pady=(6, 0))

        if not self._load_prompt_from_file(silent=True):
            self.ui_status("Chưa nạp PROMPT.txt — hãy bấm 'Tải PROMPT.txt' hoặc 'Chọn file…'")

        tab_opts = ttk.Frame(self.nb, padding=8)
        self.nb.add(tab_opts, text="Options")
        tab_opts.columnconfigure(0, weight=1)
        tab_opts.rowconfigure(0, weight=1)
        opts_nb = ttk.Notebook(tab_opts)
        opts_nb.grid(row=0, column=0, sticky="nsew")

        run_tab = ttk.Frame(opts_nb, padding=8)
        opts_nb.add(run_tab, text="Run")
        run_tab.columnconfigure(0, weight=1)

        card_auto = ttk.LabelFrame(run_tab, text="Auto-run", padding=8)
        card_auto.grid(row=0, column=0, sticky="ew")
        row_ar = ttk.Frame(card_auto)
        row_ar.grid(row=0, column=0, sticky="w")
        ttk.Checkbutton(row_ar, text="Tự động chạy định kỳ", variable=self.autorun_var,
                        command=self._toggle_autorun).pack(side="left")
        ttk.Label(row_ar, text="  mỗi (giây):").pack(side="left")
        self.autorun_interval_spin = ttk.Spinbox(
            row_ar, from_=5, to=86400, textvariable=self.autorun_seconds_var, width=8,
            command=self._autorun_interval_changed
        )
        self.autorun_interval_spin.pack(side="left", padx=(6, 0))
        self.autorun_interval_spin.bind("<FocusOut>", lambda e: self._autorun_interval_changed())

        card_upload = ttk.LabelFrame(run_tab, text="Upload & Giới hạn", padding=8)
        card_upload.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        ttk.Checkbutton(card_upload, text="Xoá file trên Gemini sau khi phân tích",
                        variable=self.delete_after_var).grid(row=0, column=0, sticky="w")
        row_ul = ttk.Frame(card_upload)
        row_ul.grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Label(row_ul, text="Giới hạn số ảnh tối đa (0 = không giới hạn):").pack(side="left")
        ttk.Spinbox(row_ul, from_=0, to=1000, textvariable=self.max_files_var, width=8).pack(side="left", padx=(6, 0))

        card_fast = ttk.LabelFrame(run_tab, text="Tăng tốc & Cache", padding=8)
        card_fast.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        row_w = ttk.Frame(card_fast)
        row_w.grid(row=0, column=0, sticky="w")
        ttk.Label(row_w, text="Số luồng upload song song:").pack(side="left")
        ttk.Spinbox(row_w, from_=1, to=16, textvariable=self.upload_workers_var, width=6).pack(side="left", padx=(6, 0))
        ttk.Checkbutton(card_fast, text="Bật cache ảnh (tái dùng file đã upload nếu chưa đổi)",
                        variable=self.cache_enabled_var).grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Checkbutton(card_fast, text="Tối ưu ảnh lossless trước khi upload (PNG)",
                        variable=self.optimize_lossless_var).grid(row=2, column=0, sticky="w", pady=(6, 0))
        ttk.Checkbutton(card_fast, text="Chỉ gọi model nếu bộ ảnh không đổi",
                        variable=self.only_generate_if_changed_var).grid(row=3, column=0, sticky="w", pady=(6, 0))

        card_nt = ttk.LabelFrame(run_tab, text="NO-TRADE cứng (chặn gọi model nếu điều kiện xấu)", padding=8)
        card_nt.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        ttk.Checkbutton(card_nt, text="Bật NO-TRADE cứng",
                        variable=self.no_trade_enabled_var).grid(row=0, column=0, columnspan=3, sticky="w")
        r1 = ttk.Frame(card_nt); r1.grid(row=1, column=0, sticky="w", pady=(4, 0))
        ttk.Label(r1, text="Ngưỡng spread > p90 ×").pack(side="left")
        ttk.Spinbox(r1, from_=1.0, to=3.0, increment=0.1,
                    textvariable=self.nt_spread_factor_var, width=6).pack(side="left", padx=(6, 12))
        r2 = ttk.Frame(card_nt); r2.grid(row=2, column=0, sticky="w", pady=(4, 0))
        ttk.Label(r2, text="ATR M5 tối thiểu (pips):").pack(side="left")
        ttk.Spinbox(r2, from_=0.5, to=50.0, increment=0.5,
                    textvariable=self.nt_min_atr_m5_pips_var, width=6).pack(side="left", padx=(6, 12))
        r3 = ttk.Frame(card_nt); r3.grid(row=3, column=0, sticky="w", pady=(4, 0))
        ttk.Label(r3, text="Ticks mỗi phút tối thiểu (5m):").pack(side="left")
        ttk.Spinbox(r3, from_=0, to=200, textvariable=self.nt_min_ticks_per_min_var,
                    width=6).pack(side="left", padx=(6, 12))

        ctx_tab = ttk.Frame(opts_nb, padding=8)
        opts_nb.add(ctx_tab, text="Context")
        ctx_tab.columnconfigure(0, weight=1)

        card_ctx_text = ttk.LabelFrame(ctx_tab, text="Ngữ cảnh từ lịch sử (Text Reports)", padding=8)
        card_ctx_text.grid(row=0, column=0, sticky="ew")
        ttk.Checkbutton(card_ctx_text, text="Dùng ngữ cảnh từ báo cáo trước (text)",
                        variable=self.remember_context_var).grid(row=0, column=0, columnspan=3, sticky="w")
        rowt = ttk.Frame(card_ctx_text)
        rowt.grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Label(rowt, text="Số báo cáo gần nhất:").pack(side="left")
        ttk.Spinbox(rowt, from_=1, to=10, textvariable=self.context_n_reports_var, width=6).pack(side="left", padx=(6, 12))
        ttk.Label(rowt, text="Giới hạn ký tự/report:").pack(side="left")
        ttk.Spinbox(rowt, from_=500, to=8000, increment=250, textvariable=self.context_limit_chars_var, width=8).pack(side="left", padx=(6, 0))

        card_ctx_json = ttk.LabelFrame(ctx_tab, text="Ngữ cảnh tóm tắt JSON", padding=8)
        card_ctx_json.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        ttk.Checkbutton(card_ctx_json, text="Tự tạo tóm tắt JSON sau mỗi lần phân tích",
                        variable=self.create_ctx_json_var).grid(row=0, column=0, sticky="w")
        ttk.Checkbutton(card_ctx_json, text="Ưu tiên dùng tóm tắt JSON làm bối cảnh",
                        variable=self.prefer_ctx_json_var).grid(row=1, column=0, sticky="w", pady=(4, 0))
        rowj = ttk.Frame(card_ctx_json)
        rowj.grid(row=2, column=0, sticky="w", pady=(6, 0))
        ttk.Label(rowj, text="Số JSON gần nhất:").pack(side="left")
        ttk.Spinbox(rowj, from_=1, to=20, textvariable=self.ctx_json_n_var, width=6).pack(side="left", padx=(6, 0))

        tg_tab = ttk.Frame(opts_nb, padding=8)
        opts_nb.add(tg_tab, text="Telegram")
        tg_tab.columnconfigure(1, weight=1)

        ttk.Checkbutton(tg_tab, text="Bật thông báo khi có setup xác suất cao",
                        variable=self.telegram_enabled_var).grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(tg_tab, text="Bot Token:").grid(row=1, column=0, sticky="w", pady=(6, 0))
        tk.Entry(tg_tab, textvariable=self.telegram_token_var, show="*", width=48).grid(row=1, column=1, sticky="ew", padx=(6, 0), pady=(6, 0))
        ttk.Label(tg_tab, text="Chat ID:").grid(row=2, column=0, sticky="w", pady=(6, 0))
        tk.Entry(tg_tab, textvariable=self.telegram_chat_id_var, width=24).grid(row=2, column=1, sticky="w", padx=(6, 0), pady=(6, 0))
        ttk.Button(tg_tab, text="Gửi thử", command=self._telegram_test).grid(row=2, column=2, sticky="e", padx=(8, 0), pady=(6, 0))

        ttk.Label(tg_tab, text="CA bundle (.pem/.crt):").grid(row=3, column=0, sticky="w", pady=(6, 0))
        tk.Entry(tg_tab, textvariable=self.telegram_ca_path_var).grid(row=3, column=1, sticky="ew", padx=(6, 0), pady=(6, 0))
        ttk.Button(tg_tab, text="Chọn…", command=self._pick_ca_bundle).grid(row=3, column=2, sticky="e", padx=(8, 0), pady=(6, 0))
        ttk.Checkbutton(tg_tab, text="Bỏ qua kiểm tra chứng chỉ (KHÔNG KHUYẾN NGHỊ)",
                        variable=self.telegram_skip_verify_var).grid(row=4, column=0, columnspan=3, sticky="w", pady=(6, 0))

        mt5_tab = ttk.Frame(opts_nb, padding=8)
        opts_nb.add(mt5_tab, text="MT5")
        mt5_tab.columnconfigure(1, weight=1)

        ttk.Checkbutton(mt5_tab, text="Bật lấy dữ liệu nến từ MT5 và đưa vào phân tích",
                        variable=self.mt5_enabled_var).grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(mt5_tab, text="MT5 terminal (tùy chọn):").grid(row=1, column=0, sticky="w", pady=(6, 0))
        tk.Entry(mt5_tab, textvariable=self.mt5_term_path_var).grid(row=1, column=1, sticky="ew", padx=(6, 0), pady=(6, 0))
        ttk.Button(mt5_tab, text="Chọn…", command=self._pick_mt5_terminal).grid(row=1, column=2, sticky="e", padx=(8, 0), pady=(6, 0))
        ttk.Label(mt5_tab, text="Symbol:").grid(row=2, column=0, sticky="w", pady=(6, 0))
        tk.Entry(mt5_tab, textvariable=self.mt5_symbol_var, width=18).grid(row=2, column=1, sticky="w", padx=(6, 0), pady=(6, 0))
        ttk.Button(mt5_tab, text="Tự nhận từ tên ảnh", command=self._mt5_guess_symbol).grid(row=2, column=2, sticky="e", padx=(8, 0), pady=(6, 0))

        rowc = ttk.Frame(mt5_tab)
        rowc.grid(row=3, column=0, columnspan=3, sticky="w", pady=(6, 0))
        ttk.Label(rowc, text="Số nến:").pack(side="left")
        ttk.Label(rowc, text="M1").pack(side="left", padx=(10, 2))
        ttk.Spinbox(rowc, from_=30, to=2000, textvariable=self.mt5_n_M1, width=6).pack(side="left")
        ttk.Label(rowc, text="M5").pack(side="left", padx=(10, 2))
        ttk.Spinbox(rowc, from_=30, to=2000, textvariable=self.mt5_n_M5, width=6).pack(side="left")
        ttk.Label(rowc, text="M15").pack(side="left", padx=(10, 2))
        ttk.Spinbox(rowc, from_=20, to=2000, textvariable=self.mt5_n_M15, width=6).pack(side="left")
        ttk.Label(rowc, text="H1").pack(side="left", padx=(10, 2))
        ttk.Spinbox(rowc, from_=20, to=2000, textvariable=self.mt5_n_H1, width=6).pack(side="left")

        btns_mt5 = ttk.Frame(mt5_tab)
        btns_mt5.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(6, 0))
        btns_mt5.columnconfigure(0, weight=1)
        btns_mt5.columnconfigure(1, weight=1)
        ttk.Button(btns_mt5, text="Kết nối/kiểm tra MT5", command=self._mt5_connect).grid(row=0, column=0, sticky="ew")
        ttk.Button(btns_mt5, text="Chụp snapshot ngay", command=self._mt5_snapshot_popup).grid(row=0, column=1, sticky="ew", padx=(6, 0))

        ttk.Label(mt5_tab, textvariable=self.mt5_status_var, foreground="#555").grid(row=5, column=0, columnspan=3, sticky="w", pady=(6, 0))

        auto_card = ttk.LabelFrame(mt5_tab, text="Auto-Trade khi có Thiết lập xác suất cao", padding=8)
        auto_card.grid(row=6, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        r0 = ttk.Frame(auto_card); r0.grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Checkbutton(r0, text="Bật Auto-Trade", variable=self.auto_trade_enabled_var).pack(side="left")
        ttk.Checkbutton(r0, text="KHÔNG trade nếu NGƯỢC bias H1", variable=self.trade_strict_bias_var).pack(side="left", padx=(12,0))

        r1 = ttk.Frame(auto_card); r1.grid(row=1, column=0, columnspan=3, sticky="w", pady=(6,0))
        ttk.Label(r1, text="Khối lượng:").pack(side="left")
        ttk.Radiobutton(r1, text="Lots cố định", value="lots", variable=self.trade_size_mode_var).pack(side="left", padx=(6,0))
        ttk.Radiobutton(r1, text="% Equity", value="percent", variable=self.trade_size_mode_var).pack(side="left", padx=(6,0))
        ttk.Radiobutton(r1, text="Tiền rủi ro", value="money", variable=self.trade_size_mode_var).pack(side="left", padx=(6,0))

        r2 = ttk.Frame(auto_card); r2.grid(row=2, column=0, columnspan=3, sticky="w", pady=(4,0))
        ttk.Label(r2, text="Lots:").pack(side="left")
        ttk.Spinbox(r2, from_=0.01, to=100.0, increment=0.01, textvariable=self.trade_lots_total_var, width=8).pack(side="left", padx=(6,12))
        ttk.Label(r2, text="% Equity rủi ro:").pack(side="left")
        ttk.Spinbox(r2, from_=0.1, to=10.0, increment=0.1, textvariable=self.trade_equity_risk_pct_var, width=6).pack(side="left", padx=(6,12))
        ttk.Label(r2, text="Tiền rủi ro:").pack(side="left")
        ttk.Spinbox(r2, from_=1.0, to=1_000_000.0, increment=1.0, textvariable=self.trade_money_risk_var, width=10).pack(side="left", padx=(6,12))

        r3 = ttk.Frame(auto_card); r3.grid(row=3, column=0, columnspan=3, sticky="w", pady=(4,0))
        ttk.Label(r3, text="Chia TP1 (%):").pack(side="left")
        ttk.Spinbox(r3, from_=1, to=99, textvariable=self.trade_split_tp1_pct_var, width=6).pack(side="left", padx=(6,12))
        ttk.Label(r3, text="Deviation (points):").pack(side="left")
        ttk.Spinbox(r3, from_=5, to=200, textvariable=self.trade_deviation_points_var, width=6).pack(side="left", padx=(6,12))
        ttk.Label(r3, text="Ngưỡng pending (points):").pack(side="left")
        ttk.Spinbox(r3, from_=5, to=2000, textvariable=self.trade_pending_threshold_points_var, width=8).pack(side="left", padx=(6,12))

        r4 = ttk.Frame(auto_card); r4.grid(row=4, column=0, columnspan=3, sticky="w", pady=(4,0))
        ttk.Label(r4, text="Magic:").pack(side="left")
        ttk.Spinbox(r4, from_=1, to=2_147_000_000, textvariable=self.trade_magic_var, width=12).pack(side="left", padx=(6,12))
        ttk.Label(r4, text="Comment:").pack(side="left")
        tk.Entry(r4, textvariable=self.trade_comment_prefix_var, width=18).pack(side="left", padx=(6,0))

        r5 = ttk.Frame(auto_card); r5.grid(row=5, column=0, columnspan=3, sticky="w", pady=(4,0))
        ttk.Checkbutton(r5, text="Dry-run (không gửi lệnh)", variable=self.auto_trade_dry_run_var).pack(side="left")
        ttk.Checkbutton(r5, text="Pending theo ATR", variable=self.trade_dynamic_pending_var).pack(side="left", padx=(12,0))
        ttk.Checkbutton(r5, text="BE sau TP1", variable=self.trade_move_to_be_after_tp1_var).pack(side="left", padx=(12,0))

        r6 = ttk.Frame(auto_card); r6.grid(row=6, column=0, columnspan=3, sticky="w", pady=(4,0))
        ttk.Label(r6, text="TTL pending (phút):").pack(side="left")
        ttk.Spinbox(r6, from_=1, to=1440, textvariable=self.trade_pending_ttl_min_var, width=6).pack(side="left", padx=(6,12))
        ttk.Label(r6, text="RR tối thiểu TP2:").pack(side="left")
        ttk.Spinbox(r6, from_=1.0, to=10.0, increment=0.1, textvariable=self.trade_min_rr_tp2_var, width=6).pack(side="left", padx=(6,12))
        ttk.Label(r6, text="Khoảng cách key lvl (pips):").pack(side="left")
        ttk.Spinbox(r6, from_=0.0, to=200.0, increment=0.5, textvariable=self.trade_min_dist_keylvl_pips_var, width=8).pack(side="left", padx=(6,12))
        ttk.Label(r6, text="Cooldown (phút):").pack(side="left")
        ttk.Spinbox(r6, from_=0, to=360, textvariable=self.trade_cooldown_min_var, width=6).pack(side="left", padx=(6,12))

        r7 = ttk.Frame(auto_card); r7.grid(row=7, column=0, columnspan=3, sticky="w", pady=(4,0))
        ttk.Label(r7, text="Trailing ATR ×").pack(side="left")
        ttk.Spinbox(r7, from_=0.1, to=3.0, increment=0.1, textvariable=self.trade_trailing_atr_mult_var, width=6).pack(side="left", padx=(6,12))

        r8 = ttk.Frame(auto_card); r8.grid(row=8, column=0, columnspan=3, sticky="w", pady=(4,0))
        ttk.Label(r8, text="Phiên cho phép:").pack(side="left")
        ttk.Checkbutton(r8, text="Asia",   variable=self.trade_allow_session_asia_var).pack(side="left", padx=(6,0))
        ttk.Checkbutton(r8, text="London", variable=self.trade_allow_session_london_var).pack(side="left", padx=(6,0))
        ttk.Checkbutton(r8, text="New York", variable=self.trade_allow_session_ny_var).pack(side="left", padx=(6,0))

        r9 = ttk.Frame(auto_card); r9.grid(row=9, column=0, columnspan=3, sticky="w", pady=(4,0))
        ttk.Label(r9, text="Chặn quanh news:").pack(side="left")
        ttk.Label(r9, text="Trước (phút):").pack(side="left", padx=(8,2))
        ttk.Spinbox(r9, from_=0, to=180, textvariable=self.trade_news_block_before_min_var, width=6).pack(side="left")
        ttk.Label(r9, text="Sau (phút):").pack(side="left", padx=(8,2))
        ttk.Spinbox(r9, from_=0, to=180, textvariable=self.trade_news_block_after_min_var, width=6).pack(side="left")
        ttk.Label(r9, text="Nguồn: Forex Factory (High)").pack(side="left", padx=(12,0))

        norun_tab = ttk.Frame(opts_nb, padding=8)
        opts_nb.add(norun_tab, text="No Run")
        norun_tab.columnconfigure(0, weight=1)
        card_norun = ttk.LabelFrame(norun_tab, text="Điều kiện không chạy phân tích tự động", padding=8)
        card_norun.grid(row=0, column=0, sticky="ew")
        ttk.Checkbutton(card_norun, text="Không chạy vào Thứ 7 và Chủ Nhật",
                        variable=self.norun_weekend_var).grid(row=0, column=0, sticky="w")
        ttk.Checkbutton(card_norun, text="Chỉ chạy trong thời gian Kill Zone",
                        variable=self.norun_killzone_var).grid(row=1, column=0, sticky="w", pady=(4, 0))

        ws_tab = ttk.Frame(opts_nb, padding=8)
        opts_nb.add(ws_tab, text="Workspace")
        for i in range(3):
            ws_tab.columnconfigure(i, weight=1)
        ttk.Button(ws_tab, text="Lưu workspace", command=self._save_workspace).grid(row=0, column=0, sticky="ew")
        ttk.Button(ws_tab, text="Khôi phục", command=self._load_workspace).grid(row=0, column=1, sticky="ew", padx=6)
        ttk.Button(ws_tab, text="Xoá workspace", command=self._delete_workspace).grid(row=0, column=2, sticky="ew")

    def _toggle_api_visibility(self):
        """
        Mục đích: Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
        Tham số: (không)
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        self.api_entry.configure(show="" if self.api_entry.cget("show") == "*" else "*")

    def _snapshot_config(self) -> RunConfig:
        """
        Mục đích: Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
        Tham số: (không)
        Trả về: RunConfig
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
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
            # News controls not yet exposed in UI: keep enabled with sane TTL
            trade_news_block_enabled=True,
            news_cache_ttl_sec=300,
        )

    def _load_env(self):
        """
        Mục đích: Làm việc với file/thư mục (chọn, nạp, xem trước, xoá, cập nhật danh sách).
        Tham số: (không)
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
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
                self.ui_message("info", "ENV", "Đã nạp GOOGLE_API_KEY từ file.")
            except Exception as e:
                self.ui_message("error", "ENV", str(e))
        else:
            load_dotenv(path)
            val = os.environ.get("GOOGLE_API_KEY", "")
            if val:
                self.api_key_var.set(val)
                self.ui_message("info", "ENV", "Đã nạp GOOGLE_API_KEY từ .env")

    def _save_api_safe(self):
        """
        Mục đích: Ghi/Xuất dữ liệu (báo cáo .md, JSON tóm tắt, cache...).
        Tham số: (không)
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        try:
            API_KEY_ENC.write_text(obfuscate_text(self.api_key_var.get().strip()), encoding="utf-8")
            self.ui_message("info", "API", f"Đã lưu an toàn vào: {API_KEY_ENC}")
        except Exception as e:
            self.ui_message("error", "API", str(e))

    def _delete_api_safe(self):
        """
        Mục đích: Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
        Tham số: (không)
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        try:
            if API_KEY_ENC.exists():
                API_KEY_ENC.unlink()
            self.ui_message("info", "API", "Đã xoá API key đã lưu.")
        except Exception as e:
            self.ui_message("error", "API", str(e))

    def _get_reports_dir(self, folder_override: str | None = None) -> Path:
        """
        Mục đích: Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
        Tham số:
          - folder_override: str | None — (tự suy luận theo ngữ cảnh sử dụng).
        Trả về: Path
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        folder = Path(folder_override) if folder_override else (Path(self.folder_path.get().strip()) if self.folder_path.get().strip() else None)
        if not folder:
            return None
        d = folder / "Reports"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def choose_folder(self):
        """
        Mục đích: Làm việc với file/thư mục (chọn, nạp, xem trước, xoá, cập nhật danh sách).
        Tham số: (không)
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        folder = filedialog.askdirectory(title="Chọn thư mục chứa ảnh")
        if not folder:
            return
        self.folder_path.set(folder)
        self._load_files(folder)
        self._auto_load_prompt_for_current_folder()
        self._refresh_history_list()
        self._refresh_json_list()

    def _load_files(self, folder):
        """
        Mục đích: Làm việc với file/thư mục (chọn, nạp, xem trước, xoá, cập nhật danh sách).
        Tham số:
          - folder — (tự suy luận theo ngữ cảnh sử dụng).
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
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
        self.ui_status(
            f"Đã nạp {count} ảnh. Sẵn sàng phân tích 1 lần."
            if count
            else "Không tìm thấy ảnh phù hợp trong thư mục đã chọn."
        )
        self.ui_progress(0)
        if hasattr(self, "export_btn"):
            self.export_btn.configure(state="disabled")
        if hasattr(self, "detail_text"):
            self.ui_detail_replace("Báo cáo tổng hợp sẽ hiển thị tại đây sau khi phân tích.")

    def start_analysis(self):
        """
        Mục đích: Bắt đầu quy trình chính (khởi tạo trạng thái, đọc cấu hình, chạy tác vụ nền).
        Tham số: (không)
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        if self.is_running:
            return
        folder = self.folder_path.get().strip()
        if not folder:
            self.ui_message("warning", "Thiếu thư mục", "Vui lòng chọn thư mục ảnh trước.")
            return

        if self.cache_enabled_var.get() and self.delete_after_var.get():
            self.ui_status("Lưu ý: Cache ảnh đang bật, KHÔNG nên xoá file trên Gemini sau phân tích.")

        self.clear_results()
        self.ui_status("Đang nạp lại ảnh từ thư mục đã chọn...")
        self._load_files(folder)
        if len(self.results) == 0:
            return
        prompt = self.prompt_text.get("1.0", "end").strip()
        if not prompt and self._load_prompt_from_file(silent=True):
            prompt = self.prompt_text.get("1.0", "end").strip()
        if not prompt:
            self.ui_message("warning", "Thiếu prompt", "Vui lòng nhập hoặc nạp PROMPT.txt trước khi chạy.")
            return
        api_key = self.api_key_var.get().strip() or os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            self.ui_message("warning", "Thiếu API key", "Vui lòng nhập API key hoặc đặt biến môi trường GOOGLE_API_KEY.")
            return
        try:
            genai.configure(api_key=api_key)
        except Exception as e:
            self.ui_message("error", "Gemini", f"Lỗi cấu hình API: {e}")
            return

        for i, r in enumerate(self.results):
            r["status"] = "Chưa xử lý"
            r["text"] = ""
            self._update_tree_row(i, r["status"])
        self.combined_report_text = ""
        self.ui_progress(0)
        self.ui_detail_replace("Đang chuẩn bị phân tích...")

        self.stop_flag = False
        self.is_running = True
        self.stop_btn.configure(state="normal")
        self.export_btn.configure(state="disabled")

        cfg = self._snapshot_config()
        t = threading.Thread(
            target=worker.run_analysis_worker,
            args=(self, prompt, self.model_var.get(), cfg),
            daemon=True
        )
        t.start()

    def stop_analysis(self):
        """
        Mục đích: Dừng quy trình đang chạy một cách an toàn (đặt cờ, giải phóng tài nguyên, cập nhật UI).
        Tham số: (không)
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        if self.is_running:
            self.stop_flag = True
            self.ui_status("Đang dừng sau khi hoàn tất tác vụ hiện tại...")

    '''
    def _load_upload_cache(self) -> dict:  # removed; use uploader.UploadCache.load()
        """
        Mục đích: Xử lý upload, gọi Gemini để phân tích bộ ảnh, gom kết quả.
        Tham số: (không)
        Trả về: dict
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        raise RuntimeError('removed: use uploader.UploadCache.load()')

    def _save_upload_cache(self, cache: dict):  # removed; use uploader.UploadCache.save()
        """
        Mục đích: Xử lý upload, gọi Gemini để phân tích bộ ảnh, gom kết quả.
        Tham số:
          - cache: dict — (tự suy luận theo ngữ cảnh sử dụng).
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        raise RuntimeError('removed: use uploader.UploadCache.save(cache)')

    def _file_sig(self, path: str) -> str:  # removed; use uploader.UploadCache.file_sig()
        """
        Mục đích: Làm việc với file/thư mục (chọn, nạp, xem trước, xoá, cập nhật danh sách).
        Tham số:
          - path: str — (tự suy luận theo ngữ cảnh sử dụng).
        Trả về: str
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        raise RuntimeError('removed: use uploader.UploadCache.file_sig(path)')

    def _cache_lookup(self, cache: dict, path: str) -> str:  # removed; use uploader.UploadCache.lookup()
        """
        Mục đích: Đọc/ghi cấu hình workspace, cache upload và các trạng thái phiên làm việc.
        Tham số:
          - cache: dict — (tự suy luận theo ngữ cảnh sử dụng).
          - path: str — (tự suy luận theo ngữ cảnh sử dụng).
        Trả về: str
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        raise RuntimeError('removed: use uploader.UploadCache.lookup(cache, path)')

    def _cache_put(self, cache: dict, path: str, remote_name: str):  # removed; use uploader.UploadCache.put()
        """
        Mục đích: Đọc/ghi cấu hình workspace, cache upload và các trạng thái phiên làm việc.
        Tham số:
          - cache: dict — (tự suy luận theo ngữ cảnh sử dụng).
          - path: str — (tự suy luận theo ngữ cảnh sử dụng).
          - remote_name: str — (tự suy luận theo ngữ cảnh sử dụng).
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        raise RuntimeError('removed: use uploader.UploadCache.put(cache, path, remote_name)')

    def _prepare_image_for_upload(self, path: str) -> str:  # removed; use uploader.prepare_image()
        """
        Mục đích: Xử lý upload, gọi Gemini để phân tích bộ ảnh, gom kết quả.
        Tham số:
          - path: str — (tự suy luận theo ngữ cảnh sử dụng).
        Trả về: str
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        raise RuntimeError('removed: use uploader.prepare_image(path, optimize=..., app_dir=APP_DIR)')

    def _prepare_image_for_upload_cfg(self, path: str, optimize: bool) -> str:  # removed; use uploader.prepare_image()
        """
        Mục đích: Xử lý upload, gọi Gemini để phân tích bộ ảnh, gom kết quả.
        Tham số:
          - path: str — (tự suy luận theo ngữ cảnh sử dụng).
          - optimize: bool — (tự suy luận theo ngữ cảnh sử dụng).
        Trả về: str
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        raise RuntimeError('removed: use uploader.prepare_image(path, optimize=..., app_dir=APP_DIR)')

    '''
    def _parse_ctx_json_files(self, max_n=5, folder: str | None = None):
        """
        Mục đích: Làm việc với file/thư mục (chọn, nạp, xem trước, xoá, cập nhật danh sách).
        Tham số:
          - max_n — (tự suy luận theo ngữ cảnh sử dụng).
          - folder: str | None — (tự suy luận theo ngữ cảnh sử dụng).
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        d = self._get_reports_dir(folder_override=folder)
        if not d:
            return []
        files = sorted(d.glob("ctx_*.json"), reverse=True)[: max(1, int(max_n))]
        out = []
        for p in files:
            try:
                out.append(json.loads(p.read_text(encoding="utf-8")))
            except Exception:
                continue
        return out

    def _summarize_checklist_trend(self, ctx_items):
        """
        Mục đích: Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
        Tham số:
          - ctx_items — (tự suy luận theo ngữ cảnh sử dụng).
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        if not ctx_items:
            return {"trend": "unknown", "enough_ratio": None}
        order = ["A", "B", "C", "D", "E", "F"]
        scores = {"ĐỦ": 2, "CHỜ": 1, "SAI": 0}
        seq = []
        enough_cnt = 0
        total = 0
        for it in ctx_items:
            setup = it.get("blocks") or []
            setup_json = None
            for blk in setup:
                try:
                    obj = json.loads(blk)
                    if isinstance(obj, dict) and "setup_status" in obj:
                        setup_json = obj
                        break
                except Exception:
                    pass
            if not setup_json:
                continue
            st = setup_json.get("setup_status", {})
            val = sum(scores.get(st.get(k, ""), 0) for k in order)
            seq.append(val)
            concl = setup_json.get("conclusions", "")
            if isinstance(concl, str) and "ĐỦ" in concl.upper():
                enough_cnt += 1
            total += 1
        if len(seq) < 2:
            return {"trend": "flat", "enough_ratio": (enough_cnt / total if total else None)}
        delta = seq[-1] - seq[0]
        trend = "improving" if delta > 0 else ("deteriorating" if delta < 0 else "flat")
        return {"trend": trend, "enough_ratio": (enough_cnt / total if total else None)}

    def _images_tf_map(self):
        """
        Mục đích: Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
        Tham số: (không)
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        names = [Path(r.get("path")).name for r in self.results if r.get("path")]
        return context_builder.images_tf_map(names, self._detect_timeframe_from_name)

    def _folder_signature(self):
        """
        Mục đích: Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
        Tham số: (không)
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        names = [Path(r.get("path")).name for r in self.results if r.get("path")]
        return context_builder.folder_signature(names)

    def compose_context(self, cfg: RunConfig, budget_chars=1800):
        """
        Mục đích: Xây dựng/ngắt ghép ngữ cảnh (text/JSON) để truyền vào prompt của Gemini.
        Tham số:
          - cfg: RunConfig — (tự suy luận theo ngữ cảnh sử dụng).
          - budget_chars — (tự suy luận theo ngữ cảnh sử dụng).
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        return context_builder.compose_context(self, cfg, budget_chars)

    def _quick_be_trailing_sweep(self, cfg: RunConfig):
        """
        Mục đích: Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
        Tham số:
          - cfg: RunConfig — (tự suy luận theo ngữ cảnh sử dụng).
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        try:
            if not (cfg.mt5_enabled and cfg.auto_trade_enabled):
                return
            ctx = self._mt5_build_context(plan=None, cfg=cfg) or ""
            if not ctx:
                return
            data = json.loads(ctx).get("MT5_DATA", {})
            if data:
                auto_trade.mt5_manage_be_trailing(self,data, cfg)
        except Exception:
            pass

    def _auto_save_json_from_report(self, text: str, cfg: RunConfig, names: list[str], context_obj: dict):
        """
        Mục đích: Ghi/Xuất dữ liệu (báo cáo .md, JSON tóm tắt, cache...).
        Tham số:
          - text: str — (tự suy luận theo ngữ cảnh sử dụng).
          - cfg: RunConfig — (tự suy luận theo ngữ cảnh sử dụng).
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        d = self._get_reports_dir(cfg.folder)
        if not d:
            return
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        found = []
        for m in re.finditer(r"\{[\s\S]*?\}", text):
            j = m.group(0).strip()
            try:
                json.loads(j)
                found.append(j)
            except Exception:
                continue
        payload = {}
        if found:
            payload["blocks"] = found
        lines, sig, high = self._extract_seven_lines(text)
        if lines:
            payload["seven_lines"] = lines
            payload["signature"] = sig
            payload["high_prob"] = bool(high)
        
        payload["cycle"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        payload["images_tf_map"] = self._images_tf_map(names)

        out = d / f"ctx_{ts}.json"
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        # --- Log proposed trade for backtesting ---
        try:
            setup = self._parse_setup_from_report(text)
            if setup and setup.get("direction") and setup.get("entry"):
                # Extract context snapshot for logging
                ctx_snapshot = {}
                if context_obj:
                    inner_ctx = context_obj.get("CONTEXT_COMPOSED", {})
                    ctx_snapshot = {
                        "session": inner_ctx.get("session"),
                        "trend_checklist": inner_ctx.get("trend_checklist", {}).get("trend"),
                        "volatility_regime": (inner_ctx.get("environment_flags") or {}).get("volatility_regime"),
                        "trend_regime": (inner_ctx.get("environment_flags") or {}).get("trend_regime"),
                    }

                trade_log_payload = {
                    "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                    "symbol": cfg.mt5_symbol,
                    "report_file": out.name,
                    "setup": setup,
                    "context_snapshot": ctx_snapshot
                }
                self._log_proposed_trade(trade_log_payload, folder_override=cfg.folder)
        except Exception:
            pass # Silently fail if parsing/logging fails

        return out

    def _log_proposed_trade(self, data: dict, folder_override: str | None = None):
        try:
            d = self._get_reports_dir(folder_override=folder_override)
            if not d:
                return

            p = d / "proposed_trades.jsonl"
            line = (json.dumps(data, ensure_ascii=False, separators=(',', ':')) + "\n").encode("utf-8")

            p.parent.mkdir(parents=True, exist_ok=True)

            with self._proposed_trade_log_lock:
                need_leading_newline = False
                if p.exists():
                    try:
                        sz = p.stat().st_size
                        if sz > 0:
                            with open(p, "rb") as fr:
                                fr.seek(-1, os.SEEK_END)
                                need_leading_newline = (fr.read(1) != b"\n")
                    except Exception:
                        need_leading_newline = False
                
                with open(p, "ab") as f:
                    if need_leading_newline:
                        f.write(b"\n")
                    f.write(line)
                    f.flush()
                    try:
                        os.fsync(f.fileno())
                    except Exception:
                        pass
        except Exception:
            pass

    def _log_vector_data(self, data: dict, folder_override: str | None = None):
        try:
            d = self._get_reports_dir(folder_override=folder_override)
            if not d:
                return

            p = d / "vector_database.jsonl"
            line = (json.dumps(data, ensure_ascii=False, separators=(',', ':')) + "\n").encode("utf-8")

            p.parent.mkdir(parents=True, exist_ok=True)

            with self._vector_db_lock:
                need_leading_newline = False
                if p.exists():
                    try:
                        sz = p.stat().st_size
                        if sz > 0:
                            with open(p, "rb") as fr:
                                fr.seek(-1, os.SEEK_END)
                                need_leading_newline = (fr.read(1) != b"\n")
                    except Exception:
                        need_leading_newline = False
                
                with open(p, "ab") as f:
                    if need_leading_newline:
                        f.write(b"\n")
                    f.write(line)
                    f.flush()
                    try:
                        os.fsync(f.fileno())
                    except Exception:
                        pass
        except Exception:
            pass

    def _pick_ca_bundle(self):
        """
        Mục đích: Làm việc với file/thư mục (chọn, nạp, xem trước, xoá, cập nhật danh sách).
        Tham số: (không)
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        p = filedialog.askopenfilename(
            title="Chọn CA bundle (.pem/.crt)",
            filetypes=[("PEM/CRT", "*.pem *.crt *.cer"), ("Tất cả", "*.*")],
        )
        if p:
            self.telegram_ca_path_var.set(p)

    def _build_ssl_context(self) -> ssl.SSLContext:
        """
        Mục đích: Khởi tạo SSLContext (UI-based) qua helper hợp nhất.
        """
        cafile = (self.telegram_ca_path_var.get() or "").strip() or None
        skip = bool(self.telegram_skip_verify_var.get())
        return build_ssl_context(cafile, skip)
    def _create_ssl_context(self, cafile: str | None, skip_verify: bool) -> ssl.SSLContext:
        """
        Mục đích: Tạo SSLContext hợp nhất (dùng chung cho Telegram/FF), giảm trùng lặp.
        Tham số:
        - cafile: str | None — đường dẫn CA file nếu có.
        - skip_verify: bool — bỏ kiểm chứng chứng chỉ.
        Trả về: ssl.SSLContext
        """
        return build_ssl_context(cafile, skip_verify)

    def _telegram_api_call(self, method: str, params: dict, use_get_fallback: bool = True, timeout: int = 15):
        """
        Mục đích: Gửi/thử thông báo Telegram, xử lý chứng chỉ và kết quả phản hồi.
        Tham số:
          - method: str — (tự suy luận theo ngữ cảnh sử dụng).
          - params: dict — (tự suy luận theo ngữ cảnh sử dụng).
          - use_get_fallback: bool — (tự suy luận theo ngữ cảnh sử dụng).
          - timeout: int — (tự suy luận theo ngữ cảnh sử dụng).
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        client = TelegramClient(
            token=(self.telegram_token_var.get() or "").strip(),
            chat_id=(self.telegram_chat_id_var.get() or "").strip() or None,
            ca_path=(self.telegram_ca_path_var.get() or "").strip() or None,
            skip_verify=bool(self.telegram_skip_verify_var.get()),
            timeout=timeout,
        )
        return client.api_call(method, params, use_get_fallback=use_get_fallback)

    def _build_telegram_message(self, seven_lines, saved_report_path, folder_override: str | None = None):
        """
        Mục đích: Khởi tạo/cấu hình thành phần giao diện hoặc cấu trúc dữ liệu nội bộ.
        Tham số:
          - seven_lines — (tự suy luận theo ngữ cảnh sử dụng).
          - saved_report_path — (tự suy luận theo ngữ cảnh sử dụng).
          - folder_override: str | None — (tự suy luận theo ngữ cảnh sử dụng).
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        folder = folder_override if folder_override is not None else self.folder_path.get().strip()

        MAX_PER_LINE = 220
        cleaned = []
        for ln in seven_lines:
            ln = re.sub(r"\s+", " ", (ln or "")).strip()
            if len(ln) > MAX_PER_LINE:
                ln = ln[: MAX_PER_LINE - 1] + "…"

            cleaned.append(_tg_html_escape(ln))

        folder_safe = _tg_html_escape(folder)
        saved_safe = _tg_html_escape(saved_report_path.name) if saved_report_path else None
        ts_safe = _tg_html_escape(ts)

        msg = (
            "🔔 <b>Setup xác suất cao</b>\n"
            f"⏱ {ts_safe}\n"
            f"📂 {folder_safe}\n\n"
            + "\n".join(cleaned)
            + (f"\n\n(Đã lưu: {saved_safe})" if saved_safe else "")
        )

        try:
            rep = self._get_reports_dir(folder_override=folder_override)
            (rep / "telegram_last.txt").write_text(msg, encoding="utf-8")
        except Exception:
            pass
        return msg

    def _build_ssl_context_from_cfg(self, cfg: RunConfig) -> ssl.SSLContext:
        """
        Mục đích: Khởi tạo/cấu hình thành phần giao diện hoặc cấu trúc dữ liệu nội bộ.
        Tham số:
          - cfg: RunConfig — (tự suy luận theo ngữ cảnh sử dụng).
        Trả về: ssl.SSLContext
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        cafile = cfg.telegram_ca_path or None
        skip = bool(getattr(cfg, "telegram_skip_verify", False))
        return build_ssl_context(cafile, skip)

    def _telegram_api_call_from_cfg(self, cfg: RunConfig, method: str, params: dict, timeout: int = 15):
        """
        Mục đích: Gửi/thử thông báo Telegram, xử lý chứng chỉ và kết quả phản hồi.
        Tham số:
          - cfg: RunConfig — (tự suy luận theo ngữ cảnh sử dụng).
          - method: str — (tự suy luận theo ngữ cảnh sử dụng).
          - params: dict — (tự suy luận theo ngữ cảnh sử dụng).
          - timeout: int — (tự suy luận theo ngữ cảnh sử dụng).
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        client = TelegramClient.from_config(cfg, timeout=timeout)
        return client.api_call(method, params)

    def _send_telegram_message_from_cfg(self, text: str, cfg: RunConfig) -> bool:
        """
        Mục đích: Gửi/thử thông báo Telegram, xử lý chứng chỉ và kết quả phản hồi.
        Tham số:
          - text: str — (tự suy luận theo ngữ cảnh sử dụng).
          - cfg: RunConfig — (tự suy luận theo ngữ cảnh sử dụng).
        Trả về: bool
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        if not cfg.telegram_enabled:
            return False
        chat_id = cfg.telegram_chat_id
        if not chat_id:
            self.ui_status("Telegram: thiếu Chat ID.")
            return False
        max_len = 3900
        if len(text) > max_len:
            text = text[:max_len] + "\n… (đã rút gọn)"
        params = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
        ok, payload = self._telegram_api_call_from_cfg(cfg, "sendMessage", params)
        if not ok:
            desc = payload.get("description") or payload.get("body") or payload.get("error", "unknown")
            self.ui_status(f"Telegram lỗi: {desc}")
            self.ui_message("error", "Telegram", f"Gửi thất bại:\n{desc}")
        else:
            self.ui_status("Đã gửi Telegram.")
        return ok

    def _send_telegram_message_from_cfg2(self, text: str, cfg: RunConfig) -> bool:
        """
        Gửi Telegram dùng TelegramClient (module), kèm phản hồi UI.
        """
        if not cfg.telegram_enabled:
            return False
        client = TelegramClient.from_config(cfg)
        ok, payload = client.send_message(text)
        if not ok:
            desc = payload.get("description") or payload.get("body") or payload.get("error", "unknown")
            self.ui_status(f"Telegram lỗi: {desc}")
            self.ui_message("error", "Telegram", f"Gửi thất bại:\n{desc}")
        else:
            self.ui_status("Đã gửi Telegram.")
        return ok

    def _send_telegram_message(self, text: str) -> bool:
        """
        Mục đích: Gửi/thử thông báo Telegram, xử lý chứng chỉ và kết quả phản hồi.
        Tham số:
          - text: str — (tự suy luận theo ngữ cảnh sử dụng).
        Trả về: bool
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        if not self.telegram_enabled_var.get():
            return False
        chat_id = self.telegram_chat_id_var.get().strip()
        if not chat_id:
            self.ui_status("Telegram: thiếu Chat ID.")
            return False
        max_len = 3900
        if len(text) > max_len:
            text = text[:max_len] + "\n… (đã rút gọn)"
        params = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
        client = TelegramClient(
            token=(self.telegram_token_var.get() or "").strip(),
            chat_id=(self.telegram_chat_id_var.get() or "").strip() or None,
            ca_path=(self.telegram_ca_path_var.get() or "").strip() or None,
            skip_verify=bool(self.telegram_skip_verify_var.get()),
        )
        ok, payload = client.send_message(text)
        if not ok:
            desc = payload.get("description") or payload.get("body") or payload.get("error", "unknown")
            self.ui_status(f"Telegram lỗi: {desc}")
            self.ui_message("error", "Telegram", f"Gửi thất bại:\n{desc}")
        else:
            self.ui_status("Đã gửi Telegram.")

        return ok

    def _telegram_test(self):
        """
        Mục đích: Gửi/thử thông báo Telegram, xử lý chứng chỉ và kết quả phản hồi.
        Tham số: (không)
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        if not self.telegram_enabled_var.get():
            self.ui_message("warning", "Telegram", "Chưa bật Telegram.")
            return
        token = self.telegram_token_var.get().strip()
        chat_id = self.telegram_chat_id_var.get().strip()
        if not token or not chat_id:
            self.ui_message("warning", "Telegram", "Hãy nhập Bot Token và Chat ID.")
            return
        client = TelegramClient(
            token=token,
            chat_id=chat_id,
            ca_path=(self.telegram_ca_path_var.get() or "").strip() or None,
            skip_verify=bool(self.telegram_skip_verify_var.get()),
        )
        ok, p = client.api_call("getMe", {}, use_get_fallback=False)
        if not ok:
            desc = p.get("description") or p.get("body") or p.get("error", "unknown")
            self.ui_message("error", "Telegram", f"getMe lỗi — kiểm tra Token:\n{desc}")
            return
        ok, p = client.api_call("getChat", {"chat_id": chat_id}, use_get_fallback=False)
        if not ok:
            desc = p.get("description") or p.get("body") or p.get("error", "unknown")
            tip = "\n\nGợi ý:\n• Nếu chat cá nhân: phải nhắn /start cho bot trước.\n• Nếu nhóm: chat_id là số âm và bot phải được thêm."
            self.ui_message("error", "Telegram", f"getChat lỗi — kiểm tra Chat ID:{tip}\n\nChi tiết:\n{desc}")
            return
        ok, _ = client.send_message("🔔 Test từ Gemini Analyzer: kết nối thành công!")
        if ok:
            self.ui_message("info", "Telegram", "Đã gửi thử thành công.")

    def _extract_seven_lines(self, combined_text: str):
        """
        Mục đích: Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
        Tham số:
          - combined_text: str — (tự suy luận theo ngữ cảnh sử dụng).
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        return report_parser.extract_seven_lines(combined_text)
        lines = [ln.strip() for ln in combined_text.strip().splitlines() if ln.strip()]
        start_idx = None
        for i, ln in enumerate(lines[:20]):
            if re.match(r"^1[\.\)\-–:]?\s*", ln) or ("Lệnh:" in ln and ln.lstrip().startswith("1")):
                start_idx = i
                break
            if "Lệnh:" in ln:
                start_idx = i
                break
        if start_idx is None:
            return None, None, False
        block = []
        j = start_idx
        while j < len(lines) and len(block) < 10:
            block.append(lines[j])
            j += 1
        picked = []
        wanted = ["Lệnh:", "Entry", "SL", "TP1", "TP2", "Lý do", "Lưu ý"]
        used = set()
        for key in wanted:
            found = None
            for ln in block:
                if ln in used:
                    continue
                if key.lower().split(":")[0] in ln.lower():
                    found = ln
                    break
            if found is None:
                idx = len(picked) + 1
                for ln in block:
                    if re.match(rf"^{idx}\s*[\.\)\-–:]", ln):
                        found = ln
                        break
            picked.append(found or f"{len(picked)+1}. (thiếu)")
            used.add(found)
        l1 = picked[0].lower()
        high = ("lệnh:" in l1) and (("mua" in l1) or ("bán" in l1)) and ("không có setup" not in l1) and ("theo dõi lệnh hiện tại" not in l1)
        sig = hashlib.sha1(("|".join(picked)).encode("utf-8")).hexdigest()
        return picked, sig, high

    def _maybe_notify_telegram(self, combined_text: str, saved_report_path: Path, cfg: RunConfig):
        """
        Mục đích: Gửi/thử thông báo Telegram, xử lý chứng chỉ và kết quả phản hồi.
        Tham số:
          - combined_text: str — (tự suy luận theo ngữ cảnh sử dụng).
          - saved_report_path: Path — (tự suy luận theo ngữ cảnh sử dụng).
          - cfg: RunConfig — (tự suy luận theo ngữ cảnh sử dụng).
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        if not cfg.telegram_enabled:
            return
        lines, sig, high = self._extract_seven_lines(combined_text)
        if not high or not lines or not sig:
            return
        if sig == self._last_telegram_signature:
            return
        self._last_telegram_signature = sig
        msg = TelegramClient.build_message(lines, saved_report_path, folder=cfg.folder)
        self._send_telegram_message_from_cfg2(msg, cfg)

    def _find_balanced_json_after(self, text: str, start_idx: int):
        """
        Mục đích: Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
        Tham số:
          - text: str — (tự suy luận theo ngữ cảnh sử dụng).
          - start_idx: int — (tự suy luận theo ngữ cảnh sử dụng).
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        return report_parser.find_balanced_json_after(text, start_idx)
        depth, i = 0, start_idx
        while i < len(text):
            ch = text[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start_idx:i+1], i+1
            i += 1
        return None, None

    def _extract_json_block_prefer(self, text: str):
        """
        Mục đích: Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
        Tham số:
          - text: str — (tự suy luận theo ngữ cảnh sử dụng).
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        return report_parser.extract_json_block_prefer(text)

        fence = re.findall(r"```json\s*(\{[\s\S]*?\})\s*```", text, flags=re.IGNORECASE)
        for blob in fence:
            try:
                return json.loads(blob)
            except Exception:
                pass

        keywords = ["CHECKLIST_JSON", "EXTRACT_JSON", "setup", "trade", "signal"]
        lowered = text.lower()
        for kw in keywords:
            idx = lowered.find(kw.lower())
            if idx >= 0:
                brace = text.find("{", idx)
                if brace >= 0:
                    js, _ = self._find_balanced_json_after(text, brace)
                    if js:
                        try:
                            return json.loads(js)
                        except Exception:
                            pass

        first_brace = text.find("{")
        while first_brace >= 0:
            js, nxt = self._find_balanced_json_after(text, first_brace)
            if js:
                try:
                    import json as _json
                    return _json.loads(js)
                except Exception:
                    pass
                first_brace = text.find("{", nxt if nxt else first_brace + 1)
            else:
                break
        return None

    def _coerce_setup_from_json(self, obj):
        """
        Mục đích: Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
        Tham số:
          - obj — (tự suy luận theo ngữ cảnh sử dụng).
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        return report_parser.coerce_setup_from_json(obj)
        if obj is None:
            return None

        candidates = []
        if isinstance(obj, dict):
            candidates.append(obj)
            for k in ("CHECKLIST_JSON", "EXTRACT_JSON", "setup", "trade", "signal"):
                v = obj.get(k)
                if isinstance(v, dict):
                    candidates.append(v)

        def _num(x):
            """
            Mục đích: Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
            Tham số:
              - x — (tự suy luận theo ngữ cảnh sử dụng).
            Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
            Ghi chú:
              - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
            """
            if x is None:
                return None
            if isinstance(x, (int, float)) and math.isfinite(x):
                return float(x)
            if isinstance(x, str):
                xs = x.strip().replace(",", "")
                try:
                    return float(xs)
                except Exception:
                    return None
            return None

        def _dir(x):
            """
            Mục đích: Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
            Tham số:
              - x — (tự suy luận theo ngữ cảnh sử dụng).
            Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
            Ghi chú:
              - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
            """
            if not x:
                return None
            s = str(x).strip().lower()

            if s in ("long", "buy", "mua", "bull", "bullish"):
                return "long"
            if s in ("short", "sell", "bán", "ban", "bear", "bearish"):
                return "short"
            return None

        for c in candidates:
            d = {
                "direction": _dir(c.get("direction") or c.get("dir") or c.get("side")),
                "entry": _num(c.get("entry") or c.get("price") or c.get("ep")),
                "sl":    _num(c.get("sl")    or c.get("stop")  or c.get("stop_loss")),
                "tp1":   _num(c.get("tp1")   or c.get("tp_1")  or c.get("take_profit_1") or c.get("tp")),
                "tp2":   _num(c.get("tp2")   or c.get("tp_2")  or c.get("take_profit_2")),
            }

            if d["tp1"] is None and d["tp2"] is not None:
                d["tp1"] = d["tp2"]
            if d["tp1"] is not None and d["sl"] is not None and d["entry"] is not None and d["direction"] in ("long","short"):
                return d
        return None
    def _parse_float(self, s: str):
        """
        Mục đích: Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
        Tham số:
          - s: str — (tự suy luận theo ngữ cảnh sử dụng).
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        return report_parser.parse_float(s)

    def _parse_direction_from_line1(self, line1: str):
        """
        Mục đích: Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
        Tham số:
          - line1: str — (tự suy luận theo ngữ cảnh sử dụng).
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        return report_parser.parse_direction_from_line1(line1)

    def _parse_setup_from_report(self, text: str):
        """
        Mục đích: Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
        Tham số:
          - text: str — (tự suy luận theo ngữ cảnh sử dụng).
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        return report_parser.parse_setup_from_report(text)
        out = {
            "direction": None, "entry": None, "sl": None, "tp1": None, "tp2": None,
            "bias_h1": None, "enough": False
        }
        if not text:
            return out

        obj = None
        if hasattr(self, "_extract_json_block_prefer"):
            obj = self._extract_json_block_prefer(text)

        if obj is None:
            for m in re.finditer(r"\{[\s\S]*?\}", text):
                try:
                    obj = json.loads(m.group(0)); break
                except Exception:
                    pass

        def _num(x):
            """
            Mục đích: Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
            Tham số:
              - x — (tự suy luận theo ngữ cảnh sử dụng).
            Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
            Ghi chú:
              - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
            """
            if x is None: return None
            if isinstance(x, (int, float)) and math.isfinite(x): return float(x)
            if isinstance(x, str):
                xs = x.strip().replace(",", "")
                try: return float(xs)
                except Exception: return None
            return None

        def _dir(x):
            """
            Mục đích: Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
            Tham số:
              - x — (tự suy luận theo ngữ cảnh sử dụng).
            Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
            Ghi chú:
              - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
            """
            if not x: return None
            s = str(x).strip().lower()
            if s in ("long","buy","mua","bull","bullish"): return "long"
            if s in ("short","sell","bán","ban","bear","bearish"): return "short"
            return None

        def _pick_from_json(root):
            """
            Mục đích: Làm việc với file/thư mục (chọn, nạp, xem trước, xoá, cập nhật danh sách).
            Tham số:
              - root — (tự suy luận theo ngữ cảnh sử dụng).
            Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
            Ghi chú:
              - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
            """
            if not isinstance(root, dict): return None

            chk = root.get("CHECKLIST_JSON") or root.get("checklist") or root
            if isinstance(chk, dict) and ("setup_status" in chk or "conclusions" in chk):
                out["bias_h1"] = (chk.get("bias_H1") or chk.get("bias_h1") or "").lower() or out["bias_h1"]
                concl = (chk.get("conclusions") or "").upper()
                out["enough"] = out["enough"] or ("ĐỦ" in concl or "DU" in concl)

            cands = []
            for k in ("proposed_plan","plan","trade","signal","setup"):
                if isinstance(root.get(k), dict):
                    cands.append(root[k])

            for v in root.values():
                if isinstance(v, dict):
                    for k in ("proposed_plan","plan","trade","signal","setup"):
                        if isinstance(v.get(k), dict):
                            cands.append(v[k])
            for c in cands:
                d = {
                    "direction": _dir(c.get("direction") or c.get("dir") or c.get("side")),
                    "entry": _num(c.get("entry") or c.get("price") or c.get("ep")),
                    "sl":    _num(c.get("sl")    or c.get("stop")  or c.get("stop_loss")),
                    "tp1":   _num(c.get("tp1")   or c.get("tp_1")  or c.get("take_profit_1") or c.get("tp")),
                    "tp2":   _num(c.get("tp2")   or c.get("tp_2")  or c.get("take_profit_2")),
                }
                if d["tp1"] is None and d["tp2"] is not None:
                    d["tp1"] = d["tp2"]
                if d["direction"] in ("long","short") and all(d[k] is not None for k in ("entry","sl","tp1")):
                    return d
            return None

        plan = _pick_from_json(obj) if obj else None
        if plan:
            out.update(plan)
            return out

        lines_sig = None
        try:
            lines, lines_sig, _ = self._extract_seven_lines(text)
        except Exception:
            lines = None
        if lines:
            out["direction"] = self._parse_direction_from_line1(lines[0])

            def _lastnum(s):
                """
                Mục đích: Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
                Tham số:
                  - s — (tự suy luận theo ngữ cảnh sử dụng).
                Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
                Ghi chú:
                  - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
                """
                if not s: return None
                s = re.sub(r"^\s*\d+\s*[\.\)\-–:]\s*", "", s.strip())
                nums = re.findall(r"[-+]?\d+(?:\.\d+)?", s.replace(",", ""))
                return float(nums[-1]) if nums else None
            out["entry"] = _lastnum(lines[1] if len(lines)>1 else None)
            out["sl"]    = _lastnum(lines[2] if len(lines)>2 else None)
            out["tp1"]   = _lastnum(lines[3] if len(lines)>3 else None)
            out["tp2"]   = _lastnum(lines[4] if len(lines)>4 else None)
        return out

    def _order_send_safe(self, req, retry=2):
        """
        Mục đích: Tự động hóa xử lý lệnh: tính khối lượng, đặt/huỷ lệnh, trailing/BE, kiểm soát RR.
        Tham số:
          - req — (tự suy luận theo ngữ cảnh sử dụng).
          - retry — (tự suy luận theo ngữ cảnh sử dụng).
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        last = None
        for i in range(max(1, retry)):
            result = mt5.order_send(req)
            if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                return result
            last = result
            time.sleep(0.6)
        return last

    def _fill_priority(self, prefer: str):
        """
        Mục đích: Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
        Tham số:
          - prefer: str — (tự suy luận theo ngữ cảnh sử dụng).
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        try:
            IOC = mt5.ORDER_FILLING_IOC
            FOK = mt5.ORDER_FILLING_FOK
            RET = mt5.ORDER_FILLING_RETURN
        except Exception:

            IOC = 1; FOK = 0; RET = 2
        return ([IOC, FOK, RET] if prefer == "market" else [FOK, IOC, RET])

    def _fill_name(self, val: int) -> str:
        """
        Mục đích: Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
        Tham số:
          - val: int — (tự suy luận theo ngữ cảnh sử dụng).
        Trả về: str
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        names = {
            getattr(mt5, "ORDER_FILLING_IOC", 1): "IOC",
            getattr(mt5, "ORDER_FILLING_FOK", 0): "FOK",
            getattr(mt5, "ORDER_FILLING_RETURN", 2): "RETURN",
        }
        return names.get(val, str(val))

    def _order_send_smart(self, req: dict, prefer: str = "market", retry_per_mode: int = 2):
        """
        Mục đích: Tự động hóa xử lý lệnh: tính khối lượng, đặt/huỷ lệnh, trailing/BE, kiểm soát RR.
        Tham số:
          - req: dict — (tự suy luận theo ngữ cảnh sử dụng).
          - prefer: str — (tự suy luận theo ngữ cảnh sử dụng).
          - retry_per_mode: int — (tự suy luận theo ngữ cảnh sử dụng).
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        last_res = None
        tried = []
        for fill in self._fill_priority(prefer):
            r = dict(req)
            r["type_filling"] = fill
            res = self._order_send_safe(r, retry=retry_per_mode)
            tried.append(self._fill_name(fill))

            if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                if len(tried) > 1:
                    self.ui_status(f"Order OK sau khi đổi filling → {tried[-1]}.")
                return res

            last_res = res

        cmt = getattr(last_res, "comment", "unknown") if last_res else "no result"
        self.ui_status(f"Order FAIL với các filling: {', '.join(tried)} — {cmt}")
        return last_res

    def _calc_rr(self, entry, sl, tp):
        """
        Mục đích: Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
        Tham số:
          - entry — (tự suy luận theo ngữ cảnh sử dụng).
          - sl — (tự suy luận theo ngữ cảnh sử dụng).
          - tp — (tự suy luận theo ngữ cảnh sử dụng).
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        try:
            risk = abs(entry - sl)
            reward = abs(tp - entry)
            return (reward / risk) if risk > 0 else None
        except Exception:
            return None

    def _allowed_session_now(self, mt5_ctx: dict, cfg: RunConfig) -> bool:
        """
        Mục đích: Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
        Tham số:
          - mt5_ctx: dict — (tự suy luận theo ngữ cảnh sử dụng).
          - cfg: RunConfig — (tự suy luận theo ngữ cảnh sử dụng).
        Trả về: bool
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        ss = (mt5_ctx.get("sessions_today") or {})
        now = datetime.now().strftime("%H:%M")
        ok = False
        def _in(r):
            """
            Mục đích: Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
            Tham số:
              - r — (tự suy luận theo ngữ cảnh sử dụng).
            Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
            Ghi chú:
              - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
            """
            return bool(r and r.get("start") and r.get("end") and r["start"] <= now < r["end"])
        if cfg.trade_allow_session_asia   and _in(ss.get("asia")): ok = True
        if cfg.trade_allow_session_london and _in(ss.get("london")): ok = True
        if cfg.trade_allow_session_ny     and ( _in(ss.get("newyork_pre")) or _in(ss.get("newyork_post")) ):
            ok = True

        if not (cfg.trade_allow_session_asia or cfg.trade_allow_session_london or cfg.trade_allow_session_ny):
            ok = True
        return ok

    def _open_path(self, path: Path):
        """
        Mục đích: Làm việc với file/thư mục (chọn, nạp, xem trước, xoá, cập nhật danh sách).
        Tham số:
          - path: Path — (tự suy luận theo ngữ cảnh sử dụng).
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        try:
            sysname = platform.system()
            if sysname == "Windows":
                os.startfile(str(path))
            elif sysname == "Darwin":
                subprocess.run(["open", str(path)], check=False)
            else:
                subprocess.run(["xdg-open", str(path)], check=False)
        except Exception as e:
            self.ui_message("error", "Mở tệp", str(e))

    def _near_key_levels_too_close(self, mt5_ctx: dict, min_pips: float, cp: float) -> bool:
        """
        Mục đích: Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
        Tham số:
          - mt5_ctx: dict — (tự suy luận theo ngữ cảnh sử dụng).
          - min_pips: float — (tự suy luận theo ngữ cảnh sử dụng).
          - cp: float — (tự suy luận theo ngữ cảnh sử dụng).
        Trả về: bool
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        try:
            lst = (mt5_ctx.get("key_levels_nearby") or [])
            for lv in lst:
                dist = float(lv.get("distance_pips") or 0.0)
                if dist and dist < float(min_pips):
                    return True
        except Exception:
            pass
        return False

    def _log_trade_decision(self, data: dict, folder_override: str | None = None):
        """
        Mục đích: Tự động hóa xử lý lệnh: tính khối lượng, đặt/huỷ lệnh, trailing/BE, kiểm soát RR.
        Tham số:
          - data: dict — (tự suy luận theo ngữ cảnh sử dụng).
          - folder_override: str | None — (tự suy luận theo ngữ cảnh sử dụng).
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        try:
            d = self._get_reports_dir(folder_override=folder_override)
            if not d:
                return

            p = d / f"trade_log_{datetime.now().strftime('%Y%m%d')}.jsonl"
            line = (json.dumps(data, ensure_ascii=False, separators=(',', ':')) + "\n").encode("utf-8")

            p.parent.mkdir(parents=True, exist_ok=True)

            with self._trade_log_lock:
                need_leading_newline = False
                if p.exists():
                    try:
                        sz = p.stat().st_size
                        if sz > 0:
                            with open(p, "rb") as fr:
                                fr.seek(-1, os.SEEK_END)
                                need_leading_newline = (fr.read(1) != b"\n")
                    except Exception:

                        need_leading_newline = False

                with open(p, "ab") as f:
                    if need_leading_newline:
                        f.write(b"\n")
                    f.write(line)
                    f.flush()
                    try:
                        os.fsync(f.fileno())
                    except Exception:
                        pass
        except Exception:

            pass

    def _load_last_trade_state(self):
        """
        Mục đích: Làm việc với file/thư mục (chọn, nạp, xem trước, xoá, cập nhật danh sách).
        Tham số: (không)
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        f = APP_DIR / "last_trade_state.json"
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_last_trade_state(self, state: dict):
        """
        Mục đích: Ghi/Xuất dữ liệu (báo cáo .md, JSON tóm tắt, cache...).
        Tham số:
          - state: dict — (tự suy luận theo ngữ cảnh sử dụng).
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        f = APP_DIR / "last_trade_state.json"
        try:
            f.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _maybe_delete(self, uploaded_file):
        """
        Mục đích: Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
        Tham số:
          - uploaded_file — (tự suy luận theo ngữ cảnh sử dụng).
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        try:
            genai.delete_file(uploaded_file.name)
        except Exception:
            pass

    def _update_progress(self, done_steps, total_steps):
        """
        Mục đích: Cập nhật UI theo cơ chế thread-safe (hàng đợi, status, progress, khu vực chi tiết).
        Tham số:
          - done_steps — (tự suy luận theo ngữ cảnh sử dụng).
          - total_steps — (tự suy luận theo ngữ cảnh sử dụng).
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        pct = (done_steps / max(total_steps, 1)) * 100.0
        self._enqueue(lambda: (self.progress_var.set(pct), self.status_var.set(f"Tiến độ: {pct:.1f}%")))

    def _update_tree_row(self, idx, status):
        """
        Mục đích: Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
        Tham số:
          - idx — (tự suy luận theo ngữ cảnh sử dụng).
          - status — (tự suy luận theo ngữ cảnh sử dụng).
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        def action():
            """
            Mục đích: Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
            Tham số: (không)
            Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
            Ghi chú:
              - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
            """
            iid = str(idx)
            if self.tree.exists(iid):
                vals = list(self.tree.item(iid, "values"))
                vals = [idx + 1, self.results[idx]["name"], status] if len(vals) < 3 else [vals[0], vals[1], status]
                self.tree.item(iid, values=vals)
        self._enqueue(action)

    def _finalize_done(self):

        """
        Mục đích: Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
        Tham số: (không)
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        try:
            self._log_trade_decision({
                "stage": "run-end",
                "t": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }, folder_override=(self.mt5_symbol_var.get().strip() or None))
        except Exception:
            pass

        self.is_running = False
        self.stop_flag = False
        self.stop_btn.configure(state="disabled")
        self.export_btn.configure(state="normal")
        self.ui_status("Đã hoàn tất phân tích toàn bộ thư mục.")
        self._schedule_next_autorun()

    def _finalize_stopped(self):
        """
        Mục đích: Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
        Tham số: (không)
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        self.is_running = False
        self.stop_flag = False
        self.stop_btn.configure(state="disabled")
        self.export_btn.configure(state="normal")
        self.ui_status("Đã dừng.")
        self._schedule_next_autorun()

    def _on_tree_select(self, _evt):
        """
        Mục đích: Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
        Tham số:
          - _evt — (tự suy luận theo ngữ cảnh sử dụng).
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        self.detail_text.delete("1.0", "end")
        if self.combined_report_text.strip():
            self.detail_text.insert("1.0", self.combined_report_text)
        else:
            self.detail_text.insert("1.0", "Chưa có báo cáo. Hãy bấm 'Bắt đầu'.")

    def export_markdown(self):
        """
        Mục đích: Ghi/Xuất dữ liệu (báo cáo .md, JSON tóm tắt, cache...).
        Tham số: (không)
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
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
            self.ui_message("info", "Thành công", f"Đã lưu: {out_path}")
        except Exception as e:
            self.ui_message("error", "Lỗi ghi file", str(e))

    def _auto_save_report(self, combined_text: str, cfg: RunConfig) -> Path:
        """
        Mục đích: Ghi/Xuất dữ liệu (báo cáo .md, JSON tóm tắt, cache...).
        Tham số:
          - combined_text: str — (tự suy luận theo ngữ cảnh sử dụng).
          - cfg: RunConfig — (tự suy luận theo ngữ cảnh sử dụng).
        Trả về: Path
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        d = self._get_reports_dir(cfg.folder)
        if not d:
            return None
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = d / f"report_{ts}.md"
        out.write_text(combined_text or "", encoding="utf-8")
        return out

    def clear_results(self):
        """
        Mục đích: Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
        Tham số: (không)
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        self.results.clear()
        self.combined_report_text = ""
        if hasattr(self, "tree"):
            self.tree.delete(*self.tree.get_children())
        if hasattr(self, "detail_text"):
            self.ui_detail_replace("Báo cáo tổng hợp sẽ hiển thị tại đây sau khi phân tích.")
        self.ui_progress(0)
        self.ui_status("Đã xoá kết quả khỏi giao diện.")

    def _enqueue(self, func):
        """
        Mục đích: Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
        Tham số:
          - func — (tự suy luận theo ngữ cảnh sử dụng).
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        self.ui_queue.put(func)

    def ui_status(self, text: str):

        """
        Mục đích: Cập nhật UI theo cơ chế thread-safe (hàng đợi, status, progress, khu vực chi tiết).
        Tham số:
          - text: str — (tự suy luận theo ngữ cảnh sử dụng).
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        self._enqueue(lambda: self.status_var.set(text))

    def ui_detail_replace(self, text: str):
        """
        Mục đích: Cập nhật UI theo cơ chế thread-safe (hàng đợi, status, progress, khu vực chi tiết).
        Tham số:
          - text: str — (tự suy luận theo ngữ cảnh sử dụng).
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        self._enqueue(lambda: (
            self.detail_text.config(state="normal"),
            self.detail_text.delete("1.0", "end"),
            self.detail_text.insert("1.0", text)
        ))

    def ui_message(self, kind: str, title: str, text: str, auto_close_ms: int = 60000, log: bool = True):
        """
        Mục đích: Cập nhật UI theo cơ chế thread-safe (hàng đợi, status, progress, khu vực chi tiết).
        Tham số:
          - kind: str — (tự suy luận theo ngữ cảnh sử dụng).
          - title: str — (tự suy luận theo ngữ cảnh sử dụng).
          - text: str — (tự suy luận theo ngữ cảnh sử dụng).
          - auto_close_ms: int — (tự suy luận theo ngữ cảnh sử dụng).
          - log: bool — (tự suy luận theo ngữ cảnh sử dụng).
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        def _show():

            """
            Mục đích: Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
            Tham số: (không)
            Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
            Ghi chú:
              - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
            """
            if log:
                try:
                    self._log_ui_message({"t": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                          "kind": kind, "title": title, "text": text})
                except Exception:
                    pass

            top = tk.Toplevel(self.root)
            try:
                top.transient(self.root)
            except Exception:
                pass
            top.resizable(False, False)
            top.title(title or {"info": "Thông báo", "warning": "Cảnh báo", "error": "Lỗi"}.get(kind, "Thông báo"))
            try:
                top.attributes("-topmost", True)
            except Exception:
                pass

            frm = ttk.Frame(top, padding=12)
            frm.pack(fill="both", expand=True)

            ttk.Label(frm, text=title or "", font=("TkDefaultFont", 10, "bold")).pack(anchor="w", pady=(0, 4))
            ttk.Label(frm, text=text or "", justify="left", wraplength=480).pack(anchor="w")
            ttk.Label(frm, text=f"Sẽ tự đóng trong {auto_close_ms//1000}s", foreground="#666").pack(anchor="w", pady=(8, 0))
            ttk.Button(frm, text="Đóng", command=top.destroy).pack(anchor="e", pady=(8, 0))

            try:
                top.update_idletasks()
                x = self.root.winfo_rootx() + self.root.winfo_width() - top.winfo_width() - 24
                y = self.root.winfo_rooty() + 24
                x = max(0, x); y = max(0, y)
                top.geometry(f"+{x}+{y}")

                def _drop_topmost():
                    """
                    Mục đích: Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
                    Tham số: (không)
                    Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
                    Ghi chú:
                      - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
                    """
                    try: top.attributes("-topmost", False)
                    except Exception: pass
                top.after(200, _drop_topmost)
            except Exception:
                pass

            def _safe_destroy():
                """
                Mục đích: Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
                Tham số: (không)
                Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
                Ghi chú:
                  - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
                """
                try: top.destroy()
                except Exception: pass
            top.after(max(1000, int(auto_close_ms)), _safe_destroy)

        self._enqueue(_show)

    def _log_ui_message(self, data: dict, folder_override: str | None = None):
        """
        Mục đích: Cập nhật UI theo cơ chế thread-safe (hàng đợi, status, progress, khu vực chi tiết).
        Tham số:
          - data: dict — (tự suy luận theo ngữ cảnh sử dụng).
          - folder_override: str | None — (tự suy luận theo ngữ cảnh sử dụng).
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        try:
            d = self._get_reports_dir(folder_override=folder_override)
            if not d:
                d = APP_DIR / "Logs"
                d.mkdir(parents=True, exist_ok=True)

            p = d / f"ui_log_{datetime.now().strftime('%Y%m%d')}.jsonl"
            line = (json.dumps(data, ensure_ascii=False, separators=(',', ':')) + "\n").encode("utf-8")

            p.parent.mkdir(parents=True, exist_ok=True)
            with self._ui_log_lock:
                need_leading_newline = False
                if p.exists():
                    try:
                        sz = p.stat().st_size
                        if sz > 0:
                            with open(p, "rb") as fr:
                                fr.seek(-1, os.SEEK_END)
                                need_leading_newline = (fr.read(1) != b"\n")
                    except Exception:
                        need_leading_newline = False
                with open(p, "ab") as f:
                    if need_leading_newline:
                        f.write(b"\n")
                    f.write(line)
                    f.flush()
                    try:
                        os.fsync(f.fileno())
                    except Exception:
                        pass
        except Exception:

            pass

    def ui_widget_state(self, widget, state: str):
        """
        Mục đích: Cập nhật UI theo cơ chế thread-safe (hàng đợi, status, progress, khu vực chi tiết).
        Tham số:
          - widget — (tự suy luận theo ngữ cảnh sử dụng).
          - state: str — (tự suy luận theo ngữ cảnh sử dụng).
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        self._enqueue(lambda: widget.configure(state=state))

    def ui_progress(self, pct: float, status: str = None):
        """
        Mục đích: Cập nhật UI theo cơ chế thread-safe (hàng đợi, status, progress, khu vực chi tiết).
        Tham số:
          - pct: float — (tự suy luận theo ngữ cảnh sử dụng).
          - status: str — (tự suy luận theo ngữ cảnh sử dụng).
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        def _act():
            """
            Mục đích: Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
            Tham số: (không)
            Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
            Ghi chú:
              - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
            """
            self.progress_var.set(pct)
            if status is not None:
                self.status_var.set(status)
        self._enqueue(_act)

    def ui_detail_clear(self, placeholder: str = None):
        """
        Mục đích: Cập nhật UI theo cơ chế thread-safe (hàng đợi, status, progress, khu vực chi tiết).
        Tham số:
          - placeholder: str — (tự suy luận theo ngữ cảnh sử dụng).
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        self._enqueue(lambda: (
            self.detail_text.delete("1.0", "end"),
            self.detail_text.insert("1.0", placeholder or "")
        ))

    def ui_refresh_history_list(self):
        """
        Mục đích: Cập nhật UI theo cơ chế thread-safe (hàng đợi, status, progress, khu vực chi tiết).
        Tham số: (không)
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        self._enqueue(self._refresh_history_list)

    def ui_refresh_json_list(self):
        """
        Mục đích: Cập nhật UI theo cơ chế thread-safe (hàng đợi, status, progress, khu vực chi tiết).
        Tham số: (không)
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        self._enqueue(self._refresh_json_list)

    def _poll_ui_queue(self):
        """
        Mục đích: Cập nhật UI theo cơ chế thread-safe (hàng đợi, status, progress, khu vực chi tiết).
        Tham số: (không)
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        try:
            while True:
                func = self.ui_queue.get_nowait()
                try:
                    func()
                except Exception:
                    pass
        except queue.Empty:
            pass
        self.root.after(80, self._poll_ui_queue)

    def ui_set_var(self, tk_var, value):
        """
        Mục đích: Cập nhật UI theo cơ chế thread-safe (hàng đợi, status, progress, khu vực chi tiết).
        Tham số:
          - tk_var — (tự suy luận theo ngữ cảnh sử dụng).
          - value — (tự suy luận theo ngữ cảnh sử dụng).
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        self._enqueue(lambda v=tk_var, val=value: v.set(val))

    def ui_set_text(self, widget, text: str):
        """
        Mục đích: Cập nhật UI theo cơ chế thread-safe (hàng đợi, status, progress, khu vực chi tiết).
        Tham số:
          - widget — (tự suy luận theo ngữ cảnh sử dụng).
          - text: str — (tự suy luận theo ngữ cảnh sử dụng).
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        self._enqueue(lambda w=widget, t=text: (
            w.config(state="normal"),
            w.delete("1.0", "end"),
            w.insert("1.0", t)
        ))

    def _refresh_history_list(self):
        """
        Mục đích: Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
        Tham số: (không)
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        if not hasattr(self, "history_list"):
            return
        self.history_list.delete(0, "end")
        d = self._get_reports_dir()
        files = sorted(d.glob("report_*.md"), reverse=True) if d else []
        self._history_files = list(files)
        for p in files:
            self.history_list.insert("end", p.name)

    def _preview_history_selected(self):
        """
        Mục đích: Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
        Tham số: (không)
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        sel = getattr(self, "history_list", None).curselection() if hasattr(self, "history_list") else None
        if not sel:
            return
        p = self._history_files[sel[0]]
        try:
            txt = p.read_text(encoding="utf-8", errors="ignore")
            self.detail_text.config(state="normal")
            self.detail_text.delete("1.0", "end")
            self.detail_text.insert("1.0", txt)
            self.ui_status(f"Xem: {p.name}")
        except Exception as e:
            self.ui_message("error", "History", str(e))

    def _open_history_selected(self):
        """
        Mục đích: Làm việc với file/thư mục (chọn, nạp, xem trước, xoá, cập nhật danh sách).
        Tham số: (không)
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        sel = self.history_list.curselection()
        if not sel:
            return
        p = self._history_files[sel[0]]
        try:
            self._open_path(p)
        except Exception as e:
            self.ui_message("error", "History", str(e))

    def _delete_history_selected(self):
        """
        Mục đích: Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
        Tham số: (không)
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        sel = self.history_list.curselection()
        if not sel:
            return
        p = self._history_files[sel[0]]
        try:
            p.unlink()
            self._refresh_history_list()
            self.detail_text.delete("1.0", "end")
        except Exception as e:
            self.ui_message("error", "History", str(e))

    def _open_reports_folder(self):
        """
        Mục đích: Làm việc với file/thư mục (chọn, nạp, xem trước, xoá, cập nhật danh sách).
        Tham số: (không)
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        d = self._get_reports_dir()
        if d:
            self._open_path(d)

    def _refresh_json_list(self):
        """
        Mục đích: Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
        Tham số: (không)
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        if not hasattr(self, "json_list"):
            return
        self.json_list.delete(0, "end")
        d = self._get_reports_dir()
        files = sorted(d.glob("ctx_*.json"), reverse=True) if d else []
        self.json_files = list(files)
        for p in files:
            self.json_list.insert("end", p.name)

    def _preview_json_selected(self):
        """
        Mục đích: Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
        Tham số: (không)
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        sel = getattr(self, "json_list", None).curselection() if hasattr(self, "json_list") else None
        if not sel:
            return
        p = self.json_files[sel[0]]
        try:
            txt = p.read_text(encoding="utf-8", errors="ignore")
            self.detail_text.config(state="normal")
            self.detail_text.delete("1.0", "end")
            self.detail_text.insert("1.0", txt)
            self.ui_status(f"Xem JSON: {p.name}")
        except Exception as e:
            self.ui_message("error", "JSON", str(e))

    def _load_json_selected(self):
        """
        Mục đích: Làm việc với file/thư mục (chọn, nạp, xem trước, xoá, cập nhật danh sách).
        Tham số: (không)
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        sel = self.json_list.curselection()
        if not sel:
            return
        p = self.json_files[sel[0]]
        try:
            self._open_path(p)
        except Exception as e:
            self.ui_message("error", "JSON", str(e))

    def _delete_json_selected(self):
        """
        Mục đích: Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
        Tham số: (không)
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        sel = self.json_list.curselection()
        if not sel:
            return
        p = self.json_files[sel[0]]
        try:
            p.unlink()
            self._refresh_json_list()
            self.detail_text.delete("1.0", "end")
        except Exception as e:
            self.ui_message("error", "JSON", str(e))

    def _open_json_folder(self):
        """
        Mục đích: Làm việc với file/thư mục (chọn, nạp, xem trước, xoá, cập nhật danh sách).
        Tham số: (không)
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        d = self._get_reports_dir()
        if d:
            self._open_path(d)

    def _detect_timeframe_from_name(self, name: str) -> str:
        """
        Mục đích: Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
        Tham số:
          - name: str — (tự suy luận theo ngữ cảnh sử dụng).
        Trả về: str
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        s = Path(name).stem.lower()

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
        """
        Mục đích: Khởi tạo/cấu hình thành phần giao diện hoặc cấu trúc dữ liệu nội bộ.
        Tham số:
          - names — (tự suy luận theo ngữ cảnh sử dụng).
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        lines = []
        for n in names:
            tf = self._detect_timeframe_from_name(n)
            lines.append(f"- {n} ⇒ {tf}")
        return "\n".join(lines)

    def _toggle_autorun(self):
        """
        Mục đích: Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
        Tham số: (không)
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        if self.autorun_var.get():
            self._schedule_next_autorun()
        else:
            if self._autorun_job:
                self.root.after_cancel(self._autorun_job)
                self._autorun_job = None
            self.ui_status("Đã tắt auto-run.")

    def _autorun_interval_changed(self):
        """
        Mục đích: Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
        Tham số: (không)
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        if self.autorun_var.get():
            self._schedule_next_autorun()

    def _schedule_next_autorun(self):
        """
        Mục đích: Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
        Tham số: (không)
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        if not self.autorun_var.get():
            return
        if self._autorun_job:
            self.root.after_cancel(self._autorun_job)
        secs = max(5, int(self.autorun_seconds_var.get()))
        self._autorun_job = self.root.after(secs * 1000, self._autorun_tick)
        self.ui_status(f"Tự động chạy sau {secs}s.")

    def _autorun_tick(self):
        """
        Mục đích: Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
        Tham số: (không)
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        self._autorun_job = None
        if not self.is_running:
            self.start_analysis()
        else:

            if self.mt5_enabled_var.get() and self.auto_trade_enabled_var.get():

                cfg_snapshot = self._snapshot_config()
                def _sweep(c):
                    """
                    Mục đích: Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
                    Tham số:
                      - c — (tự suy luận theo ngữ cảnh sử dụng).
                    Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
                    Ghi chú:
                      - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
                    """
                    try:
                        ctx = self._mt5_build_context(plan=None, cfg=c) or ""
                        if ctx:
                            data = json.loads(ctx).get("MT5_DATA", {})
                            if data:
                                auto_trade.mt5_manage_be_trailing(self,data, c)
                    except Exception:
                        pass
                threading.Thread(target=_sweep, args=(cfg_snapshot,), daemon=True).start()
            self._schedule_next_autorun()

    def _pick_mt5_terminal(self):
        """
        Mục đích: Tương tác với MetaTrader 5 (kết nối, lấy dữ liệu nến, tính toán chỉ số, snapshot...).
        Tham số: (không)
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        p = filedialog.askopenfilename(
            title="Chọn terminal64.exe hoặc terminal.exe",
            filetypes=[("MT5 terminal", "terminal*.exe"), ("Tất cả", "*.*")],
        )
        if p:
            self.mt5_term_path_var.set(p)

    def _mt5_guess_symbol(self):
        """
        Mục đích: Tương tác với MetaTrader 5 (kết nối, lấy dữ liệu nến, tính toán chỉ số, snapshot...).
        Tham số: (không)
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
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
                self.ui_status(f"Đã đoán symbol: {self.mt5_symbol_var.get()}")
            else:
                self.ui_message("info", "MT5", "Không đoán được symbol từ tên file.")
        except Exception:
            pass

    def _mt5_connect(self):
        """
        Mục đích: Tương tác với MetaTrader 5 (kết nối, lấy dữ liệu nến, tính toán chỉ số, snapshot...).
        Tham số: (không)
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        if mt5 is None:
            self.ui_message("error", "MT5", "Chưa cài thư viện MetaTrader5.\nHãy chạy: pip install MetaTrader5")
            return
        term = self.mt5_term_path_var.get().strip() or None
        try:
            ok = mt5.initialize(path=term) if term else mt5.initialize()
            self.mt5_initialized = bool(ok)
            if not ok:
                err = f"MT5: initialize() thất bại: {mt5.last_error()}"
                self._enqueue(lambda: self.mt5_status_var.set(err))
                self.ui_message("error", "MT5", f"initialize() lỗi: {mt5.last_error()}")
            else:
                v = mt5.version()
                self._enqueue(lambda: self.mt5_status_var.set(f"MT5: đã kết nối (build {v[0]})"))
                self.ui_message("info", "MT5", "Kết nối thành công.")
        except Exception as e:
            self._enqueue(lambda: self.mt5_status_var.set(f"MT5: lỗi kết nối: {e}"))
            self.ui_message("error", "MT5", f"Lỗi kết nối: {e}")

    def _mt5_build_context(self, plan=None, cfg: RunConfig | None = None):
        """
        Mục đích: Tương tác với MetaTrader 5 (kết nối, lấy dữ liệu nến, tính toán chỉ số, snapshot...).
        Tham số:
          - plan — (tự suy luận theo ngữ cảnh sử dụng).
          - cfg: RunConfig | None — (tự suy luận theo ngữ cảnh sử dụng).
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        sym = (cfg.mt5_symbol if cfg else (self.mt5_symbol_var.get() or "").strip())
        if not ((cfg.mt5_enabled if cfg else self.mt5_enabled_var.get()) and sym) or mt5 is None:
            return ""
        if not self.mt5_initialized:
            self._mt5_connect()
            if not self.mt5_initialized:
                return ""

        # Delegate to mt5_utils for building the MT5 context JSON
        try:
            return mt5_utils.build_context(
                sym,
                n_m1=(cfg.mt5_n_M1 if cfg else int(self.mt5_n_M1.get())),
                n_m5=(cfg.mt5_n_M5 if cfg else int(self.mt5_n_M5.get())),
                n_m15=(cfg.mt5_n_M15 if cfg else int(self.mt5_n_M15.get())),
                n_h1=(cfg.mt5_n_H1 if cfg else int(self.mt5_n_H1.get())),
                plan=plan,
                return_json=True,
            ) or ""
        except Exception:
            return ""

    def _mt5_snapshot_popup(self):
        """
        Mục đích: Tương tác với MetaTrader 5 (kết nối, lấy dữ liệu nến, tính toán chỉ số, snapshot...).
        Tham số: (không)
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        txt = self._mt5_build_context(plan=None)
        if not txt:
            self.ui_message("warning", "MT5", "Không thể lấy dữ liệu. Kiểm tra kết nối/biểu tượng (Symbol).")
            return
        win = tk.Toplevel(self.root)
        win.title("MT5 snapshot")
        win.geometry("760x520")
        st = ScrolledText(win, wrap="none")
        st.pack(fill="both", expand=True)
        st.insert("1.0", txt)

    def _extract_text_from_obj(self, obj):
        """
        Mục đích: Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
        Tham số:
          - obj — (tự suy luận theo ngữ cảnh sử dụng).
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        parts = []

        def walk(x):
            """
            Mục đích: Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
            Tham số:
              - x — (tự suy luận theo ngữ cảnh sử dụng).
            Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
            Ghi chú:
              - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
            """
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
        """
        Mục đích: Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
        Tham số:
          - raw: str — (tự suy luận theo ngữ cảnh sử dụng).
        Trả về: str
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        s = raw.strip()

        try:
            obj = json.loads(s)
            return self._extract_text_from_obj(obj)
        except Exception:
            pass

        try:
            obj = ast.literal_eval(s)
            return self._extract_text_from_obj(obj)
        except Exception:
            pass

        if s.count("") >= 3 and s.count("\n") <= s.count(""):
            s = (s.replace("", "\n")
                 .replace("\\t", "\t")
                 .replace('\\"', '"')
                 .replace("\\'", "'"))
        return s

    def _reformat_prompt_area(self):
        """
        Mục đích: Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
        Tham số: (không)
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        raw = self.prompt_text.get("1.0", "end")
        pretty = self._normalize_prompt_text(raw)
        self.prompt_text.delete("1.0", "end")
        self.prompt_text.insert("1.0", pretty)

    def _find_prompt_file(self):
        """
        Mục đích: Làm việc với file/thư mục (chọn, nạp, xem trước, xoá, cập nhật danh sách).
        Tham số: (không)
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        cand = []
        pfp = self.prompt_file_path_var.get().strip()
        if pfp:
            cand.append(Path(pfp))
        folder = self.folder_path.get().strip()
        if folder:
            for name in ("PROMPT.txt", "Prompt.txt", "prompt.txt"):
                cand.append(Path(folder) / name)
        cand.append(APP_DIR / "PROMPT.txt")
        for p in cand:
            try:
                if p and p.exists() and p.is_file():
                    return p
            except Exception:
                pass
        return None

    def _load_prompt_from_file(self, path=None, silent=False):
        """
        Mục đích: Làm việc với file/thư mục (chọn, nạp, xem trước, xoá, cập nhật danh sách).
        Tham số:
          - path — (tự suy luận theo ngữ cảnh sử dụng).
          - silent — (tự suy luận theo ngữ cảnh sử dụng).
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        try:
            p = Path(path) if path else self._find_prompt_file()
            if not p:
                if not silent:
                    self.ui_message("warning", "Prompt", "Không tìm thấy PROMPT.txt trong thư mục đã chọn hoặc APP_DIR.")
                return False
            raw = p.read_text(encoding="utf-8", errors="ignore")
            text = self._normalize_prompt_text(raw)
            self.prompt_text.delete("1.0", "end")
            self.prompt_text.insert("1.0", text)
            self.prompt_file_path_var.set(str(p))
            self.ui_status(f"Đã nạp prompt từ: {p.name}")
            return True
        except Exception as e:
            if not silent:
                self.ui_message("error", "Prompt", f"Lỗi nạp PROMPT.txt: {e}")
            return False

    def _pick_prompt_file(self):
        """
        Mục đích: Làm việc với file/thư mục (chọn, nạp, xem trước, xoá, cập nhật danh sách).
        Tham số: (không)
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        path = filedialog.askopenfilename(
            title="Chọn PROMPT.txt",
            filetypes=[("Text", "*.txt"), ("Tất cả", "*.*")]
        )
        if not path:
            return
        self._load_prompt_from_file(path)

    def _auto_load_prompt_for_current_folder(self):
        """
        Mục đích: Làm việc với file/thư mục (chọn, nạp, xem trước, xoá, cập nhật danh sách).
        Tham số: (không)
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        if self.auto_load_prompt_txt_var.get():
            self._load_prompt_from_file(silent=True)

    def _save_workspace(self):
        """
        Mục đích: Ghi/Xuất dữ liệu (báo cáo .md, JSON tóm tắt, cache...).
        Tham số: (không)
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
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
            self.ui_message("info", "Workspace", "Đã lưu workspace.")
        except Exception as e:
            self.ui_message("error", "Workspace", str(e))

    def _load_workspace_dup(self):
        """
        Mục đích: Làm việc với file/thư mục (chọn, nạp, xem trước, xoá, cập nhật danh sách).
        Tham số: (không)
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
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

    def _delete_workspace_dup(self):
        """
        Mục đích: Đọc/ghi cấu hình workspace, cache upload và các trạng thái phiên làm việc.
        Tham số: (không)
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        try:
            if WORKSPACE_JSON.exists():
                WORKSPACE_JSON.unlink()
            self.ui_message("info", "Workspace", "Đã xoá workspace.")
        except Exception as e:
            self.ui_message("error", "Workspace", str(e))

    def _load_workspace(self):
        """
        Mục đích: Làm việc với file/thư mục (chọn, nạp, xem trước, xoá, cập nhật danh sách).
        Tham số: (không)
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
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
        """
        Mục đích: Đọc/ghi cấu hình workspace, cache upload và các trạng thái phiên làm việc.
        Tham số: (không)
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        try:
            if WORKSPACE_JSON.exists():
                WORKSPACE_JSON.unlink()
            self.ui_message("info", "Workspace", "Đã xoá workspace.")
        except Exception as e:
            self.ui_message("error", "Workspace", str(e))

        # No periodic scheduling needed here; remove stray reference to undefined 'secs' and '_tick'.

def main():
    """
    Mục đích: Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
    Tham số: (không)
    Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
    Ghi chú:
      - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
    """
    root = tk.Tk()
    app = GeminiFolderOnceApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()
