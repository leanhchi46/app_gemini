# src/core/app_logic.py
from __future__ import annotations

import os  # Cần cho os.environ.get
import sys  # Cần cho sys.exit
from pathlib import Path
import json  # Cần cho json.dumps, json.loads
import threading
import time
import logging
from typing import Optional, TYPE_CHECKING, Tuple

# Khởi tạo logger cho module này
logger = logging.getLogger(__name__)

# Để tránh lỗi import vòng tròn, sử dụng TYPE_CHECKING cho type hints
if TYPE_CHECKING:
    from src.ui.app_ui import TradingToolApp
    import tkinter as tk

from src.config.constants import API_KEY_ENC
from src.utils.utils import obfuscate_text
from src.config.config import RunConfig
from src.core.worker_modules import main_worker as worker
from src.utils import ui_utils
from src.services import telegram_client
from src.services import news
from src.core import context_builder
from src.utils import report_parser as report_utils_parser
from src.utils import mt5_utils
from src.core.worker_modules import no_run_trade_conditions # Import module mới
import tkinter as tk
from tkinter import filedialog
from tkinter.scrolledtext import ScrolledText
import dotenv # Thêm import dotenv
from dotenv import load_dotenv # Thêm import load_dotenv

try:
    import google.generativeai as genai
except ImportError:
    print(
        "Lỗi: Cần cài đặt Google Gemini SDK. Chạy lệnh: pip install google-generativeai"
    )
    sys.exit(1)

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None


class AppLogic:
    """
    Lớp chứa toàn bộ logic nghiệp vụ cốt lõi của ứng dụng, tách biệt khỏi giao diện người dùng.
    Nó quản lý các tác vụ như cấu hình API, phân tích dữ liệu, tương tác với MT5,
    và xử lý các sự kiện tự động.
    """

    def __init__(self, app_ui: Optional["TradingToolApp"] = None):
        """
        Khởi tạo lớp logic nghiệp vụ, nhận tham chiếu đến đối tượng UI.

        Args:
            app_ui: Tham chiếu đến đối tượng giao diện người dùng (TradingToolApp), có thể là None.
        """
        logger.debug("Bắt đầu hàm __init__.")
        logger.debug("Khởi tạo AppLogic.")
        self.app_ui = app_ui
        # Khóa thread để đảm bảo an toàn khi truy cập tài nguyên dùng chung từ nhiều luồng
        self._trade_log_lock = threading.Lock()
        self._proposed_trade_log_lock = threading.Lock()
        self._vector_db_lock = threading.Lock()
        self._ui_log_lock = threading.Lock()

        self.ff_cache_events_local = []
        self.ff_cache_fetch_time = 0.0

        self.last_no_trade_ok = None
        self.last_no_trade_reasons = []

        self._news_refresh_lock = threading.Lock()
        self._news_refresh_inflight = False

        self.is_running = False
        self.stop_flag = False
        self.results = []  # Kết quả phân tích của các file ảnh
        self.combined_report_text = ""  # Báo cáo tổng hợp
        self.ui_queue = (
            app_ui.ui_queue if app_ui else None
        )  # Sử dụng hàng đợi UI từ đối tượng UI nếu có

        self.active_worker_thread = None
        self.active_executor = None

        # Biến cho cơ chế tái kết nối và kiểm tra định kỳ
        self._mt5_reconnect_job = None
        self._mt5_reconnect_attempts = 0
        self._mt5_max_reconnect_attempts = 5
        self._mt5_reconnect_delay_sec = 5  # Giây
        self._mt5_check_connection_job = None
        self._mt5_check_interval_sec = 30  # Giây

    def set_ui_references(self, app_ui: "TradingToolApp"):
        """
        Thiết lập tham chiếu đến đối tượng UI và hàng đợi UI sau khi đối tượng UI được tạo.

        Args:
            app_ui: Đối tượng giao diện người dùng (TradingToolApp).
        """
        logger.debug("Bắt đầu hàm set_ui_references.")
        self.app_ui = app_ui
        self.ui_queue = app_ui.ui_queue
        logger.debug("Thiết lập tham chiếu UI cho AppLogic.")
        logger.debug("Kết thúc set_ui_references.")

    def _configure_gemini_api_and_update_ui(self, app: "TradingToolApp"):
        """
        Cấu hình Gemini API với API key hiện tại và cập nhật danh sách mô hình AI trên UI.

        Args:
            app: Đối tượng giao diện người dùng (TradingToolApp).
        """
        logger.debug("Bắt đầu hàm _configure_gemini_api_and_update_ui.")
        api_key = app.api_key_var.get().strip() or os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            ui_utils._enqueue(app, lambda: app.ui_status("Thiếu API key để cấu hình Gemini."))
            logger.warning("Thiếu API key để cấu hình Gemini API.")
            return

        def _do_configure():
            """
            Thực hiện cấu hình Gemini API trong một luồng nền.
            """
            logger.debug("Bắt đầu hàm _do_configure.")
            try:
                genai.configure(api_key=api_key)
                ui_utils._enqueue(app, lambda: app.ui_status("Đã cấu hình Gemini API."))
                logger.debug("Đã cấu hình Gemini API key.")
                app._update_model_list_in_ui() # Gọi hàm cập nhật danh sách mô hình AI
            except genai.exceptions.APIError as e:
                error_message = f"Lỗi cấu hình Gemini API: {e.message}. Vui lòng kiểm tra lại API key và đảm bảo nó có đủ quyền truy cập."
                ui_utils._enqueue(app, lambda: app.ui_status(error_message))
                logger.exception(error_message)
            except Exception as e:
                error_message = f"Lỗi cấu hình Gemini API không xác định: {e}"
                ui_utils._enqueue(app, lambda: app.ui_status(error_message))
                logger.exception(error_message)
        
        threading.Thread(target=_do_configure, daemon=True).start()

    def compose_context(self, cfg: "RunConfig", budget_chars: int) -> str:
        """
        Hợp nhất các thành phần ngữ cảnh (dữ liệu MT5, báo cáo cũ, tin tức) để tạo chuỗi ngữ cảnh hoàn chỉnh
        cung cấp cho mô hình AI.

        Args:
            cfg: Đối tượng cấu hình RunConfig.
            budget_chars: Ngân sách ký tự tối đa cho chuỗi ngữ cảnh.

        Returns:
            Chuỗi JSON của ngữ cảnh đã được tạo.
        """
        logger.debug("Bắt đầu hàm compose_context.")
        logger.debug(f"Bắt đầu compose_context với budget_chars: {budget_chars}.")
        
        # Chạy việc xây dựng ngữ cảnh trong một luồng nền để tránh chặn UI
        context_result = threading.Event()
        context_data = {"context": "", "exception": None}

        def _do_compose():
            """
            Thực hiện việc xây dựng ngữ cảnh trong một luồng nền.
            """
            logger.debug("Bắt đầu hàm _do_compose.")
            try:
                context_data["context"] = context_builder.compose_context(self.app_ui, cfg, budget_chars)
            except Exception as e:
                context_data["exception"] = e
                logger.exception(f"Lỗi khi xây dựng ngữ cảnh trong luồng nền: {e}")
            finally:
                context_result.set()

        threading.Thread(target=_do_compose, daemon=True).start()
        
        # Chờ cho đến khi ngữ cảnh được xây dựng xong (có thể thêm timeout nếu cần)
        context_result.wait() # Chặn luồng hiện tại cho đến khi ngữ cảnh sẵn sàng

        if context_data["exception"]:
            raise context_data["exception"]
        
        logger.debug("Kết thúc compose_context.")
        return context_data["context"]

    def _maybe_notify_telegram(
        self,
        app: "TradingToolApp",
        report_text: str,
        report_path: Path | None,
        cfg: "RunConfig",
    ):
        """
        Gửi thông báo qua Telegram nếu tính năng Telegram được bật và báo cáo phân tích
        chứa tín hiệu giao dịch có xác suất cao ("HIGH PROBABILITY").
        Tránh gửi trùng lặp bằng cách sử dụng chữ ký báo cáo.

        Args:
            app: Đối tượng giao diện người dùng (TradingToolApp).
            report_text: Nội dung báo cáo phân tích.
            report_path: Đường dẫn đến file báo cáo (có thể là None).
            cfg: Đối tượng cấu hình RunConfig.
        """
        logger.debug("Bắt đầu hàm _maybe_notify_telegram.")
        logger.debug(f"Bắt đầu _maybe_notify_telegram. Telegram enabled: {cfg.telegram_enabled}, Report text length: {len(report_text) if report_text else 0}.")
        if not cfg.telegram_enabled or not report_text:
            logger.debug("Telegram không được bật hoặc không có báo cáo, bỏ qua gửi Telegram.")
            return

        # Chỉ gửi nếu có tín hiệu "HIGH PROBABILITY" trong báo cáo
        if "HIGH PROBABILITY" not in report_text.upper():
            logger.debug("Báo cáo không chứa 'HIGH PROBABILITY', bỏ qua gửi Telegram.")
            return

        # Tạo một "chữ ký" cho báo cáo để tránh gửi trùng lặp
        signature = report_utils_parser.create_report_signature(report_text)
        if signature == app._last_telegram_signature:
            logger.info(f"Đã gửi báo cáo này trước đó (signature: {signature}), bỏ qua gửi trùng lặp.")
            return
        app._last_telegram_signature = signature
        logger.info(f"Đang gửi thông báo Telegram cho báo cáo (signature: {signature}).")

        # Gửi thông báo trong một luồng riêng biệt
        threading.Thread(
            target=telegram_client.send_telegram_message,
            args=(report_text, report_path, cfg),
            daemon=True,
        ).start()
        logger.debug("Kết thúc _maybe_notify_telegram.")

    def _snapshot_config(self, app: "TradingToolApp") -> "RunConfig":
        """
        Chụp lại toàn bộ trạng thái cấu hình hiện tại từ giao diện người dùng và trả về một đối tượng RunConfig.
        Điều này đảm bảo rằng luồng worker chạy với một cấu hình nhất quán,
        ngay cả khi người dùng thay đổi cài đặt trên giao diện trong lúc đang chạy.

        Args:
            app: Đối tượng giao diện người dùng (TradingToolApp).

        Returns:
            Một đối tượng RunConfig chứa cấu hình hiện tại.
        """
        logger.debug("Bắt đầu hàm _snapshot_config.")
        config = RunConfig(
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
            trade_pending_threshold_points=int(
                app.trade_pending_threshold_points_var.get()
            ),
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
        logger.debug(f"Đã chụp snapshot cấu hình cho news fetch: {config}")
        return config

    def _load_env(self, app: "TradingToolApp"):
        """
        Mở hộp thoại cho người dùng chọn tệp .env và tải biến môi trường từ đó.
        Ưu tiên nạp GOOGLE_API_KEY.

        Args:
            app: Đối tượng giao diện người dùng (TradingToolApp).
        """
        logger.debug("Bắt đầu _load_env.")
        path = filedialog.askopenfilename(
            title="Chọn file .env", filetypes=[("ENV", ".env"), ("Tất cả", "*.*")]
        )
        if not path:
            logger.debug("Người dùng đã hủy chọn file .env.")
            return
        # Nếu thư viện python-dotenv không được cài đặt, đọc tệp theo cách thủ công
        if load_dotenv is None:
            try:
                for line in Path(path).read_text(encoding="utf-8").splitlines():
                    if "=" in line:
                        k, v = line.split("=", 1)
                        if k.strip() == "GOOGLE_API_KEY":
                            app.api_key_var.set(v.strip())
                            logger.info("Đã nạp GOOGLE_API_KEY từ file .env thủ công.")
                            break
                ui_utils.ui_message(
                    app, "info", "ENV", "Đã nạp GOOGLE_API_KEY từ file."
                )
            except Exception as e:
                logger.exception(f"Lỗi khi nạp GOOGLE_API_KEY từ file .env thủ công: {e}")
                ui_utils.ui_message(app, "error", "ENV", str(e))
        # Nếu có python-dotenv, sử dụng nó để tải tất cả các biến
        else:
            load_dotenv(path)
            val = os.environ.get("GOOGLE_API_KEY", "")
            if val:
                app.api_key_var.set(val)
                ui_utils.ui_message(app, "info", "ENV", "Đã nạp GOOGLE_API_KEY từ .env")
                logger.info("Đã nạp GOOGLE_API_KEY từ .env bằng python-dotenv.")
        logger.debug("Kết thúc _load_env.")

    def _save_api_safe(self, app: "TradingToolApp"):
        """
        Mã hóa và lưu API key vào tệp để sử dụng trong các lần chạy sau.

        Args:
            app: Đối tượng giao diện người dùng (TradingToolApp).
        """
        logger.debug("Bắt đầu _save_api_safe.")
        try:
            API_KEY_ENC.write_text(
                obfuscate_text(app.api_key_var.get().strip()), encoding="utf-8"
            )
            ui_utils.ui_message(
                app, "info", "API", f"Đã lưu an toàn vào: {API_KEY_ENC}"
            )
            logger.info(f"Đã lưu an toàn API key vào: {API_KEY_ENC}")
        except Exception as e:
            logger.exception(f"Lỗi khi lưu API key an toàn: {e}")
            ui_utils.ui_message(app, "error", "API", str(e))
        logger.debug("Kết thúc _save_api_safe.")

    def _delete_api_safe(self, app: "TradingToolApp"):
        """
        Xóa tệp chứa API key đã mã hóa khỏi hệ thống.

        Args:
            app: Đối tượng giao diện người dùng (TradingToolApp).
        """
        logger.debug("Bắt đầu _delete_api_safe.")
        try:
            if API_KEY_ENC.exists():
                API_KEY_ENC.unlink()
                logger.info(f"Đã xoá API key đã lưu từ: {API_KEY_ENC}")
            else:
                logger.info("Không tìm thấy file API key đã lưu để xoá.")
            ui_utils.ui_message(app, "info", "API", "Đã xoá API key đã lưu.")
        except Exception as e:
            logger.exception(f"Lỗi khi xoá API key đã lưu: {e}")
            ui_utils.ui_message(app, "error", "API", str(e))
        logger.debug("Kết thúc _delete_api_safe.")

    def start_analysis(self, app: "TradingToolApp"):
        """
        Bắt đầu một phiên phân tích mới.
        Kiểm tra các điều kiện cần thiết, cấu hình Gemini API, và khởi chạy luồng worker
        để thực hiện phân tích ảnh.

        Args:
            app: Đối tượng giao diện người dùng (TradingToolApp).
        """
        logger.debug(f"Bắt đầu start_analysis. App đang chạy: {app.is_running}")
        if app.is_running:
            logger.info("Ứng dụng đã đang chạy, bỏ qua yêu cầu start_analysis.")
            return
        folder = app.folder_path.get().strip()
        if not folder:
            logger.warning("Thiếu thư mục ảnh, không thể bắt đầu phân tích.")
            ui_utils.ui_message(
                app, "warning", "Thiếu thư mục", "Vui lòng chọn thư mục ảnh trước."
            )
            return

        if app.cache_enabled_var.get() and app.delete_after_var.get():
            logger.warning("Cache ảnh đang bật, KHÔNG nên xoá file trên Gemini sau phân tích.")
            ui_utils.ui_status(
                app,
                "Lưu ý: Cache ảnh đang bật, KHÔNG nên xoá file trên Gemini sau phân tích.",
            )

        app.clear_results()
        ui_utils.ui_status(app, "Đang nạp lại ảnh từ thư mục đã chọn...")
        app._load_files(folder)
        if len(app.results) == 0:
            logger.info("Không tìm thấy ảnh nào trong thư mục, không thể bắt đầu phân tích.")
            return

        prompt_no_entry = app.prompt_no_entry_text.get("1.0", "end").strip()
        prompt_entry_run = app.prompt_entry_run_text.get("1.0", "end").strip()

        if not prompt_no_entry or not prompt_entry_run:
            logger.warning("Thiếu nội dung prompt, không thể bắt đầu phân tích.")
            ui_utils.ui_message(
                app,
                "warning",
                "Thiếu prompt",
                "Vui lòng nhập nội dung cho cả hai tab prompt trước khi chạy.",
            )
            return

        cfg = self._snapshot_config(app)
        logger.debug(f"Cấu hình snapshot cho worker: {cfg}")

        # API key đã được cấu hình ở _configure_gemini_api_and_update_ui, không cần cấu hình lại ở đây
        # api_key = app.api_key_var.get().strip() or os.environ.get("GOOGLE_API_KEY")
        # if not api_key:
        #     logger.warning("Thiếu API key, không thể cấu hình Gemini API.")
        #     ui_utils.ui_message(
        #         app,
        #         "warning",
        #         "Thiếu API key",
        #         "Vui lòng nhập API key hoặc đặt biến môi trường GOOGLE_API_KEY.",
        #     )
        #     return
        
        # # Cấu hình API key cho thư viện Gemini
        # try:
        #     genai.configure(api_key=api_key)
        #     logger.debug("Đã cấu hình Gemini API key.")
        # except Exception as e:
        #     logger.exception(f"Lỗi cấu hình API trong start_analysis: {e}")
        #     ui_utils.ui_message(app, "error", "Gemini", f"Lỗi cấu hình API: {e}")
        #     return

        # Đặt lại trạng thái của các kết quả trước khi bắt đầu
        for i, r in enumerate(app.results):
            r["status"] = "Chưa xử lý"
            r["text"] = ""
            app._update_tree_row(i, r["status"])
        app.combined_report_text = ""
        ui_utils.ui_progress(app, 0)
        ui_utils.ui_detail_replace(app, "Đang chuẩn bị phân tích...")
        logger.info("Đang chuẩn bị dữ liệu và khởi chạy worker.")

        app.stop_flag = False
        app.is_running = True
        app.stop_btn.configure(state="normal")

        # Chạy logic phân tích chính trong một luồng riêng biệt
        # và lưu lại tham chiếu đến luồng này
        app.active_worker_thread = threading.Thread(
            target=worker.run_analysis_worker,
            args=(app, prompt_no_entry, prompt_entry_run, app.model_var.get(), cfg),
            daemon=True,
        )
        app.active_worker_thread.start()
        logger.info("Đã khởi chạy luồng phân tích worker.")
        logger.debug("Kết thúc start_analysis.")

    def stop_analysis(self, app: "TradingToolApp"):
        """
        Gửi tín hiệu dừng cho luồng worker đang chạy và hủy các tác vụ upload đang chờ
        trong executor để dừng quá trình phân tích.

        Args:
            app: Đối tượng giao diện người dùng (TradingToolApp).
        """
        logger.debug(f"Bắt đầu stop_analysis. App đang chạy: {app.is_running}")
        if not app.is_running:
            logger.info("Ứng dụng không chạy, bỏ qua yêu cầu stop_analysis.")
            return

        app.stop_flag = True
        ui_utils.ui_status(app, "Đang gửi yêu cầu dừng...")
        logger.info("Đã đặt cờ dừng cho worker.")

        # Hủy các tác vụ upload đang chờ trong executor
        if app.active_executor:
            try:
                # Hủy tất cả các future chưa bắt đầu chạy.
                # wait=False để không chặn luồng UI.
                app.active_executor.shutdown(wait=False, cancel_futures=True)
                ui_utils.ui_status(app, "Đã yêu cầu hủy các tác vụ upload đang chờ.")
                logger.info("Đã yêu cầu hủy các tác vụ upload đang chờ trong executor.")
            except Exception as e:
                logger.exception(f"Lỗi khi shutdown executor: {e}")
                logging.warning(f"Lỗi khi shutdown executor: {e}")
        else:
            ui_utils.ui_status(
                app, "Đang dừng... (Không có tác vụ upload nào đang hoạt động)"
            )
            logger.debug("Không có executor đang hoạt động để shutdown.")

        app.is_running = False
        app.stop_flag = False
        app.active_worker_thread = None
        app.active_executor = None
        app.stop_btn.configure(state="disabled")
        ui_utils.ui_status(app, "Đã hoàn tất phân tích toàn bộ thư mục.")
        logger.info("Đã hoàn tất phân tích toàn bộ thư mục sau khi dừng.")
        self._schedule_next_autorun(app)
        logger.debug("Kết thúc stop_analysis.")

    def _finalize_stopped(self, app: "TradingToolApp"):
        """
        Hoàn tất quá trình phân tích khi người dùng yêu cầu dừng.
        Cập nhật trạng thái giao diện và lên lịch cho lần chạy tự động tiếp theo (nếu bật).

        Args:
            app: Đối tượng giao diện người dùng (TradingToolApp).
        """
        logger.debug("Bắt đầu _finalize_stopped.")
        app.is_running = False
        app.stop_flag = False
        app.active_worker_thread = None
        app.active_executor = None
        app.stop_btn.configure(state="disabled")
        ui_utils.ui_status(app, "Đã dừng.")
        self._schedule_next_autorun(app)
        logger.debug("Kết thúc _finalize_stopped.")

    def _toggle_autorun(self, app: "TradingToolApp"):
        """
        Bật hoặc tắt chế độ tự động chạy phân tích.
        Nếu bật, lên lịch cho lần chạy tiếp theo. Nếu tắt, hủy lịch chạy hiện tại.

        Args:
            app: Đối tượng giao diện người dùng (TradingToolApp).
        """
        logger.debug(f"Bắt đầu _toggle_autorun. Autorun enabled: {app.autorun_var.get()}")
        if app.autorun_var.get():
            self._schedule_next_autorun(app)
            logger.info("Đã bật auto-run.")
        else:
            if app._autorun_job:
                app.root.after_cancel(app._autorun_job)
                app._autorun_job = None
            ui_utils.ui_status(app, "Đã tắt auto-run.")
            logger.info("Đã tắt auto-run.")
        logger.debug("Kết thúc _toggle_autorun.")

    def _autorun_interval_changed(self, app: "TradingToolApp"):
        """
        Xử lý khi khoảng thời gian tự động chạy thay đổi.
        Nếu chế độ tự động chạy đang bật, lên lịch lại cho lần chạy tiếp theo.

        Args:
            app: Đối tượng giao diện người dùng (TradingToolApp).
        """
        logger.debug(f"Bắt đầu _autorun_interval_changed. Autorun enabled: {app.autorun_var.get()}")
        if app.autorun_var.get():
            self._schedule_next_autorun(app)
            logger.info("Khoảng thời gian auto-run đã thay đổi, lên lịch lại.")
        logger.debug("Kết thúc _autorun_interval_changed.")

    def _schedule_next_autorun(self, app: "TradingToolApp"):
        """
        Lên lịch cho lần chạy tự động tiếp theo sau một khoảng thời gian nhất định.

        Args:
            app: Đối tượng giao diện người dùng (TradingToolApp).
        """
        logger.debug("Bắt đầu _schedule_next_autorun.")
        if not app.autorun_var.get():
            logger.debug("Auto-run không được bật, bỏ qua lên lịch.")
            return
        if app._autorun_job:
            app.root.after_cancel(app._autorun_job)
            logger.debug("Đã hủy tác vụ auto-run cũ.")
        secs = max(5, int(app.autorun_seconds_var.get()))
        app._autorun_job = app.root.after(secs * 1000, lambda: self._autorun_tick(app))
        ui_utils.ui_status(app, f"Tự động chạy sau {secs}s.")
        logger.info(f"Đã lên lịch auto-run tiếp theo sau {secs} giây.")
        logger.debug("Kết thúc _schedule_next_autorun.")

    def _autorun_tick(self, app: "TradingToolApp"):
        """
        Hàm được gọi khi đến thời gian tự động chạy.
        Nếu không có phân tích nào đang chạy, bắt đầu một phân tích mới.
        Nếu đang chạy, thực hiện các tác vụ nền như quản lý BE/Trailing.

        Args:
            app: Đối tượng giao diện người dùng (TradingToolApp).
        """
        logger.debug("Bắt đầu _autorun_tick.")
        app._autorun_job = None
        # Nếu không có phân tích nào đang chạy, bắt đầu một phân tích mới.
        if not app.is_running:
            logger.info("Auto-run: Không có phân tích đang chạy, bắt đầu phân tích mới.")
            self.start_analysis(app)
        else:
            logger.info("Auto-run: Đã có phân tích đang chạy, kiểm tra tác vụ nền.")
            # Nếu một phân tích đang chạy, thực hiện các tác vụ nền (nếu được bật)
            # như quản lý trailing stop cho các lệnh đang mở.
            if app.mt5_enabled_var.get() and app.auto_trade_enabled_var.get():
                logger.debug("Auto-run: MT5 và Auto-trade được bật, thực hiện tác vụ nền.")
                cfg_snapshot = self._snapshot_config(app)

                def _sweep(c):
                    logger.debug("Bắt đầu luồng _sweep cho tác vụ nền auto-trade.")
                    try:
                        safe_data = mt5_utils.build_context_from_app(
                            app, plan=None, cfg=c
                        )
                        if safe_data and safe_data.raw:
                            # data = safe_data.raw.get("MT5_DATA", {}) # Biến này không được sử dụng
                            # auto_trade.mt5_manage_be_trailing(app,data, c) # Tạm thời vô hiệu hóa
                            logger.debug("Đã lấy dữ liệu MT5 trong _sweep.")
                            pass
                    except Exception as e:
                        logger.exception(f"Lỗi trong luồng _sweep của auto-trade: {e}")
                        logging.warning(f"Lỗi trong luồng _sweep của auto-trade: {e}")
                    logger.debug("Kết thúc luồng _sweep.")

                threading.Thread(
                    target=_sweep, args=(cfg_snapshot,), daemon=True
                ).start()
            else:
                logger.debug("Auto-run: MT5 hoặc Auto-trade không được bật, bỏ qua tác vụ nền.")
            # Lên lịch cho lần chạy tự động tiếp theo.
            self._schedule_next_autorun(app)
        logger.debug("Kết thúc _autorun_tick.")

    def _pick_mt5_terminal(self, app: "TradingToolApp"):
        """
        Mở hộp thoại cho người dùng chọn đường dẫn đến file thực thi của MetaTrader 5 (terminal64.exe hoặc terminal.exe).

        Args:
            app: Đối tượng giao diện người dùng (TradingToolApp).
        """
        logger.debug("Bắt đầu _pick_mt5_terminal.")
        p = filedialog.askopenfilename(
            title="Chọn terminal64.exe hoặc terminal.exe",
            filetypes=[("MT5 terminal", "terminal*.exe"), ("Tất cả", "*.*")],
        )
        if p:
            app.mt5_term_path_var.set(p)
            logger.info(f"Đã chọn đường dẫn MT5 terminal: {p}")
        else:
            logger.debug("Người dùng đã hủy chọn đường dẫn MT5 terminal.")
        logger.debug("Kết thúc _pick_mt5_terminal.")

    def _mt5_guess_symbol(self, app: "TradingToolApp"):
        """
        Cố gắng đoán biểu tượng (symbol) giao dịch từ tên các file ảnh đã nạp.
        Ví dụ: "EURUSD_H1.png" sẽ đoán là "EURUSD".

        Args:
            app: Đối tượng giao diện người dùng (TradingToolApp).
        """
        logger.debug("Bắt đầu _mt5_guess_symbol.")
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
                logger.info(f"Đã đoán symbol MT5: {app.mt5_symbol_var.get()}")
            else:
                ui_utils.ui_message(
                    app, "info", "MT5", "Không đoán được symbol từ tên file."
                )
                logger.info("Không đoán được symbol MT5 từ tên file.")
        except Exception as e:
            logger.exception(f"Lỗi khi đoán symbol MT5: {e}")
            logging.warning(f"Lỗi khi đoán symbol MT5: {e}")
        logger.debug("Kết thúc _mt5_guess_symbol.")

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
            self._schedule_mt5_reconnect(app)  # Kích hoạt tái kết nối
            return False, msg

    def _mt5_connect(self, app: "TradingToolApp") -> Tuple[bool, str]:
        """
        Khởi tạo kết nối đến MetaTrader 5.
        Trả về trạng thái kết nối (True/False) và thông báo.

        Args:
            app: Đối tượng giao diện người dùng (TradingToolApp).

        Returns:
            Tuple[bool, str]: Trạng thái kết nối (True nếu thành công, False nếu thất bại) và thông báo kết quả.
        """
        logger.debug("Bắt đầu _schedule_mt5_reconnect.")
        if self._mt5_reconnect_job:
            app.root.after_cancel(self._mt5_reconnect_job)
            self._mt5_reconnect_job = None
            logger.debug("Đã hủy tác vụ tái kết nối MT5 cũ.")

        if self._mt5_reconnect_attempts >= self._mt5_max_reconnect_attempts:
            logging.warning(
                "MT5 Reconnect: Đã đạt số lần thử tối đa, dừng tái kết nối."
            )
            ui_utils._enqueue(
                app, lambda: app.mt5_status_var.set("MT5: Tái kết nối thất bại.")
            )
            self._mt5_reconnect_attempts = 0  # Reset để có thể thử lại thủ công
            logger.debug("Kết thúc _schedule_mt5_reconnect (đã đạt số lần thử tối đa).")
            return

        delay = self._mt5_reconnect_delay_sec * (2**self._mt5_reconnect_attempts)
        delay = min(delay, 600)  # Giới hạn độ trễ tối đa 10 phút
        self._mt5_reconnect_attempts += 1

        ui_utils._enqueue(
            app,
            lambda: app.mt5_status_var.set(
                f"MT5: Đang thử tái kết nối ({self._mt5_reconnect_attempts}/{self._mt5_max_reconnect_attempts}) sau {delay}s..."
            ),
        )
        logging.info(
            f"MT5 Reconnect: Lên lịch thử lại sau {delay}s (lần {self._mt5_reconnect_attempts})."
        )

        self._mt5_reconnect_job = app.root.after(
            int(delay * 1000), lambda: self._attempt_mt5_reconnect(app)
        )
        logger.debug("Kết thúc _schedule_mt5_reconnect.")

    def _attempt_mt5_reconnect(self, app: "TradingToolApp"):
        """
        Thực hiện một lần thử tái kết nối MT5.

        Args:
            app: Đối tượng giao diện người dùng (TradingToolApp).
        """
        logging.info("MT5 Reconnect: Đang thực hiện tái kết nối...")
        ok, msg = self._mt5_connect(app)
        if ok:
            logging.info("MT5 Reconnect: Tái kết nối thành công.")
            self._mt5_reconnect_attempts = 0  # Reset số lần thử
            self._schedule_mt5_connection_check(app)  # Bắt đầu kiểm tra định kỳ
        else:
            logging.warning(f"MT5 Reconnect: Tái kết nối thất bại: {msg}")
            self._schedule_mt5_reconnect(app)  # Lên lịch thử lại

    def _schedule_mt5_connection_check(self, app: "TradingToolApp"):
        """
        Lên lịch kiểm tra kết nối MT5 định kỳ.
        """
        logger.debug("Bắt đầu _schedule_mt5_connection_check.")
        if self._mt5_check_connection_job:
            app.root.after_cancel(self._mt5_check_connection_job)
            self._mt5_check_connection_job = None
            logger.debug("Đã hủy tác vụ kiểm tra kết nối MT5 cũ.")

        ui_utils._enqueue(
            app,
            lambda: app.mt5_status_var.set(
                f"MT5: Đã kết nối. Kiểm tra sau {self._mt5_check_interval_sec}s."
            ),
        )
        self._mt5_check_connection_job = app.root.after(
            int(self._mt5_check_interval_sec * 1000),
            lambda: self._check_mt5_connection(app),
        )
        logger.info(f"Đã lên lịch kiểm tra kết nối MT5 sau {self._mt5_check_interval_sec} giây.")
        logger.debug("Kết thúc _schedule_mt5_connection_check.")

    def _check_mt5_connection(self, app: "TradingToolApp"):
        """
        Thực hiện kiểm tra trạng thái kết nối MT5.
        Nếu kết nối bị mất, kích hoạt cơ chế tái kết nối.

        Args:
            app: Đối tượng giao diện người dùng (TradingToolApp).
        """
        logger.debug("Bắt đầu _check_mt5_connection.")
        if not app.mt5_enabled_var.get():
            logger.info("MT5 Check: MT5 không được bật, dừng kiểm tra định kỳ.")
            logger.debug("Kết thúc _check_mt5_connection (MT5 không bật).")
            return

        if mt5 is None:
            logger.warning(
                "MT5 Check: Thư viện MetaTrader5 không có, không thể kiểm tra."
            )
            self._schedule_mt5_reconnect(
                app
            )  # Cố gắng tái kết nối nếu thư viện bị thiếu
            logger.debug("Kết thúc _check_mt5_connection (thiếu thư viện MT5).")
            return

        try:
            if not mt5.initialize():  # Cố gắng khởi tạo lại nếu cần
                logger.warning(
                    "MT5 Check: initialize() thất bại, kết nối có thể bị mất."
                )
                app.mt5_initialized = False
                self._schedule_mt5_reconnect(app)
                logger.debug("Kết thúc _check_mt5_connection (initialize thất bại).")
                return

            # Kiểm tra nhẹ bằng cách lấy thông tin tài khoản
            account_info = mt5.account_info()
            if account_info is None:
                logger.warning(
                    "MT5 Check: Không thể lấy thông tin tài khoản, kết nối có thể bị mất."
                )
                app.mt5_initialized = False
                self._schedule_mt5_reconnect(app)
                logger.debug("Kết thúc _check_mt5_connection (không lấy được account_info).")
                return

            logger.debug("MT5 Check: Kết nối vẫn hoạt động.")
            app.mt5_initialized = True  # Đảm bảo trạng thái được cập nhật
            self._schedule_mt5_connection_check(app)  # Lên lịch kiểm tra tiếp theo
            logger.debug("Kết thúc _check_mt5_connection (thành công).")
        except Exception as e:
            logger.exception(f"MT5 Check Exception: {e}")
            app.mt5_initialized = False
            self._schedule_mt5_reconnect(app)
            logger.debug("Kết thúc _check_mt5_connection (có lỗi ngoại lệ).")

    def _mt5_snapshot_popup(self, app: "TradingToolApp"):
        """
        Hiển thị một cửa sổ popup chứa dữ liệu MetaTrader 5 hiện tại dưới dạng JSON.
        """
        logger.debug("Bắt đầu _mt5_snapshot_popup.")
        safe_data = mt5_utils.build_context_from_app(app, plan=None)
        if not safe_data or not safe_data.raw:
            logger.warning("Không thể lấy dữ liệu MT5 cho snapshot. Kiểm tra kết nối/biểu tượng (Symbol).")
            ui_utils.ui_message(
                app,
                "warning",
                "MT5",
                "Không thể lấy dữ liệu. Kiểm tra kết nối/biểu tượng (Symbol).",
            )
            logger.debug("Kết thúc _mt5_snapshot_popup (không có dữ liệu).")
            return

        # Chuyển đổi dữ liệu thô sang chuỗi JSON có định dạng để hiển thị
        try:
            json_text = json.dumps(safe_data.raw, ensure_ascii=False, indent=2)
            logger.debug("Đã chuyển đổi dữ liệu MT5 sang JSON.")
        except Exception as e:
            logger.exception(f"Lỗi khi định dạng JSON cho MT5 snapshot: {e}")
            json_text = f"Lỗi khi định dạng JSON: {e}\n\nDữ liệu thô:\n{safe_data.raw}"

        win = tk.Toplevel(app.root)
        win.title("MT5 snapshot")
        win.geometry("760x520")
        st = ScrolledText(win, wrap="none")
        st.pack(fill="both", expand=True)
        st.insert("1.0", json_text)
        logger.info("Đã hiển thị MT5 snapshot popup.")
        logger.debug("Kết thúc _mt5_snapshot_popup.")

    def _refresh_news_cache(
        self,
        app: "TradingToolApp",
        ttl: int = 300,
        *,
        async_fetch: bool = True,
        cfg: "RunConfig" | None = None,
    ) -> None:
        """
        Làm mới bộ đệm tin tức từ Forex Factory nếu dữ liệu đã cũ (quá thời gian `ttl`).
        Có thể chạy đồng bộ hoặc không đồng bộ.

        Args:
            app: Đối tượng giao diện người dùng (TradingToolApp).
            ttl: Thời gian sống (Time-To-Live) của cache tin tức bằng giây. Mặc định là 300 giây.
            async_fetch: Nếu True, việc làm mới tin tức sẽ chạy không đồng bộ trong một luồng riêng.
                         Nếu False, nó sẽ chạy đồng bộ. Mặc định là True.
            cfg: Đối tượng RunConfig tùy chọn để sử dụng. Nếu None, cấu hình sẽ được chụp từ UI.
        """
        logger.debug(f"Bắt đầu _refresh_news_cache. Async: {async_fetch}, TTL: {ttl}")
        try:
            now_ts = time.time()
            last_ts = float(app.ff_cache_fetch_time or 0.0)
            if (now_ts - last_ts) <= max(0, int(ttl or 0)):
                logger.debug(f"Cache tin tức vẫn còn hiệu lực ({now_ts - last_ts:.2f}s < {ttl}s), bỏ qua làm mới.")
                logger.debug("Kết thúc _refresh_news_cache (cache còn hiệu lực).")
                return

            # Tạo snapshot config ở luồng chính để đảm bảo an toàn thread
            final_cfg = cfg or self._snapshot_config(app)
            logger.debug(f"Đã tạo snapshot cấu hình cho news fetch: {final_cfg}")

            if async_fetch:
                with app._news_refresh_lock:
                    if app._news_refresh_inflight:
                        logger.debug("Đã có yêu cầu làm mới tin tức đang thực hiện, bỏ qua.")
                        logger.debug("Kết thúc _refresh_news_cache (async, đang inflight).")
                        return
                    app._news_refresh_inflight = True
                logger.info("Đang làm mới tin tức không đồng bộ.")

                def _do_async(config: RunConfig):
                    logger.debug("Bắt đầu luồng _do_async để fetch tin tức.")
                    try:
                        ev = news.fetch_high_impact_events_for_cfg(config, timeout=20)
                        app.ff_cache_events_local = ev or []
                        app.ff_cache_fetch_time = time.time()
                        logger.info(f"Đã làm mới tin tức không đồng bộ, tìm thấy {len(ev or [])} sự kiện.")
                    except Exception as e:
                        logger.exception(f"Lỗi khi làm mới tin tức (async): {e}")
                        logging.warning(f"Lỗi khi làm mới tin tức (async): {e}")
                    finally:
                        with app._news_refresh_lock:
                            app._news_refresh_inflight = False
                        logger.debug("Kết thúc luồng _do_async.")

                threading.Thread(
                    target=_do_async, args=(final_cfg,), daemon=True
                ).start()
                logger.debug("Kết thúc _refresh_news_cache (async, đã khởi chạy luồng).")
                return

            # Logic chạy đồng bộ (synchronous)
            if not app._news_refresh_lock.acquire(blocking=False):
                logger.debug("Đã có yêu cầu làm mới tin tức đang thực hiện (sync), bỏ qua.")
                logger.debug("Kết thúc _refresh_news_cache (sync, đang inflight).")
                return
            logger.info("Đang làm mới tin tức đồng bộ.")

            try:
                app._news_refresh_inflight = True
                ev = news.fetch_high_impact_events_for_cfg(final_cfg, timeout=20)
                app.ff_cache_events_local = ev or []
                app.ff_cache_fetch_time = time.time()
                logger.info(f"Đã làm mới tin tức đồng bộ, tìm thấy {len(ev or [])} sự kiện.")
            except Exception as e:
                logger.exception(f"Lỗi khi làm mới tin tức (sync): {e}")
                logging.warning(f"Lỗi khi làm mới tin tức (sync): {e}")
            finally:
                app._news_refresh_inflight = False
                app._news_refresh_lock.release()
            logger.debug("Kết thúc _refresh_news_cache (sync).")
        except Exception as e:
            logger.exception(f"Lỗi không mong muốn trong refresh_news_cache: {e}")
            logging.error(f"Lỗi không mong muốn trong refresh_news_cache: {e}")
        logger.debug("Kết thúc _refresh_news_cache (tổng thể).")
