# src/core/app_logic.py
from __future__ import annotations

import os # Cần cho os.environ.get
import sys # Cần cho sys.exit
from pathlib import Path
import json # Cần cho json.dumps, json.loads
import threading
import time
import logging
from datetime import datetime
from typing import Optional, TYPE_CHECKING, Tuple

# Để tránh lỗi import vòng tròn, sử dụng TYPE_CHECKING cho type hints
if TYPE_CHECKING:
    from src.ui.app_ui import TradingToolApp
    import tkinter as tk

from src.config.constants import API_KEY_ENC
from src.utils.utils import obfuscate_text
from src.utils.safe_data import SafeMT5Data
from src.config.config import RunConfig
from src.core import worker
from src.utils import ui_utils
from src.services import news, telegram_client
from src.core import context_builder
from src.utils import report_parser as report_utils_parser
from src.ui import history_manager
from src.core import auto_trade
from src.utils import mt5_utils
import tkinter as tk
from tkinter import filedialog
from tkinter.scrolledtext import ScrolledText

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

class AppLogic:
    """
    Lớp chứa toàn bộ logic nghiệp vụ cốt lõi của ứng dụng, tách biệt khỏi giao diện người dùng.
    """
    def __init__(self, app_ui: Optional["TradingToolApp"] = None):
        """
        Khởi tạo lớp logic nghiệp vụ, nhận tham chiếu đến đối tượng UI.
        """
        self.app_ui = app_ui
        # Khóa thread để đảm bảo an toàn khi truy cập tài nguyên dùng chung từ nhiều luồng
        self._trade_log_lock = threading.Lock()
        self._proposed_trade_log_lock = threading.Lock()
        self._vector_db_lock = threading.Lock()
        self._ui_log_lock = threading.Lock()

        self.ff_cache_events_local = []
        self.ff_cache_fetch_time   = 0.0

        self.last_no_trade_ok = None
        self.last_no_trade_reasons = []

        self._news_refresh_lock = threading.Lock()
        self._news_refresh_inflight = False

        self.is_running = False
        self.stop_flag = False
        self.results = [] # Kết quả phân tích của các file ảnh
        self.combined_report_text = "" # Báo cáo tổng hợp
        self.ui_queue = app_ui.ui_queue if app_ui else None # Sử dụng hàng đợi UI từ đối tượng UI nếu có

        self.active_worker_thread = None
        self.active_executor = None

        # Biến cho cơ chế tái kết nối và kiểm tra định kỳ
        self._mt5_reconnect_job = None
        self._mt5_reconnect_attempts = 0
        self._mt5_max_reconnect_attempts = 5
        self._mt5_reconnect_delay_sec = 5 # Giây
        self._mt5_check_connection_job = None
        self._mt5_check_interval_sec = 30 # Giây

    def set_ui_references(self, app_ui: "TradingToolApp"):
        """
        Thiết lập tham chiếu đến đối tượng UI và hàng đợi UI sau khi đối tượng UI được tạo.
        """
        self.app_ui = app_ui
        self.ui_queue = app_ui.ui_queue

    def compose_context(self, cfg: "RunConfig", budget_chars: int) -> str:
        """
        Hợp nhất các thành phần ngữ cảnh (dữ liệu MT5, báo cáo cũ, tin tức) để tạo chuỗi ngữ cảnh hoàn chỉnh
        cung cấp cho mô hình AI.
        """
        return context_builder.compose_context(self.app_ui, cfg, budget_chars)

    def _refresh_news_cache(self, app: "TradingToolApp", ttl: int = 300, *, async_fetch: bool = True, cfg: "RunConfig" | None = None) -> None:
        """
        Làm mới bộ đệm tin tức từ Forex Factory nếu dữ liệu đã cũ (quá thời gian `ttl`).
        Có thể chạy đồng bộ hoặc không đồng bộ.
        """
        try:
            now_ts = time.time()
            last_ts = float(self.ff_cache_fetch_time or 0.0)
            if (now_ts - last_ts) <= max(0, int(ttl or 0)):
                return

            # Tạo snapshot config ở luồng chính để đảm bảo an toàn thread
            final_cfg = cfg or self._snapshot_config(app)

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

    def _log_trade_decision(self, app: "TradingToolApp", data: dict, folder_override: str | None = None):
        """
        Ghi lại các quyết định hoặc sự kiện quan trọng vào file log JSONL.
        Sử dụng khóa (lock) để đảm bảo an toàn khi ghi file từ nhiều luồng.
        """
        try:
            d = history_manager._get_reports_dir(app, folder_override=folder_override)
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

    def _maybe_notify_telegram(self, app: "TradingToolApp", report_text: str, report_path: Path | None, cfg: "RunConfig"):
        """
        Gửi thông báo qua Telegram nếu tính năng Telegram được bật và báo cáo phân tích
        chứa tín hiệu giao dịch có xác suất cao ("HIGH PROBABILITY").
        Tránh gửi trùng lặp bằng cách sử dụng chữ ký báo cáo.
        """
        if not cfg.telegram_enabled or not report_text:
            return
        
        # Chỉ gửi nếu có tín hiệu "HIGH PROBABILITY" trong báo cáo
        if "HIGH PROBABILITY" not in report_text.upper():
            return

        # Tạo một "chữ ký" cho báo cáo để tránh gửi trùng lặp
        signature = report_utils_parser.create_report_signature(report_text)
        if signature == app._last_telegram_signature:
            return
        app._last_telegram_signature = signature

        # Gửi thông báo trong một luồng riêng biệt
        threading.Thread(
            target=telegram_client.send_telegram_message,
            args=(report_text, report_path, cfg),
            daemon=True
        ).start()

    def _snapshot_config(self, app: "TradingToolApp") -> "RunConfig":
        """
        Chụp lại toàn bộ trạng thái cấu hình hiện tại từ giao diện người dùng và trả về một đối tượng RunConfig.
        Điều này đảm bảo rằng luồng worker chạy với một cấu hình nhất quán,
        ngay cả khi người dùng thay đổi cài đặt trên giao diện trong lúc đang chạy.
        """
        return RunConfig(
            folder=app.folder_path.get().strip(),
            delete_after=bool(app.delete_after_var.get()),
            max_files=int(app.max_files_var.get()),
            upload_workers=int(app.upload_workers_var.get()),
            cache_enabled=bool(app.cache_enabled_var.get()),
            optimize_lossless=bool(app.optimize_lossless_var.get()),
            only_generate_if_changed=bool(app.only_generate_if_changed_var.get()),
            ctx_limit=int(app.context_limit_chars_var.get()),
            create_ctx_json=bool(app.create_ctx_json_var.get()),
            prefer_ctx_json=bool(app.prefer_ctx_json_var.get()),
            ctx_json_n=int(app.ctx_json_n_var.get()),
            telegram_enabled=bool(app.telegram_enabled_var.get()),
            telegram_token=app.telegram_token_var.get().strip(),
            telegram_chat_id=app.telegram_chat_id_var.get().strip(),
            telegram_skip_verify=bool(app.telegram_skip_verify_var.get()),
            telegram_ca_path=app.telegram_ca_path_var.get().strip(),
            mt5_enabled=bool(app.mt5_enabled_var.get()),
            mt5_symbol=app.mt5_symbol_var.get().strip(),
            mt5_n_M1=int(app.mt5_n_M1.get()),
            mt5_n_M5=int(app.mt5_n_M5.get()),
            mt5_n_M15=int(app.mt5_n_M15.get()),
            mt5_n_H1=int(app.mt5_n_H1.get()),
            nt_enabled=bool(app.no_trade_enabled_var.get()),
            nt_spread_factor=float(app.nt_spread_factor_var.get()),
            nt_min_atr_m5_pips=float(app.nt_min_atr_m5_pips_var.get()),
            nt_min_ticks_per_min=int(app.nt_min_ticks_per_min_var.get()),
            auto_trade_enabled=bool(app.auto_trade_enabled_var.get()),
            trade_strict_bias=bool(app.trade_strict_bias_var.get()),
            trade_size_mode=app.trade_size_mode_var.get(),
            trade_lots_total=float(app.trade_lots_total_var.get()),
            trade_equity_risk_pct=float(app.trade_equity_risk_pct_var.get()),
            trade_money_risk=float(app.trade_money_risk_var.get()),
            trade_split_tp1_pct=int(app.trade_split_tp1_pct_var.get()),
            trade_deviation_points=int(app.trade_deviation_points_var.get()),
            trade_pending_threshold_points=int(app.trade_pending_threshold_points_var.get()),
            trade_magic=int(app.trade_magic_var.get()),
            trade_comment_prefix=app.trade_comment_prefix_var.get(),
            trade_pending_ttl_min=int(app.trade_pending_ttl_min_var.get()),
            trade_min_rr_tp2=float(app.trade_min_rr_tp2_var.get()),
            trade_min_dist_keylvl_pips=float(app.trade_min_dist_keylvl_pips_var.get()),
            trade_cooldown_min=int(app.trade_cooldown_min_var.get()),
            trade_dynamic_pending=bool(app.trade_dynamic_pending_var.get()),
            auto_trade_dry_run=bool(app.auto_trade_dry_run_var.get()),
            trade_move_to_be_after_tp1=bool(app.trade_move_to_be_after_tp1_var.get()),
            trade_trailing_atr_mult=float(app.trade_trailing_atr_mult_var.get()),
            trade_allow_session_asia=bool(app.trade_allow_session_asia_var.get()),
            trade_allow_session_london=bool(app.trade_allow_session_london_var.get()),
            trade_allow_session_ny=bool(app.trade_allow_session_ny_var.get()),
            trade_news_block_before_min=int(app.trade_news_block_before_min_var.get()),
            trade_news_block_after_min=int(app.trade_news_block_after_min_var.get()),
            trade_news_block_enabled=True,
            news_cache_ttl_sec=300,
        )

    def _load_env(self, app: "TradingToolApp"):
        """
        Mở hộp thoại cho người dùng chọn tệp .env và tải biến môi trường từ đó.
        Ưu tiên nạp GOOGLE_API_KEY.
        """
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
                            app.api_key_var.set(v.strip())
                            break
                ui_utils.ui_message(app, "info", "ENV", "Đã nạp GOOGLE_API_KEY từ file.")
            except Exception as e:
                ui_utils.ui_message(app, "error", "ENV", str(e))
        # Nếu có python-dotenv, sử dụng nó để tải tất cả các biến
        else:
            load_dotenv(path)
            val = os.environ.get("GOOGLE_API_KEY", "")
            if val:
                app.api_key_var.set(val)
                ui_utils.ui_message(app, "info", "ENV", "Đã nạp GOOGLE_API_KEY từ .env")

    def _save_api_safe(self, app: "TradingToolApp"):
        """
        Mã hóa và lưu API key vào tệp để sử dụng trong các lần chạy sau.
        """
        try:
            API_KEY_ENC.write_text(obfuscate_text(app.api_key_var.get().strip()), encoding="utf-8")
            ui_utils.ui_message(app, "info", "API", f"Đã lưu an toàn vào: {API_KEY_ENC}")
        except Exception as e:
            ui_utils.ui_message(app, "error", "API", str(e))

    def _delete_api_safe(self, app: "TradingToolApp"):
        """
        Xóa tệp chứa API key đã mã hóa khỏi hệ thống.
        """
        try:
            if API_KEY_ENC.exists():
                API_KEY_ENC.unlink()
            ui_utils.ui_message(app, "info", "API", "Đã xoá API key đã lưu.")
        except Exception as e:
            ui_utils.ui_message(app, "error", "API", str(e))

    def start_analysis(self, app: "TradingToolApp"):
        """
        Bắt đầu một phiên phân tích mới.
        Kiểm tra các điều kiện cần thiết, cấu hình Gemini API, và khởi chạy luồng worker
        để thực hiện phân tích ảnh.
        """
        if app.is_running:
            return
        folder = app.folder_path.get().strip()
        if not folder:
            ui_utils.ui_message(app, "warning", "Thiếu thư mục", "Vui lòng chọn thư mục ảnh trước.")
            return

        if app.cache_enabled_var.get() and app.delete_after_var.get():
            ui_utils.ui_status(app, "Lưu ý: Cache ảnh đang bật, KHÔNG nên xoá file trên Gemini sau phân tích.")

        app.clear_results()
        ui_utils.ui_status(app, "Đang nạp lại ảnh từ thư mục đã chọn...")
        app._load_files(folder)
        if len(app.results) == 0:
            return

        prompt_no_entry = app.prompt_no_entry_text.get("1.0", "end").strip()
        prompt_entry_run = app.prompt_entry_run_text.get("1.0", "end").strip()

        if not prompt_no_entry or not prompt_entry_run:
            ui_utils.ui_message(app, "warning", "Thiếu prompt", "Vui lòng nhập nội dung cho cả hai tab prompt trước khi chạy.")
            return
        
        cfg = self._snapshot_config(app)

        api_key = app.api_key_var.get().strip() or os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            ui_utils.ui_message(app, "warning", "Thiếu API key", "Vui lòng nhập API key hoặc đặt biến môi trường GOOGLE_API_KEY.")
            return
        try:
            # Cấu hình API key cho thư viện Gemini
            genai.configure(api_key=api_key)
        except Exception as e:
            ui_utils.ui_message(app, "error", "Gemini", f"Lỗi cấu hình API: {e}")
            return

        # Đặt lại trạng thái của các kết quả trước khi bắt đầu
        for i, r in enumerate(app.results):
            r["status"] = "Chưa xử lý"
            r["text"] = ""
            app._update_tree_row(i, r["status"])
        app.combined_report_text = ""
        ui_utils.ui_progress(app, 0)
        ui_utils.ui_detail_replace(app, "Đang chuẩn bị phân tích...")

        app.stop_flag = False
        app.is_running = True
        app.stop_btn.configure(state="normal")

        # Chạy logic phân tích chính trong một luồng riêng biệt
        # và lưu lại tham chiếu đến luồng này
        app.active_worker_thread = threading.Thread(
            target=worker.run_analysis_worker,
            args=(
                app,
                prompt_no_entry,
                prompt_entry_run,
                app.model_var.get(),
                cfg
            ),
            daemon=True
        )
        app.active_worker_thread.start()

    def stop_analysis(self, app: "TradingToolApp"):
        """
        Gửi tín hiệu dừng cho luồng worker đang chạy và hủy các tác vụ upload đang chờ
        trong executor để dừng quá trình phân tích.
        """
        if not app.is_running:
            return

        app.stop_flag = True
        ui_utils.ui_status(app, "Đang gửi yêu cầu dừng...")

        # Hủy các tác vụ upload đang chờ trong executor
        if app.active_executor:
            try:
                # Hủy tất cả các future chưa bắt đầu chạy.
                # wait=False để không chặn luồng UI.
                app.active_executor.shutdown(wait=False, cancel_futures=True)
                ui_utils.ui_status(app, "Đã yêu cầu hủy các tác vụ upload đang chờ.")
            except Exception as e:
                logging.warning(f"Lỗi khi shutdown executor: {e}")
        else:
            ui_utils.ui_status(app, "Đang dừng... (Không có tác vụ upload nào đang hoạt động)")

    def _maybe_delete(self, uploaded_file):
        """
        Thực hiện xóa file đã upload lên Gemini nếu cấu hình cho phép.
        """
        try:
            genai.delete_file(uploaded_file.name)
        except Exception:
            pass

    def _finalize_done(self, app: "TradingToolApp"):
        """
        Hoàn tất quá trình phân tích khi tất cả các file đã được xử lý.
        Ghi log kết thúc, cập nhật trạng thái giao diện và lên lịch cho lần chạy tự động tiếp theo (nếu bật).
        """
        try:
            self._log_trade_decision(app, {
                "stage": "run-end",
                "t": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }, folder_override=(app.mt5_symbol_var.get().strip() or None))
        except Exception:
            pass

        app.is_running = False
        app.stop_flag = False
        app.active_worker_thread = None
        app.active_executor = None
        app.stop_btn.configure(state="disabled")
        ui_utils.ui_status(app, "Đã hoàn tất phân tích toàn bộ thư mục.")
        self._schedule_next_autorun(app)

    def _finalize_stopped(self, app: "TradingToolApp"):
        """
        Hoàn tất quá trình phân tích khi người dùng yêu cầu dừng.
        Cập nhật trạng thái giao diện và lên lịch cho lần chạy tự động tiếp theo (nếu bật).
        """
        app.is_running = False
        app.stop_flag = False
        app.active_worker_thread = None
        app.active_executor = None
        app.stop_btn.configure(state="disabled")
        ui_utils.ui_status(app, "Đã dừng.")
        self._schedule_next_autorun(app)

    def _toggle_autorun(self, app: "TradingToolApp"):
        """
        Bật hoặc tắt chế độ tự động chạy phân tích.
        Nếu bật, lên lịch cho lần chạy tiếp theo. Nếu tắt, hủy lịch chạy hiện tại.
        """
        if app.autorun_var.get():
            self._schedule_next_autorun(app)
        else:
            if app._autorun_job:
                app.root.after_cancel(app._autorun_job)
                app._autorun_job = None
            ui_utils.ui_status(app, "Đã tắt auto-run.")

    def _autorun_interval_changed(self, app: "TradingToolApp"):
        """
        Xử lý khi khoảng thời gian tự động chạy thay đổi.
        Nếu chế độ tự động chạy đang bật, lên lịch lại cho lần chạy tiếp theo.
        """
        if app.autorun_var.get():
            self._schedule_next_autorun(app)

    def _schedule_next_autorun(self, app: "TradingToolApp"):
        """
        Lên lịch cho lần chạy tự động tiếp theo sau một khoảng thời gian nhất định.
        """
        if not app.autorun_var.get():
            return
        if app._autorun_job:
            app.root.after_cancel(app._autorun_job)
        secs = max(5, int(app.autorun_seconds_var.get()))
        app._autorun_job = app.root.after(secs * 1000, lambda: self._autorun_tick(app))
        ui_utils.ui_status(app, f"Tự động chạy sau {secs}s.")

    def _autorun_tick(self, app: "TradingToolApp"):
        """
        Hàm được gọi khi đến thời gian tự động chạy.
        Nếu không có phân tích nào đang chạy, bắt đầu một phân tích mới.
        Nếu đang chạy, thực hiện các tác vụ nền như quản lý BE/Trailing.
        """
        app._autorun_job = None
        # Nếu không có phân tích nào đang chạy, bắt đầu một phân tích mới.
        if not app.is_running:
            self.start_analysis(app)
        else:
            # Nếu một phân tích đang chạy, thực hiện các tác vụ nền (nếu được bật)
            # như quản lý trailing stop cho các lệnh đang mở.
            if app.mt5_enabled_var.get() and app.auto_trade_enabled_var.get():

                cfg_snapshot = self._snapshot_config(app)
                def _sweep(c):
                    try:
                        ctx = self._mt5_build_context(app, plan=None, cfg=c) or ""
                        if ctx:
                            data = json.loads(ctx).get("MT5_DATA", {})
                            # auto_trade.mt5_manage_be_trailing(app,data, c) # Tạm thời vô hiệu hóa
                    except Exception:
                        pass
                threading.Thread(target=_sweep, args=(cfg_snapshot,), daemon=True).start()
            # Lên lịch cho lần chạy tự động tiếp theo.
            self._schedule_next_autorun(app)

    def _pick_mt5_terminal(self, app: "TradingToolApp"):
        """
        Mở hộp thoại cho người dùng chọn đường dẫn đến file thực thi của MetaTrader 5 (terminal64.exe hoặc terminal.exe).
        """
        p = filedialog.askopenfilename(
            title="Chọn terminal64.exe hoặc terminal.exe",
            filetypes=[("MT5 terminal", "terminal*.exe"), ("Tất cả", "*.*")],
        )
        if p:
            app.mt5_term_path_var.set(p)

    def _mt5_guess_symbol(self, app: "TradingToolApp"):
        """
        Cố gắng đoán biểu tượng (symbol) giao dịch từ tên các file ảnh đã nạp.
        Ví dụ: "EURUSD_H1.png" sẽ đoán là "EURUSD".
        """
        try:
            tfs = {"M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1", "MN1"}
            names = [r["name"] for r in app.results]
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
                app.mt5_symbol_var.set(Counter(cands).most_common(1)[0][0])
                ui_utils.ui_status(app, f"Đã đoán symbol: {app.mt5_symbol_var.get()}")
            else:
                ui_utils.ui_message(app, "info", "MT5", "Không đoán được symbol từ tên file.")
        except Exception:
            pass

    def _mt5_connect(self, app: "TradingToolApp") -> Tuple[bool, str]:
        """
        Khởi tạo kết nối đến MetaTrader 5.
        Trả về trạng thái kết nối (True/False) và thông báo.
        """
        if mt5 is None:
            msg = "Chưa cài thư viện MetaTrader5.\nHãy chạy: pip install MetaTrader5"
            logging.error(f"MT5 Connect Error: {msg}")
            return False, msg
        
        term = app.mt5_term_path_var.get().strip() or None
        try:
            ok = mt5.initialize(path=term) if term else mt5.initialize()
            app.mt5_initialized = bool(ok)
            if not ok:
                err_code = mt5.last_error()
                msg = f"MT5: initialize() thất bại: {err_code}"
                logging.error(f"MT5 Connect Error: {msg}")
                return False, msg
            else:
                v = mt5.version()
                msg = f"MT5: đã kết nối (build {v[0]})"
                logging.info(f"MT5 Connect Success: {msg}")
                return True, msg
        except Exception as e:
            msg = f"MT5: lỗi kết nối: {e}"
            logging.error(f"MT5 Connect Exception: {msg}")
            self._schedule_mt5_reconnect(app) # Kích hoạt tái kết nối
            return False, msg

    def _schedule_mt5_reconnect(self, app: "TradingToolApp"):
        """
        Lên lịch để thử tái kết nối MT5 sau một khoảng thời gian.
        Sử dụng exponential backoff và giới hạn số lần thử.
        """
        if self._mt5_reconnect_job:
            app.root.after_cancel(self._mt5_reconnect_job)
            self._mt5_reconnect_job = None

        if self._mt5_reconnect_attempts >= self._mt5_max_reconnect_attempts:
            logging.warning("MT5 Reconnect: Đã đạt số lần thử tối đa, dừng tái kết nối.")
            ui_utils._enqueue(app, lambda: app.mt5_status_var.set("MT5: Tái kết nối thất bại."))
            self._mt5_reconnect_attempts = 0 # Reset để có thể thử lại thủ công
            return

        delay = self._mt5_reconnect_delay_sec * (2 ** self._mt5_reconnect_attempts)
        delay = min(delay, 600) # Giới hạn độ trễ tối đa 10 phút
        self._mt5_reconnect_attempts += 1

        ui_utils._enqueue(app, lambda: app.mt5_status_var.set(f"MT5: Đang thử tái kết nối ({self._mt5_reconnect_attempts}/{self._mt5_max_reconnect_attempts}) sau {delay}s..."))
        logging.info(f"MT5 Reconnect: Lên lịch thử lại sau {delay}s (lần {self._mt5_reconnect_attempts}).")

        self._mt5_reconnect_job = app.root.after(int(delay * 1000), lambda: self._attempt_mt5_reconnect(app))

    def _attempt_mt5_reconnect(self, app: "TradingToolApp"):
        """
        Thực hiện một lần thử tái kết nối MT5.
        """
        logging.info("MT5 Reconnect: Đang thực hiện tái kết nối...")
        ok, msg = self._mt5_connect(app)
        if ok:
            logging.info("MT5 Reconnect: Tái kết nối thành công.")
            self._mt5_reconnect_attempts = 0 # Reset số lần thử
            self._schedule_mt5_connection_check(app) # Bắt đầu kiểm tra định kỳ
        else:
            logging.warning(f"MT5 Reconnect: Tái kết nối thất bại: {msg}")
            self._schedule_mt5_reconnect(app) # Lên lịch thử lại

    def _schedule_mt5_connection_check(self, app: "TradingToolApp"):
        """
        Lên lịch kiểm tra kết nối MT5 định kỳ.
        """
        if self._mt5_check_connection_job:
            app.root.after_cancel(self._mt5_check_connection_job)
            self._mt5_check_connection_job = None

        ui_utils._enqueue(app, lambda: app.mt5_status_var.set(f"MT5: Đã kết nối. Kiểm tra sau {self._mt5_check_interval_sec}s."))
        self._mt5_check_connection_job = app.root.after(int(self._mt5_check_interval_sec * 1000), lambda: self._check_mt5_connection(app))

    def _check_mt5_connection(self, app: "TradingToolApp"):
        """
        Thực hiện kiểm tra trạng thái kết nối MT5.
        Nếu kết nối bị mất, kích hoạt cơ chế tái kết nối.
        """
        if not app.mt5_enabled_var.get():
            logging.info("MT5 Check: MT5 không được bật, dừng kiểm tra định kỳ.")
            return

        if mt5 is None:
            logging.warning("MT5 Check: Thư viện MetaTrader5 không có, không thể kiểm tra.")
            self._schedule_mt5_reconnect(app) # Cố gắng tái kết nối nếu thư viện bị thiếu
            return

        try:
            if not mt5.initialize(): # Cố gắng khởi tạo lại nếu cần
                logging.warning("MT5 Check: initialize() thất bại, kết nối có thể bị mất.")
                app.mt5_initialized = False
                self._schedule_mt5_reconnect(app)
                return
            
            # Kiểm tra nhẹ bằng cách lấy thông tin tài khoản
            account_info = mt5.account_info()
            if account_info is None:
                logging.warning("MT5 Check: Không thể lấy thông tin tài khoản, kết nối có thể bị mất.")
                app.mt5_initialized = False
                self._schedule_mt5_reconnect(app)
                return
            
            logging.debug("MT5 Check: Kết nối vẫn hoạt động.")
            app.mt5_initialized = True # Đảm bảo trạng thái được cập nhật
            self._schedule_mt5_connection_check(app) # Lên lịch kiểm tra tiếp theo
        except Exception as e:
            logging.error(f"MT5 Check Exception: {e}")
            app.mt5_initialized = False
            self._schedule_mt5_reconnect(app)

    def _mt5_build_context(self, app: "TradingToolApp", plan=None, cfg: "RunConfig" | None = None) -> Optional["SafeMT5Data"]:
        """
        Xây dựng đối tượng ngữ cảnh MetaTrader 5 (SafeMT5Data) chứa dữ liệu thị trường hiện tại
        (giá nến, thông tin tài khoản, các lệnh đang mở...).
        """
        sym = (cfg.mt5_symbol if cfg else (app.mt5_symbol_var.get() or "").strip())
        if not ((cfg.mt5_enabled if cfg else app.mt5_enabled_var.get()) and sym) or mt5 is None:
            return None
        if not app.mt5_initialized:
            ok, _ = self._mt5_connect(app)
            if not ok:
                return None

        # Ủy quyền cho mt5_utils để xây dựng đối tượng ngữ cảnh MT5
        try:
            return mt5_utils.build_context(
                sym,
                n_m1=(cfg.mt5_n_M1 if cfg else int(app.mt5_n_M1.get())),
                n_m5=(cfg.mt5_n_M5 if cfg else int(app.mt5_n_M5.get())),
                n_m15=(cfg.mt5_n_M15 if cfg else int(app.mt5_n_M15.get())),
                n_h1=(cfg.mt5_n_H1 if cfg else int(app.mt5_n_H1.get())),
                plan=plan,
                return_json=False, # Đảm bảo chúng ta nhận được đối tượng Python, không phải chuỗi JSON
            )
        except Exception:
            return None

    def _mt5_snapshot_popup(self, app: "TradingToolApp"):
        """
        Hiển thị một cửa sổ popup chứa dữ liệu MetaTrader 5 hiện tại dưới dạng JSON.
        """
        safe_data = self._mt5_build_context(app, plan=None)
        if not safe_data or not safe_data.raw:
            ui_utils.ui_message(app, "warning", "MT5", "Không thể lấy dữ liệu. Kiểm tra kết nối/biểu tượng (Symbol).")
            return
        
        # Chuyển đổi dữ liệu thô sang chuỗi JSON có định dạng để hiển thị
        try:
            json_text = json.dumps(safe_data.raw, ensure_ascii=False, indent=2)
        except Exception as e:
            json_text = f"Lỗi khi định dạng JSON: {e}\n\nDữ liệu thô:\n{safe_data.raw}"

        win = tk.Toplevel(app.root)
        win.title("MT5 snapshot")
        win.geometry("760x520")
        st = ScrolledText(win, wrap="none")
        st.pack(fill="both", expand=True)
        st.insert("1.0", json_text)
