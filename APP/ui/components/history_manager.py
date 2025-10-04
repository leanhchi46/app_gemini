from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from APP.ui.utils import ui_builder

if TYPE_CHECKING:
    from APP.ui.app_ui import AppUI

logger = logging.getLogger(__name__)


class HistoryManager:
    def __init__(self, app: "AppUI"):
        self.app = app
        self.app._history_files = []
        self.app.json_files = []

    def refresh_history_list(self):
        """Làm mới danh sách các báo cáo lịch sử (report_*.md)."""
        if not hasattr(self.app, "history_list"):
            return
        self.app.history_list.delete(0, "end")
        reports_dir = self.app.get_reports_dir()
        if reports_dir:
            files = sorted(reports_dir.glob("report_*.md"), reverse=True)
            self.app._history_files = list(files)
            for p in files:
                self.app.history_list.insert("end", p.name)

    def preview_history_selected(self):
        """Hiển thị nội dung của báo cáo lịch sử được chọn."""
        sel = self.app.history_list.curselection()
        if not sel:
            return
        p = self.app._history_files[sel[0]]
        try:
            txt = p.read_text(encoding="utf-8", errors="ignore")
            ui_builder.detail_replace(self.app, txt)
            self.app.status_var.set(f"Xem: {p.name}")
        except Exception as e:
            ui_builder.message(self.app, "error", "History", str(e))

    def open_history_selected(self):
        """Mở báo cáo lịch sử được chọn."""
        sel = self.app.history_list.curselection()
        if not sel:
            return
        p = self.app._history_files[sel[0]]
        ui_builder.open_path(self.app, p)

    def delete_history_selected(self):
        """Xóa báo cáo lịch sử được chọn."""
        sel = self.app.history_list.curselection()
        if not sel:
            return
        p = self.app._history_files[sel[0]]
        try:
            p.unlink()
            self.refresh_history_list()
            ui_builder.detail_replace(self.app, "")
            self.app.status_var.set(f"Đã xóa: {p.name}")
        except Exception as e:
            ui_builder.message(self.app, "error", "History", str(e))

    def open_reports_folder(self):
        """Mở thư mục Reports."""
        reports_dir = self.app.get_reports_dir()
        if reports_dir:
            ui_builder.open_path(self.app, reports_dir)

    def refresh_json_list(self):
        """Làm mới danh sách các tệp ngữ cảnh JSON (ctx_*.json)."""
        if not hasattr(self.app, "json_list"):
            return
        self.app.json_list.delete(0, "end")
        reports_dir = self.app.get_reports_dir()
        if reports_dir:
            files = sorted(reports_dir.glob("ctx_*.json"), reverse=True)
            self.app.json_files = list(files)
            for p in files:
                self.app.json_list.insert("end", p.name)

    def preview_json_selected(self):
        """Hiển thị nội dung của tệp JSON được chọn."""
        sel = self.app.json_list.curselection()
        if not sel:
            return
        p = self.app.json_files[sel[0]]
        try:
            txt = p.read_text(encoding="utf-8", errors="ignore")
            ui_builder.detail_replace(self.app, txt)
            self.app.status_var.set(f"Xem JSON: {p.name}")
        except Exception as e:
            ui_builder.message(self.app, "error", "JSON", str(e))

    def delete_json_selected(self):
        """Xóa tệp JSON được chọn."""
        sel = self.app.json_list.curselection()
        if not sel:
            return
        p = self.app.json_files[sel[0]]
        try:
            p.unlink()
            self.refresh_json_list()
            ui_builder.detail_replace(self.app, "")
            self.app.status_var.set(f"Đã xóa JSON: {p.name}")
        except Exception as e:
            ui_builder.message(self.app, "error", "JSON", str(e))
