# src/ui/history_manager.py
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from src.utils import ui_utils

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from src.ui.app_ui import TradingToolApp


def _get_reports_dir(app: "TradingToolApp", folder_override: str | None = None) -> Path:
    """
    Lấy đường dẫn đến thư mục "Reports" bên trong thư mục ảnh đã chọn.
    Nếu thư mục chưa tồn tại, nó sẽ được tạo.
    """
    logger.debug(f"Bắt đầu _get_reports_dir. Folder override: {folder_override}")
    folder = Path(folder_override) if folder_override else (Path(app.folder_path.get().strip()) if app.folder_path.get().strip() else None)
    if not folder:
        logger.warning("Không có folder path, không thể lấy reports dir.")
        return None
    d = folder / "Reports"
    d.mkdir(parents=True, exist_ok=True)
    logger.debug(f"Đã lấy reports dir: {d}")
    return d

def _refresh_history_list(app: "TradingToolApp"):
    """
    Làm mới danh sách các báo cáo lịch sử (file report_*.md) trong thư mục "Reports"
    và hiển thị chúng trên giao diện.
    """
    logger.debug("Bắt đầu _refresh_history_list.")
    if not hasattr(app, "history_list"):
        logger.warning("app không có thuộc tính history_list.")
        return
    app.history_list.delete(0, "end")
    d = _get_reports_dir(app)
    if d: # Thêm kiểm tra d
        files = sorted(d.glob("report_*.md"), reverse=True)
        app._history_files = list(files)
        for p in files:
            app.history_list.insert("end", p.name)
        logger.debug(f"Đã làm mới history list với {len(files)} file.")
    else:
        app._history_files = []
        logger.warning("Không thể làm mới history list vì không có thư mục reports hợp lệ.")

def _preview_history_selected(app: "TradingToolApp"):
    """
    Hiển thị nội dung của báo cáo lịch sử được chọn trong khu vực chi tiết trên giao diện.
    """
    logger.debug("Bắt đầu _preview_history_selected.")
    sel = getattr(app, "history_list", None).curselection() if hasattr(app, "history_list") else None
    if not sel:
        logger.debug("Không có báo cáo lịch sử nào được chọn.")
        return
    p = app._history_files[sel[0]]
    try:
        txt = p.read_text(encoding="utf-8", errors="ignore")
        app.detail_text.config(state="normal")
        app.detail_text.delete("1.0", "end")
        app.detail_text.insert("1.0", txt)
        ui_utils.ui_status(app, f"Xem: {p.name}")
        logger.debug(f"Đã xem trước báo cáo lịch sử: {p.name}")
    except Exception as e:
        ui_utils.ui_message(app, "error", "History", str(e))
        logger.error(f"Lỗi khi xem trước báo cáo lịch sử '{p.name}': {e}")
    finally:
        logger.debug("Kết thúc _preview_history_selected.")

def _open_history_selected(app: "TradingToolApp"):
    """
    Mở báo cáo lịch sử được chọn bằng ứng dụng mặc định của hệ điều hành.
    """
    logger.debug("Bắt đầu _open_history_selected.")
    sel = app.history_list.curselection()
    if not sel:
        logger.debug("Không có báo cáo lịch sử nào được chọn để mở.")
        return
    p = app._history_files[sel[0]]
    try:
        ui_utils._open_path(app, p)
        logger.debug(f"Đã mở báo cáo lịch sử: {p.name}")
    except Exception as e:
        ui_utils.ui_message(app, "error", "History", str(e))
        logger.error(f"Lỗi khi mở báo cáo lịch sử '{p.name}': {e}")
    finally:
        logger.debug("Kết thúc _open_history_selected.")

def _delete_history_selected(app: "TradingToolApp"):
    """
    Xóa báo cáo lịch sử được chọn khỏi hệ thống và làm mới danh sách trên giao diện.
    """
    logger.debug("Bắt đầu _delete_history_selected.")
    sel = app.history_list.curselection()
    if not sel:
        logger.debug("Không có báo cáo lịch sử nào được chọn để xóa.")
        return
    p = app._history_files[sel[0]]
    try:
        p.unlink()
        _refresh_history_list(app)
        app.detail_text.delete("1.0", "end")
        ui_utils.ui_status(app, f"Đã xóa: {p.name}")
        logger.debug(f"Đã xóa báo cáo lịch sử: {p.name}")
    except Exception as e:
        ui_utils.ui_message(app, "error", "History", str(e))
        logger.error(f"Lỗi khi xóa báo cáo lịch sử '{p.name}': {e}")
    finally:
        logger.debug("Kết thúc _delete_history_selected.")

def _open_reports_folder(app: "TradingToolApp"):
    """
    Mở thư mục "Reports" bằng ứng dụng mặc định của hệ điều hành.
    """
    logger.debug("Bắt đầu _open_reports_folder.")
    d = _get_reports_dir(app)
    if d:
        ui_utils._open_path(app, d)
        logger.debug(f"Đã mở thư mục reports: {d}")
    else:
        logger.warning("Không thể mở thư mục reports vì đường dẫn không hợp lệ.")
    logger.debug("Kết thúc _open_reports_folder.")

def _refresh_json_list(app: "TradingToolApp"):
    """
    Làm mới danh sách các file JSON ngữ cảnh (ctx_*.json) trong thư mục "Reports"
    và hiển thị chúng trên giao diện.
    """
    logger.debug("Bắt đầu _refresh_json_list.")
    if not hasattr(app, "json_list"):
        logger.warning("app không có thuộc tính json_list.")
        return
    app.json_list.delete(0, "end")
    d = _get_reports_dir(app)
    if d: # Thêm kiểm tra d
        files = sorted(d.glob("ctx_*.json"), reverse=True)
        app.json_files = list(files)
        for p in files:
            app.json_list.insert("end", p.name)
        logger.debug(f"Đã làm mới JSON list với {len(files)} file.")
    else:
        app.json_files = []
        logger.warning("Không thể làm mới JSON list vì không có thư mục reports hợp lệ.")

def _preview_json_selected(app: "TradingToolApp"):
    """
    Hiển thị nội dung của file JSON ngữ cảnh được chọn trong khu vực chi tiết trên giao diện.
    """
    logger.debug("Bắt đầu _preview_json_selected.")
    sel = getattr(app, "json_list", None).curselection() if hasattr(app, "json_list") else None
    if not sel:
        logger.debug("Không có file JSON nào được chọn.")
        return
    p = app.json_files[sel[0]]
    try:
        txt = p.read_text(encoding="utf-8", errors="ignore")
        app.detail_text.config(state="normal")
        app.detail_text.delete("1.0", "end")
        app.detail_text.insert("1.0", txt)
        ui_utils.ui_status(app, f"Xem JSON: {p.name}")
        logger.debug(f"Đã xem trước file JSON: {p.name}")
    except Exception as e:
        ui_utils.ui_message(app, "error", "JSON", str(e))
        logger.error(f"Lỗi khi xem trước file JSON '{p.name}': {e}")
    finally:
        logger.debug("Kết thúc _preview_json_selected.")

def _load_json_selected(app: "TradingToolApp"):
    """
    Mở file JSON ngữ cảnh được chọn bằng ứng dụng mặc định của hệ điều hành.
    """
    logger.debug("Bắt đầu _load_json_selected.")
    sel = app.json_list.curselection()
    if not sel:
        logger.debug("Không có file JSON nào được chọn để mở.")
        return
    p = app.json_files[sel[0]]
    try:
        ui_utils._open_path(app, p)
        logger.debug(f"Đã mở file JSON: {p.name}")
    except Exception as e:
        ui_utils.ui_message(app, "error", "JSON", str(e))
        logger.error(f"Lỗi khi mở file JSON '{p.name}': {e}")
    finally:
        logger.debug("Kết thúc _load_json_selected.")

def _delete_json_selected(app: "TradingToolApp"):
    """
    Xóa file JSON ngữ cảnh được chọn khỏi hệ thống và làm mới danh sách trên giao diện.
    """
    logger.debug("Bắt đầu _delete_json_selected.")
    sel = app.json_list.curselection()
    if not sel:
        logger.debug("Không có file JSON nào được chọn để xóa.")
        return
    p = app.json_files[sel[0]]
    try:
        p.unlink()
        _refresh_json_list(app)
        app.detail_text.delete("1.0", "end")
        ui_utils.ui_status(app, f"Đã xóa JSON: {p.name}")
        logger.debug(f"Đã xóa file JSON: {p.name}")
    except Exception as e:
        ui_utils.ui_message(app, "error", "JSON", str(e))
        logger.error(f"Lỗi khi xóa file JSON '{p.name}': {e}")
    finally:
        logger.debug("Kết thúc _delete_json_selected.")

def _open_json_folder(app: "TradingToolApp"):
    """
    Mở thư mục chứa các file JSON ngữ cảnh bằng ứng dụng mặc định của hệ điều hành.
    """
    logger.debug("Bắt đầu _open_json_folder.")
    d = _get_reports_dir(app)
    if d:
        ui_utils._open_path(app, d)
        logger.debug(f"Đã mở thư mục JSON: {d}")
    else:
        logger.warning("Không thể mở thư mục JSON vì đường dẫn không hợp lệ.")
    logger.debug("Kết thúc _open_json_folder.")
