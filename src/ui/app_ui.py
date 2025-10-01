# src/ui/app_ui.py
from __future__ import annotations

import tkinter as tk
from tkinter import filedialog
from tkinter.scrolledtext import ScrolledText
from pathlib import Path
import os # Cần cho os.environ.get
import queue # Cần cho self.ui_queue
import threading # Cần cho threading.Lock
from datetime import datetime # Cần cho export_markdown
from typing import TYPE_CHECKING, Optional
import logging # Thêm import logging
import google.generativeai as genai # Thêm import genai

# Để tránh lỗi import vòng tròn, sử dụng TYPE_CHECKING cho type hints
if TYPE_CHECKING:
    from src.core.app_logic import AppLogic
    from src.config.config import RunConfig
    from src.utils.safe_data import SafeMT5Data

from src.config.constants import (
    DEFAULT_MODEL, # Cần cho self.model_var
    API_KEY_ENC,   # Cần cho api_init
    SUPPORTED_EXTS # Cần cho _load_files
)
from src.utils.utils import (
    deobfuscate_text, # Cần cho api_init
)
from src.utils import ui_utils
from src.utils import ui_builder
from src.utils import report_parser # Giữ lại vì một số hàm vẫn dùng trực tiếp
from src.utils import mt5_utils # Cần cho _mt5_build_context
from src.ui import history_manager
from src.ui import prompt_manager
from src.ui import timeframe_detector
from src.config import workspace_manager


class TradingToolApp:
    """
    Lớp chính điều khiển giao diện và luồng hoạt động của ứng dụng.
    """
    def __init__(self, root: tk.Tk, app_logic: "AppLogic"):
        """
        Khởi tạo giao diện chính và các biến trạng thái của ứng dụng.
        """
        self.root = root
        self.app_logic = app_logic # Tham chiếu đến lớp logic nghiệp vụ
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
        
        # Lên lịch kiểm tra kết nối MT5 ban đầu khi ứng dụng khởi động
        self.app_logic._schedule_mt5_connection_check(self)

        # Đảm bảo hủy các tác vụ hẹn giờ khi đóng ứng dụng và lưu workspace
        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)

    def _on_closing(self):
        """
        Xử lý sự kiện đóng cửa sổ ứng dụng.
        Hủy bỏ tất cả các tác vụ hẹn giờ đang chạy và lưu workspace.
        """
        if self.app_logic._mt5_reconnect_job:
            self.root.after_cancel(self.app_logic._mt5_reconnect_job)
            self.app_logic._mt5_reconnect_job = None
        if self.app_logic._mt5_check_connection_job:
            self.root.after_cancel(self.app_logic._mt5_check_connection_job)
            self.app_logic._mt5_check_connection_job = None
        
        # Lưu workspace trước khi đóng
        self._save_workspace()
        
        self.root.destroy()

    def _init_tk_variables(self):
        """
        Khởi tạo tất cả các biến trạng thái của Tkinter.
        Các biến này được liên kết với các widget trong giao diện người dùng để quản lý dữ liệu và trạng thái.
        """
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

    def compose_context(self, cfg: "RunConfig", budget_chars: int) -> str:
        """
        Hợp nhất các thành phần ngữ cảnh (dữ liệu MT5, báo cáo cũ, tin tức) để tạo chuỗi ngữ cảnh hoàn chỉnh
        cung cấp cho mô hình AI.
        """
        return self.app_logic.compose_context(cfg, budget_chars)

    def _images_tf_map(self, names: list[str]) -> dict[str, str]:
        """
        Tạo một bản đồ (dictionary) từ tên file ảnh sang khung thời gian (timeframe) tương ứng
        bằng cách sử dụng hàm _detect_timeframe_from_name.
        """
        return timeframe_detector.images_tf_map(names, self._detect_timeframe_from_name)

    def ui_status(self, message: str):
        """
        Cập nhật thông báo trạng thái trên giao diện người dùng.
        """
        ui_utils.ui_status(self, message)

    def _refresh_news_cache(self, ttl: int = 300, *, async_fetch: bool = True, cfg: "RunConfig" | None = None) -> None:
        """
        Làm mới bộ đệm tin tức từ Forex Factory nếu dữ liệu đã cũ (quá thời gian `ttl`).
        Có thể chạy đồng bộ hoặc không đồng bộ.
        """
        self.app_logic._refresh_news_cache(self, ttl, async_fetch=async_fetch, cfg=cfg)

    def _toggle_api_visibility(self):
        """
        Chuyển đổi trạng thái hiển thị (ẩn/hiện) của ô nhập API key trên giao diện.
        """
        self.api_entry.configure(show="" if self.api_entry.cget("show") == "*" else "*")

    def _log_trade_decision(self, data: dict, folder_override: str | None = None):
        """
        Ghi lại các quyết định hoặc sự kiện quan trọng vào file log JSONL.
        Sử dụng khóa (lock) để đảm bảo an toàn khi ghi file từ nhiều luồng.
        """
        self.app_logic._log_trade_decision(self, data, folder_override)

    def _maybe_notify_telegram(self, report_text: str, report_path: Path | None, cfg: "RunConfig"):
        """
        Gửi thông báo qua Telegram nếu tính năng Telegram được bật và báo cáo phân tích
        chứa tín hiệu giao dịch có xác suất cao ("HIGH PROBABILITY").
        Tránh gửi trùng lặp bằng cách sử dụng chữ ký báo cáo.
        """
        self.app_logic._maybe_notify_telegram(self, report_text, report_path, cfg)

    def _snapshot_config(self) -> "RunConfig":
        """
        Chụp lại toàn bộ trạng thái cấu hình hiện tại từ giao diện người dùng và trả về một đối tượng RunConfig.
        Điều này đảm bảo rằng luồng worker chạy với một cấu hình nhất quán,
        ngay cả khi người dùng thay đổi cài đặt trên giao diện trong lúc đang chạy.
        """
        return self.app_logic._snapshot_config(self)

    def _load_env(self):
        """
        Mở hộp thoại cho người dùng chọn tệp .env và tải biến môi trường từ đó.
        Ưu tiên nạp GOOGLE_API_KEY.
        """
        self.app_logic._load_env(self)

    def _save_api_safe(self):
        """
        Mã hóa và lưu API key vào tệp để sử dụng trong các lần chạy sau.
        """
        self.app_logic._save_api_safe(self)

    def _delete_api_safe(self):
        """
        Xóa tệp chứa API key đã mã hóa khỏi hệ thống.
        """
        self.app_logic._delete_api_safe(self)

    def _get_reports_dir(self, folder_override: str | None = None) -> Path:
        """
        Lấy đường dẫn đến thư mục "Reports" bên trong thư mục ảnh đã chọn.
        Nếu thư mục chưa tồn tại, nó sẽ được tạo.
        """
        return history_manager._get_reports_dir(self, folder_override)

    def choose_folder(self):
        """
        Mở hộp thoại cho người dùng chọn thư mục chứa ảnh.
        Sau khi chọn, tải danh sách tệp và làm mới các danh sách lịch sử/JSON.
        """
        folder = filedialog.askdirectory(title="Chọn thư mục chứa ảnh")
        if not folder:
            return
        self.folder_path.set(folder)
        self._load_files(folder)
        history_manager._refresh_history_list(self)
        history_manager._refresh_json_list(self)

    def _load_files(self, folder):
        """
        Xóa kết quả cũ và quét thư mục được chọn (bao gồm cả thư mục con)
        để tìm các tệp ảnh hợp lệ (có phần mở rộng được hỗ trợ).
        Cập nhật danh sách tệp trên giao diện.
        """
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
        """
        Bắt đầu một phiên phân tích mới.
        Kiểm tra các điều kiện cần thiết, cấu hình Gemini API, và khởi chạy luồng worker
        để thực hiện phân tích ảnh.
        """
        self.app_logic.start_analysis(self)

    def stop_analysis(self):
        """
        Gửi tín hiệu dừng cho luồng worker đang chạy và hủy các tác vụ upload đang chờ
        trong executor để dừng quá trình phân tích.
        """
        self.app_logic.stop_analysis(self)

    def _find_balanced_json_after(self, text: str, start_idx: int):
        """
        Tìm và trích xuất một khối JSON cân bằng (balanced JSON block) từ một chuỗi văn bản,
        bắt đầu từ một chỉ mục cụ thể.
        """
        return report_parser.find_balanced_json_after(text, start_idx)

    def _extract_json_block_prefer(self, text: str):
        """
        Trích xuất khối JSON từ một chuỗi văn bản, ưu tiên các khối JSON hoàn chỉnh và hợp lệ.
        """
        return report_parser.extract_json_block_prefer(text)

    def _coerce_setup_from_json(self, obj):
        """
        Chuyển đổi một đối tượng Python (thường là từ JSON) thành đối tượng TradeSetup.
        """
        return report_parser.coerce_setup_from_json(obj)

    def _parse_float(self, s: str):
        """
        Phân tích một chuỗi thành số thực (float).
        """
        return report_parser.parse_float(s)

    def _parse_direction_from_line1(self, line1: str):
        """
        Phân tích hướng giao dịch (Buy/Sell) từ dòng đầu tiên của báo cáo.
        """
        return report_parser.parse_direction_from_line1(line1)

    def _maybe_delete(self, uploaded_file):
        """
        Thực hiện xóa file đã upload lên Gemini nếu cấu hình cho phép.
        """
        self.app_logic._maybe_delete(uploaded_file)

    def _update_progress(self, done_steps, total_steps):
        """
        Cập nhật thanh tiến trình và trạng thái trên giao diện người dùng.
        """
        pct = (done_steps / max(total_steps, 1)) * 100.0
        ui_utils._enqueue(self, lambda: (self.progress_var.set(pct), self.status_var.set(f"Tiến độ: {pct:.1f}%")))

    def _update_tree_row(self, idx, status):
        """
        Cập nhật trạng thái của một hàng (file) trong bảng hiển thị trên giao diện.
        """
        def action():
            iid = str(idx)
            if self.tree.exists(iid):
                vals = list(self.tree.item(iid, "values"))
                vals = [idx + 1, self.results[idx]["name"], status] if len(vals) < 3 else [vals[0], vals[1], status]
                self.tree.item(iid, values=vals)
        ui_utils._enqueue(self, action)

    def _finalize_done(self):
        """
        Hoàn tất quá trình phân tích khi tất cả các file đã được xử lý.
        Ghi log kết thúc, cập nhật trạng thái giao diện và lên lịch cho lần chạy tự động tiếp theo (nếu bật).
        """
        self.app_logic._finalize_stopped(self)

    def _finalize_stopped(self):
        """
        Hoàn tất quá trình phân tích khi người dùng yêu cầu dừng.
        Cập nhật trạng thái giao diện và lên lịch cho lần chạy tự động tiếp theo (nếu bật).
        """
        self.app_logic._finalize_stopped(self)

    def _on_tree_select(self, _evt):
        """
        Xử lý sự kiện khi người dùng chọn một hàng trong bảng hiển thị file.
        Hiển thị báo cáo tổng hợp hoặc thông báo tương ứng.
        """
        self.detail_text.delete("1.0", "end")
        if self.combined_report_text.strip():
            self.detail_text.insert("1.0", self.combined_report_text)
        else:
            self.detail_text.insert("1.0", "Chưa có báo cáo. Hãy bấm 'Bắt đầu'.")

    def export_markdown(self):
        """
        Xuất báo cáo phân tích tổng hợp ra file Markdown.
        Mở hộp thoại lưu file để người dùng chọn vị trí và tên file.
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
            ui_utils.ui_message(self, "info", "Thành công", f"Đã lưu: {out_path}")
        except Exception as e:
            ui_utils.ui_message(self, "error", "Lỗi ghi file", str(e))

    def clear_results(self):
        """
        Xóa tất cả các kết quả phân tích hiện có khỏi giao diện và bộ nhớ.
        """
        self.results.clear()
        self.combined_report_text = ""
        if hasattr(self, "tree"):
            self.tree.delete(*self.tree.get_children())
        if hasattr(self, "detail_text"):
            ui_utils.ui_detail_replace(self, "Báo cáo tổng hợp sẽ hiển thị tại đây sau khi phân tích.")
        ui_utils.ui_progress(self, 0)
        ui_utils.ui_status(self, "Đã xoá kết quả khỏi giao diện.")

    def _refresh_history_list(self):
        """
        Làm mới danh sách các báo cáo lịch sử (file report_*.md) trong thư mục "Reports"
        và hiển thị chúng trên giao diện.
        """
        history_manager._refresh_history_list(self)

    def _preview_history_selected(self):
        """
        Hiển thị nội dung của báo cáo lịch sử được chọn trong khu vực chi tiết trên giao diện.
        """
        history_manager._preview_history_selected(self)

    def _open_history_selected(self):
        """
        Mở báo cáo lịch sử được chọn bằng ứng dụng mặc định của hệ điều hành.
        """
        history_manager._open_history_selected(self)

    def _open_path(self, path: Path):
        """
        Mở một tệp hoặc thư mục bằng ứng dụng mặc định của hệ điều hành.
        Hỗ trợ các hệ điều hành Windows, macOS và Linux.
        """
        ui_utils._open_path(self, path)

    def _delete_history_selected(self):
        """
        Xóa báo cáo lịch sử được chọn khỏi hệ thống và làm mới danh sách trên giao diện.
        """
        history_manager._delete_history_selected(self)

    def _open_reports_folder(self):
        """
        Mở thư mục "Reports" bằng ứng dụng mặc định của hệ điều hành.
        """
        history_manager._open_reports_folder(self)

    def _refresh_json_list(self):
        """
        Làm mới danh sách các file JSON ngữ cảnh (ctx_*.json) trong thư mục "Reports"
        và hiển thị chúng trên giao diện.
        """
        history_manager._refresh_json_list(self)

    def _preview_json_selected(self):
        """
        Hiển thị nội dung của file JSON ngữ cảnh được chọn trong khu vực chi tiết trên giao diện.
        """
        history_manager._preview_json_selected(self)

    def _load_json_selected(self):
        """
        Mở file JSON ngữ cảnh được chọn bằng ứng dụng mặc định của hệ điều hành.
        """
        history_manager._load_json_selected(self)

    def _delete_json_selected(self):
        """
        Xóa file JSON ngữ cảnh được chọn khỏi hệ thống và làm mới danh sách trên giao diện.
        """
        history_manager._delete_json_selected(self)

    def _open_json_folder(self):
        """
        Mở thư mục chứa các file JSON ngữ cảnh bằng ứng dụng mặc định của hệ điều hành.
        """
        history_manager._open_json_folder(self)

    def _detect_timeframe_from_name(self, name: str) -> str:
        """
        Phát hiện khung thời gian (timeframe) từ tên file ảnh bằng cách sử dụng các mẫu regex.
        Ví dụ: "EURUSD_M5.png" sẽ trả về "M5".
        """
        return timeframe_detector._detect_timeframe_from_name(name)

    def _build_timeframe_section(self, names):
        """
        Xây dựng một chuỗi văn bản liệt kê các file ảnh và khung thời gian tương ứng của chúng.
        """
        return timeframe_detector._build_timeframe_section(names)

    def _toggle_autorun(self):
        """
        Bật hoặc tắt chế độ tự động chạy phân tích.
        Nếu bật, lên lịch cho lần chạy tiếp theo. Nếu tắt, hủy lịch chạy hiện tại.
        """
        self.app_logic._toggle_autorun(self)

    def _autorun_interval_changed(self):
        """
        Xử lý khi khoảng thời gian tự động chạy thay đổi.
        Nếu chế độ tự động chạy đang bật, lên lịch lại cho lần chạy tiếp theo.
        """
        self.app_logic._autorun_interval_changed(self)

    def _schedule_next_autorun(self):
        """
        Lên lịch cho lần chạy tự động tiếp theo sau một khoảng thời gian nhất định.
        """
        self.app_logic._schedule_next_autorun(self)

    def _autorun_tick(self):
        """
        Hàm được gọi khi đến thời gian tự động chạy.
        Nếu không có phân tích nào đang chạy, bắt đầu một phân tích mới.
        Nếu đang chạy, thực hiện các tác vụ nền như quản lý BE/Trailing.
        """
        self.app_logic._autorun_tick(self)

    def _pick_mt5_terminal(self):
        """
        Mở hộp thoại cho người dùng chọn đường dẫn đến file thực thi của MetaTrader 5 (terminal64.exe hoặc terminal.exe).
        """
        self.app_logic._pick_mt5_terminal(self)

    def _mt5_guess_symbol(self):
        """
        Cố gắng đoán biểu tượng (symbol) giao dịch từ tên các file ảnh đã nạp.
        Ví dụ: "EURUSD_H1.png" sẽ đoán là "EURUSD".
        """
        self.app_logic._mt5_guess_symbol(self)

    def _mt5_connect(self):
        """
        Gọi logic kết nối MT5 và cập nhật UI dựa trên kết quả.
        """
        ok, msg = self.app_logic._mt5_connect(self)
        if ok:
            ui_utils._enqueue(self, lambda: self.mt5_status_var.set(msg))
            ui_utils.ui_message(self, "info", "MT5", "Kết nối thành công.")
            self.app_logic._schedule_mt5_connection_check(self) # Bắt đầu kiểm tra định kỳ khi kết nối thành công
        else:
            ui_utils._enqueue(self, lambda: self.mt5_status_var.set(msg))
            ui_utils.ui_message(self, "error", "MT5", msg)

    def _mt5_build_context(self, plan=None, cfg: "RunConfig" | None = None) -> Optional["SafeMT5Data"]:
        """
        Xây dựng đối tượng ngữ cảnh MetaTrader 5 (SafeMT5Data) chứa dữ liệu thị trường hiện tại
        (giá nến, thông tin tài khoản, các lệnh đang mở...).
        """
        return mt5_utils.build_context_from_app(self, plan, cfg)

    def _mt5_snapshot_popup(self):
        """
        Hiển thị một cửa sổ popup chứa dữ liệu MetaTrader 5 hiện tại dưới dạng JSON.
        """
        self.app_logic._mt5_snapshot_popup(self)

    def _extract_text_from_obj(self, obj):
        """
        Trích xuất tất cả các chuỗi văn bản từ một đối tượng Python (dict, list, str)
        một cách đệ quy và nối chúng lại thành một chuỗi duy nhất.
        """
        return prompt_manager._extract_text_from_obj(obj)

    def _normalize_prompt_text(self, raw: str) -> str:
        """
        Chuẩn hóa văn bản prompt đầu vào.
        Cố gắng phân tích dưới dạng JSON hoặc đối tượng Python, sau đó trích xuất văn bản.
        Nếu không thành công, trả về văn bản gốc.
        """
        return prompt_manager._normalize_prompt_text(raw)

    def _reformat_prompt_area(self):
        """
        Định dạng lại nội dung của khu vực nhập prompt hiện tại (tab "No Entry" hoặc "Entry/Run")
        bằng cách chuẩn hóa văn bản.
        """
        prompt_manager._reformat_prompt_area(self)

    def _load_prompts_from_disk(self, silent=False):
        """
        Tải nội dung các file prompt từ đĩa (`prompt_no_entry.txt` và `prompt_entry_run.txt`)
        và hiển thị chúng trên các tab prompt tương ứng.
        """
        prompt_manager._load_prompts_from_disk(self, silent)

    def _save_current_prompt_to_disk(self):
        """
        Lưu nội dung của prompt hiện tại (trên tab đang chọn) vào file tương ứng trên đĩa.
        """
        prompt_manager._save_current_prompt_to_disk(self)

    def _save_workspace(self):
        """
        Lưu toàn bộ cấu hình và trạng thái hiện tại của ứng dụng vào file `workspace.json`.
        Các thông tin nhạy cảm như Telegram token được mã hóa trước khi lưu.
        """
        workspace_manager._save_workspace(self)

    def _load_workspace(self):
        """
        Tải cấu hình và trạng thái ứng dụng từ file `workspace.json` khi khởi động.
        Giải mã các thông tin nhạy cảm đã được mã hóa.
        """
        workspace_manager._load_workspace(self)

    def _delete_workspace(self):
        """
        Xóa file `workspace.json` khỏi hệ thống.
        """
        workspace_manager._delete_workspace(self)

    def _update_model_list_in_ui(self):
        """
        Cập nhật danh sách các mô hình AI khả dụng trong Combobox trên UI.
        """
        try:
            # Cấu hình API Key trước khi gọi list_models
            genai.configure(api_key=self.api_key_var.get())

            available_models = []
            for m in genai.list_models():
                if "generateContent" in m.supported_generation_methods:
                    available_models.append(m.name)
            
            if available_models:
                self.model_combo['values'] = available_models
                # Nếu mô hình hiện tại không còn khả dụng, đặt lại về mô hình đầu tiên
                if self.model_var.get() not in available_models:
                    self.model_var.set(available_models[0])
                self.ui_status("Đã cập nhật danh sách mô hình AI.")
            else:
                self.ui_status("Không tìm thấy mô hình AI khả dụng nào.")
        except Exception as e:
            self.ui_status(f"Lỗi khi cập nhật danh sách mô hình AI: {e}")
            logging.error(f"Lỗi khi cập nhật danh sách mô hình AI: {e}")
