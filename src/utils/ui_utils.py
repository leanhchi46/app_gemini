from __future__ import annotations
import tkinter as tk
from tkinter import messagebox
from typing import TYPE_CHECKING
import queue
import json
import os
from datetime import datetime
from src.config.constants import APP_DIR

if TYPE_CHECKING:
    from scripts.tool import TradingToolApp

def _enqueue(app: "TradingToolApp", func):
    """Thêm một hàm vào hàng đợi để được thực thi an toàn trên luồng UI chính."""
    app.ui_queue.put(func)

def _log_status(app: "TradingToolApp", text: str):
    """Ghi lại một thông điệp trạng thái vào log (chạy trong luồng riêng)."""
    # Lấy giá trị symbol ở luồng chính để tránh lỗi RuntimeError
    try:
        folder_override = app.mt5_symbol_var.get().strip() or None
    except Exception:
        folder_override = None

    def _do_log(folder: str | None):
        try:
            app._log_trade_decision({
                "stage": "status_update",
                "t": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "message": text
            }, folder_override=folder)
        except Exception:
            pass
    
    import threading
    threading.Thread(target=_do_log, args=(folder_override,), daemon=True).start()

def ui_status(app: "TradingToolApp", text: str):
    """Cập nhật thanh trạng thái trên UI và ghi log."""
    _enqueue(app, lambda: app.status_var.set(text))
    _log_status(app, text)

def ui_detail_replace(app: "TradingToolApp", text: str):
    """Thay thế toàn bộ nội dung trong ô văn bản chi tiết."""
    _enqueue(app, lambda: (
        app.detail_text.config(state="normal"),
        app.detail_text.delete("1.0", "end"),
        app.detail_text.insert("1.0", text),
        app.detail_text.see("end")
    ))

def ui_message(app: "TradingToolApp", kind: str, title: str, text: str):
    """Hiển thị một hộp thoại thông báo (info, warning, error)."""
    _enqueue(app, lambda: getattr(messagebox, f"show{kind}", messagebox.showinfo)(title, text))

def ui_widget_state(app: "TradingToolApp", widget, state: str):
    """Thay đổi trạng thái của một widget (ví dụ: 'normal', 'disabled')."""
    _enqueue(app, lambda: widget.configure(state=state))

def ui_progress(app: "TradingToolApp", pct: float, status: str = None):
    """Cập nhật thanh tiến trình."""
    def _act():
        app.progress_var.set(pct)
        if status is not None:
            app.status_var.set(status)
    _enqueue(app, _act)

def ui_refresh_history_list(app: "TradingToolApp"):
    """Yêu cầu làm mới danh sách lịch sử trên UI."""
    _enqueue(app, app._refresh_history_list)

def ui_refresh_json_list(app: "TradingToolApp"):
    """Yêu cầu làm mới danh sách JSON trên UI."""
    _enqueue(app, app._refresh_json_list)

def _poll_ui_queue(app: "TradingToolApp"):
    """
    Kiểm tra hàng đợi UI định kỳ và thực thi các hàm đang chờ.
    Đây là cơ chế cốt lõi để cập nhật giao diện từ luồng phụ một cách an toàn.
    """
    try:
        while True:
            func = app.ui_queue.get_nowait()
            func()
    except queue.Empty:
        # Hàng đợi trống, đây là trường hợp hoạt động bình thường, không phải lỗi.
        pass
    finally:
        # Luôn lên lịch cho lần kiểm tra tiếp theo để giữ cho vòng lặp UI hoạt động.
        app.root.after(80, lambda: _poll_ui_queue(app))
