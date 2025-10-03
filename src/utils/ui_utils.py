from __future__ import annotations
import tkinter as tk
from tkinter import messagebox
from typing import TYPE_CHECKING
import queue
import json
import os
from datetime import datetime
import logging # Thêm import logging
from pathlib import Path # Thêm import Path
import sys # Thêm import sys

logger = logging.getLogger(__name__) # Khởi tạo logger

if TYPE_CHECKING:
    from scripts.tool import TradingToolApp

def _enqueue(app: "TradingToolApp", func):
    """
    Thêm một hàm vào hàng đợi để được thực thi an toàn trên luồng UI chính.

    Args:
        app: Đối tượng ứng dụng chính.
        func: Hàm cần được thực thi.
    """
    logger.debug(f"Enqueueing function: {func.__name__ if hasattr(func, '__name__') else 'lambda'}")
    app.ui_queue.put(func)

def _log_status(app: "TradingToolApp", text: str):
    """
    Ghi lại một thông điệp trạng thái vào log (chạy trong luồng riêng).

    Args:
        app: Đối tượng ứng dụng chính.
        text: Thông điệp trạng thái cần ghi.
    """
    logger.debug(f"Bắt đầu _log_status cho text: {text}")
    # Lấy giá trị symbol ở luồng chính để tránh lỗi RuntimeError
    try:
        folder_override = app.mt5_symbol_var.get().strip() or None
        logger.debug(f"Folder override cho log status: {folder_override}")
    except Exception as e:
        folder_override = None
        logger.warning(f"Lỗi khi lấy mt5_symbol_var cho log status: {e}")

    def _do_log(folder: str | None):
        try:
            app._log_trade_decision({
                "stage": "status_update",
                "t": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "message": text
            }, folder_override=folder)
            logger.debug("Đã log trade decision cho status update.")
        except Exception as e:
            logger.error(f"Lỗi khi log trade decision từ _log_status: {e}")
            pass
    
    import threading
    threading.Thread(target=_do_log, args=(folder_override,), daemon=True).start()
    logger.debug("Kết thúc _log_status.")

def ui_status(app: "TradingToolApp", text: str):
    """
    Cập nhật thanh trạng thái trên UI và ghi log.

    Args:
        app: Đối tượng ứng dụng chính.
        text: Văn bản trạng thái cần hiển thị.
    """
    logger.debug(f"Cập nhật UI status: {text}")
    _enqueue(app, lambda: app.status_var.set(text))
    _log_status(app, text)

def ui_detail_replace(app: "TradingToolApp", text: str):
    """
    Thay thế toàn bộ nội dung trong ô văn bản chi tiết.

    Args:
        app: Đối tượng ứng dụng chính.
        text: Văn bản mới để hiển thị.
    """
    logger.debug(f"Cập nhật UI detail text. Độ dài: {len(text)}")
    _enqueue(app, lambda: (
        app.detail_text.config(state="normal"),
        app.detail_text.delete("1.0", "end"),
        app.detail_text.insert("1.0", text),
        app.detail_text.see("end")
    ))

def ui_message(app: "TradingToolApp", kind: str, title: str, text: str):
    """
    Hiển thị một hộp thoại thông báo (info, warning, error).

    Args:
        app: Đối tượng ứng dụng chính.
        kind: Loại thông báo ("info", "warning", "error").
        title: Tiêu đề của hộp thoại.
        text: Nội dung của thông báo.
    """
    logger.debug(f"Hiển thị UI message. Kind: {kind}, Title: {title}, Text: {text}")
    _enqueue(app, lambda: getattr(messagebox, f"show{kind}", messagebox.showinfo)(title, text))

def ui_widget_state(app: "TradingToolApp", widget: Any, state: str):
    """
    Thay đổi trạng thái của một widget (ví dụ: 'normal', 'disabled').

    Args:
        app: Đối tượng ứng dụng chính.
        widget: Widget cần thay đổi trạng thái.
        state: Trạng thái mới ("normal", "disabled", v.v.).
    """
    logger.debug(f"Thay đổi trạng thái widget {widget} thành: {state}")
    _enqueue(app, lambda: widget.configure(state=state))

def ui_progress(app: "TradingToolApp", pct: float, status: Optional[str] = None):
    """
    Cập nhật thanh tiến trình.

    Args:
        app: Đối tượng ứng dụng chính.
        pct: Phần trăm tiến độ (0.0 đến 100.0).
        status: Văn bản trạng thái tùy chọn để hiển thị cùng với tiến trình.
    """
    logger.debug(f"Cập nhật UI progress: {pct:.1f}%, status: {status}")
    def _act():
        app.progress_var.set(pct)
        if status is not None:
            app.status_var.set(status)
    _enqueue(app, _act)

def ui_refresh_history_list(app: "TradingToolApp"):
    """
    Yêu cầu làm mới danh sách lịch sử trên UI.

    Args:
        app: Đối tượng ứng dụng chính.
    """
    logger.debug("Yêu cầu làm mới history list.")
    _enqueue(app, app._refresh_history_list)

def ui_refresh_json_list(app: "TradingToolApp"):
    """
    Yêu cầu làm mới danh sách JSON trên UI.

    Args:
        app: Đối tượng ứng dụng chính.
    """
    logger.debug("Yêu cầu làm mới JSON list.")
    _enqueue(app, app._refresh_json_list)

def _open_path(app: "TradingToolApp", path: Path):
    """
    Mở một tệp hoặc thư mục bằng ứng dụng mặc định của hệ điều hành.
    Hỗ trợ các hệ điều hành Windows, macOS và Linux.

    Args:
        app: Đối tượng ứng dụng chính.
        path: Đường dẫn đến tệp hoặc thư mục cần mở.
    """
    logger.debug(f"Bắt đầu _open_path cho path: {path}")
    try:
        if os.name == "nt":  # Windows
            os.startfile(path)
        elif os.name == "posix":  # macOS, Linux
            import subprocess
            subprocess.call(["open", path]) if sys.platform == "darwin" else subprocess.call(["xdg-open", path])
        else:
            raise RuntimeError(f"Hệ điều hành không được hỗ trợ: {os.name}")
        logger.info(f"Đã mở path thành công: {path}")
    except Exception as e:
        ui_message(app, "error", "Lỗi Mở File", f"Không thể mở {path}:\n{e}")
        logger.error(f"Lỗi khi mở path '{path}': {e}")
    finally:
        logger.debug("Kết thúc _open_path.")

def _poll_ui_queue(app: "TradingToolApp"):
    """
    Kiểm tra hàng đợi UI định kỳ và thực thi các hàm đang chờ.
    Đây là cơ chế cốt lõi để cập nhật giao diện từ luồng phụ một cách an toàn.

    Args:
        app: Đối tượng ứng dụng chính.
    """
    try:
        while True:
            func = app.ui_queue.get_nowait()
            func()
            logger.debug(f"Đã thực thi hàm từ UI queue: {func.__name__ if hasattr(func, '__name__') else 'lambda'}")
    except queue.Empty:
        # Hàng đợi trống, đây là trường hợp hoạt động bình thường, không phải lỗi.
        pass
    except Exception as e:
        logger.error(f"Lỗi trong _poll_ui_queue: {e}")
    finally:
        # Luôn lên lịch cho lần kiểm tra tiếp theo để giữ cho vòng lặp UI hoạt động.
        app.root.after(80, lambda: _poll_ui_queue(app))
