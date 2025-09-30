# src/ui/history_manager.py
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from src.utils import ui_utils

if TYPE_CHECKING:
    import tkinter as tk
    from src.ui.app_ui import TradingToolApp


def _get_reports_dir(app: "TradingToolApp", folder_override: str | None = None) -> Path:
    """
    Lấy đường dẫn đến thư mục "Reports" bên trong thư mục ảnh đã chọn.
    Nếu thư mục chưa tồn tại, nó sẽ được tạo.
    """
    folder = Path(folder_override) if folder_override else (Path(app.folder_path.get().strip()) if app.folder_path.get().strip() else None)
    if not folder:
        return None
    d = folder / "Reports"
    d.mkdir(parents=True, exist_ok=True)
    return d

def _refresh_history_list(app: "TradingToolApp"):
    """
    Làm mới danh sách các báo cáo lịch sử (file report_*.md) trong thư mục "Reports"
    và hiển thị chúng trên giao diện.
    """
    if not hasattr(app, "history_list"):
        return
    app.history_list.delete(0, "end")
    d = _get_reports_dir(app)
    files = sorted(d.glob("report_*.md"), reverse=True) if d else []
    app._history_files = list(files)
    for p in files:
        app.history_list.insert("end", p.name)

def _preview_history_selected(app: "TradingToolApp"):
    """
    Hiển thị nội dung của báo cáo lịch sử được chọn trong khu vực chi tiết trên giao diện.
    """
    sel = getattr(app, "history_list", None).curselection() if hasattr(app, "history_list") else None
    if not sel:
        return
    p = app._history_files[sel[0]]
    try:
        txt = p.read_text(encoding="utf-8", errors="ignore")
        app.detail_text.config(state="normal")
        app.detail_text.delete("1.0", "end")
        app.detail_text.insert("1.0", txt)
        ui_utils.ui_status(app, f"Xem: {p.name}")
    except Exception as e:
        ui_utils.ui_message(app, "error", "History", str(e))

def _open_history_selected(app: "TradingToolApp"):
    """
    Mở báo cáo lịch sử được chọn bằng ứng dụng mặc định của hệ điều hành.
    """
    sel = app.history_list.curselection()
    if not sel:
        return
    p = app._history_files[sel[0]]
    try:
        ui_utils._open_path(app, p)
    except Exception as e:
        ui_utils.ui_message(app, "error", "History", str(e))

def _delete_history_selected(app: "TradingToolApp"):
    """
    Xóa báo cáo lịch sử được chọn khỏi hệ thống và làm mới danh sách trên giao diện.
    """
    sel = app.history_list.curselection()
    if not sel:
        return
    p = app._history_files[sel[0]]
    try:
        p.unlink()
        _refresh_history_list(app)
        app.detail_text.delete("1.0", "end")
    except Exception as e:
        ui_utils.ui_message(app, "error", "History", str(e))

def _open_reports_folder(app: "TradingToolApp"):
    """
    Mở thư mục "Reports" bằng ứng dụng mặc định của hệ điều hành.
    """
    d = _get_reports_dir(app)
    if d:
        ui_utils._open_path(app, d)

def _refresh_json_list(app: "TradingToolApp"):
    """
    Làm mới danh sách các file JSON ngữ cảnh (ctx_*.json) trong thư mục "Reports"
    và hiển thị chúng trên giao diện.
    """
    if not hasattr(app, "json_list"):
        return
    app.json_list.delete(0, "end")
    d = _get_reports_dir(app)
    files = sorted(d.glob("ctx_*.json"), reverse=True) if d else []
    app.json_files = list(files)
    for p in files:
        app.json_list.insert("end", p.name)

def _preview_json_selected(app: "TradingToolApp"):
    """
    Hiển thị nội dung của file JSON ngữ cảnh được chọn trong khu vực chi tiết trên giao diện.
    """
    sel = getattr(app, "json_list", None).curselection() if hasattr(app, "json_list") else None
    if not sel:
        return
    p = app.json_files[sel[0]]
    try:
        txt = p.read_text(encoding="utf-8", errors="ignore")
        app.detail_text.config(state="normal")
        app.detail_text.delete("1.0", "end")
        app.detail_text.insert("1.0", txt)
        ui_utils.ui_status(app, f"Xem JSON: {p.name}")
    except Exception as e:
        ui_utils.ui_message(app, "error", "JSON", str(e))

def _load_json_selected(app: "TradingToolApp"):
    """
    Mở file JSON ngữ cảnh được chọn bằng ứng dụng mặc định của hệ điều hành.
    """
    sel = app.json_list.curselection()
    if not sel:
        return
    p = app.json_files[sel[0]]
    try:
        ui_utils._open_path(app, p)
    except Exception as e:
        ui_utils.ui_message(app, "error", "JSON", str(e))

def _delete_json_selected(app: "TradingToolApp"):
    """
    Xóa file JSON ngữ cảnh được chọn khỏi hệ thống và làm mới danh sách trên giao diện.
    """
    sel = app.json_list.curselection()
    if not sel:
        return
    p = app.json_files[sel[0]]
    try:
        p.unlink()
        _refresh_json_list(app)
        app.detail_text.delete("1.0", "end")
    except Exception as e:
        ui_utils.ui_message(app, "error", "JSON", str(e))

def _open_json_folder(app: "TradingToolApp"):
    """
    Mở thư mục chứa các file JSON ngữ cảnh bằng ứng dụng mặc định của hệ điều hành.
    """
    d = _get_reports_dir(app)
    if d:
        ui_utils._open_path(app, d)
