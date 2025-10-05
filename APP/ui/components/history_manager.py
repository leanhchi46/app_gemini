# -*- coding: utf-8 -*-
"""
Quản lý việc hiển thị và tương tác với lịch sử báo cáo và các tệp ngữ cảnh.

Lớp HistoryManager đóng gói tất cả logic liên quan đến việc làm mới, xem trước,
mở và xóa các tệp báo cáo (.md) và tệp ngữ cảnh (.json) từ giao diện người dùng.
"""

from __future__ import annotations

import logging
import tkinter as tk
from typing import TYPE_CHECKING, Callable, Optional

if TYPE_CHECKING:
    from APP.ui.app_ui import AppUI

from APP.configs import workspace_config
from APP.ui.utils import ui_builder

logger = logging.getLogger(__name__)


class HistoryManager:
    """
    Quản lý các thành phần UI liên quan đến lịch sử giao dịch và ngữ cảnh.
    """

    def __init__(self, app: "AppUI") -> None:
        """
        Khởi tạo HistoryManager.

        Args:
            app (AppUI): Instance của ứng dụng chính.
        """
        self.app = app
        self.logger = logging.getLogger(__name__)

    # --- Private Helper Methods (Refactored) ---

    def _refresh_file_list(
        self, listbox: Optional[tk.Listbox], file_glob: str, target_attr: str
    ) -> None:
        """
        Hàm chung để làm mới danh sách tệp trên một Listbox cụ thể.
        """
        self.logger.debug(f"Bắt đầu làm mới danh sách cho mẫu: {file_glob}")
        if not listbox:
            return
        try:
            listbox.delete(0, "end")
            base_folder = self.app.folder_path.get()

            if not base_folder:
                self.logger.warning("Thư mục gốc chưa được đặt, không thể làm mới danh sách.")
                setattr(self.app, target_attr, [])
                return

            # Logic được chuẩn hóa: phụ thuộc vào base_folder và symbol hiện tại.
            symbol = self.app.mt5_symbol_var.get()
            reports_dir = workspace_config.get_reports_dir(base_folder, symbol)
            
            # Sử dụng is_dir() để kiểm tra chính xác hơn
            if not reports_dir.is_dir():
                self.logger.warning(f"Thư mục báo cáo không tồn tại tại '{reports_dir}' cho symbol '{symbol}', không thể làm mới {target_attr}.")
                setattr(self.app, target_attr, [])
                return

            files = sorted(reports_dir.glob(file_glob), reverse=True)
            setattr(self.app, target_attr, list(files))
            for p in files:
                listbox.insert("end", p.name)
            self.logger.debug(f"Đã làm mới {target_attr} với {len(files)} tệp.")
        except Exception as e:
            self.logger.error(f"Lỗi khi làm mới danh sách tệp ({file_glob}): {e}", exc_info=True)
            ui_builder.show_message(
                "Lỗi", f"Không thể làm mới danh sách tệp:\n{e}"
            )

    def _preview_selected_file(self, listbox: Optional[tk.Listbox], file_list_attr: str, file_type: str) -> None:
        """
        Hàm chung để hiển thị nội dung của tệp được chọn.
        """
        self.logger.debug(f"Bắt đầu xem trước tệp loại: {file_type}")
        if not listbox or not self.app.detail_text:
            return
        file_path = None
        try:
            sel = listbox.curselection()
            if not sel:
                return

            file_list = getattr(self.app, file_list_attr, [])
            if not file_list or sel[0] >= len(file_list):
                return
            file_path = file_list[sel[0]]
            content = file_path.read_text(encoding="utf-8", errors="ignore")

            self.app.detail_text.config(state="normal")
            self.app.detail_text.delete("1.0", "end")
            self.app.detail_text.insert("1.0", content)
            self.app.detail_text.config(state="disabled")

            self.app.ui_status(f"Đang xem {file_type}: {file_path.name}")
            self.logger.debug(f"Đã hiển thị xem trước cho: {file_path.name}")
        except IndexError:
            self.logger.warning(f"Lựa chọn không hợp lệ cho {file_type}, có thể danh sách đã thay đổi.")
        except Exception as e:
            error_msg = f"Lỗi khi xem trước {file_type}"
            if file_path:
                error_msg += f" '{file_path.name}'"
            self.logger.error(f"{error_msg}: {e}", exc_info=True)
            ui_builder.show_message("Lỗi", f"Không thể xem trước tệp:\n{e}")

    def _delete_selected_file(self, listbox: Optional[tk.Listbox], file_list_attr: str, refresh_func: Callable[[], None], file_type: str) -> None:
        """
        Hàm chung để xóa tệp được chọn.
        """
        self.logger.debug(f"Bắt đầu xóa tệp loại: {file_type}")
        if not listbox or not self.app.detail_text:
            return
        file_path = None
        try:
            sel = listbox.curselection()
            if not sel:
                return

            file_list = getattr(self.app, file_list_attr, [])
            if not file_list or sel[0] >= len(file_list):
                return
            file_path = file_list[sel[0]]

            if ui_builder.ask_confirmation(
                title="Xác nhận Xóa", message=f"Bạn có chắc chắn muốn xóa tệp:\n{file_path.name}?"
            ):
                file_path.unlink()
                refresh_func()
                self.app.detail_text.config(state="normal")
                self.app.detail_text.delete("1.0", "end")
                self.app.detail_text.config(state="disabled")
                self.app.ui_status(f"Đã xóa {file_type}: {file_path.name}")
                self.logger.info(f"Đã xóa {file_type}: {file_path.name}")
        except Exception as e:
            error_msg = f"Lỗi khi xóa {file_type}"
            if file_path:
                error_msg += f" '{file_path.name}'"
            self.logger.error(f"{error_msg}: {e}", exc_info=True)
            ui_builder.show_message("Lỗi", f"Không thể xóa tệp:\n{e}")

    def _open_selected_file(self, listbox: Optional[tk.Listbox], file_list_attr: str, file_type: str) -> None:
        """
        Hàm chung để mở tệp được chọn bằng ứng dụng mặc định của hệ điều hành.
        """
        self.logger.debug(f"Bắt đầu mở tệp loại: {file_type}")
        if not listbox:
            return
        file_path = None
        try:
            sel = listbox.curselection()
            if not sel:
                return
            file_list = getattr(self.app, file_list_attr, [])
            if not file_list or sel[0] >= len(file_list):
                return
            file_path = file_list[sel[0]]

            # Mở file bằng os.startfile để tương thích tốt hơn trên Windows
            import os
            os.startfile(file_path)

            self.logger.debug(f"Đã yêu cầu mở tệp: {file_path}")
        except Exception as e:
            error_msg = f"Lỗi khi mở {file_type}"
            if file_path:
                error_msg += f" '{file_path.name}'"
            self.logger.error(f"{error_msg}: {e}", exc_info=True)
            ui_builder.show_message("Lỗi", f"Không thể mở tệp:\n{e}")

    # --- Public Methods for MD Reports ---

    def refresh_history_list(self) -> None:
        """Làm mới danh sách các báo cáo lịch sử (report_*.md) và hiển thị trên UI."""
        self._refresh_file_list(self.app.history_list, "report_*.md", "_history_files")

    def preview_history_selected(self) -> None:
        """Hiển thị nội dung của báo cáo lịch sử được chọn."""
        self._preview_selected_file(self.app.history_list, "_history_files", "Báo cáo")

    def open_history_selected(self) -> None:
        """Mở báo cáo lịch sử được chọn bằng ứng dụng mặc định."""
        self._open_selected_file(self.app.history_list, "_history_files", "Báo cáo")

    def delete_history_selected(self) -> None:
        """Xóa báo cáo lịch sử được chọn."""
        self._delete_selected_file(
            self.app.history_list, "_history_files", self.refresh_history_list, "Báo cáo"
        )

    def open_reports_folder(self) -> None:
        """Mở thư mục chứa các báo cáo và tệp ngữ cảnh."""
        self.logger.debug("Bắt đầu mở thư mục báo cáo.")
        try:
            base_folder = self.app.folder_path.get()
            if not base_folder:
                ui_builder.show_message("Thông báo", "Vui lòng chọn thư mục ảnh trước.")
                return

            # Logic đã được chuẩn hóa: Sử dụng symbol hiện tại.
            symbol = self.app.mt5_symbol_var.get()
            reports_dir = workspace_config.get_reports_dir(base_folder, symbol)
            if reports_dir.is_dir():
                import os
                os.startfile(reports_dir)
                self.logger.debug(f"Đã yêu cầu mở thư mục: {reports_dir}")
            else:
                self.logger.warning(f"Thư mục báo cáo không tồn tại tại: {reports_dir}")
                ui_builder.show_message("Thông báo", "Thư mục báo cáo không tồn tại.")
        except Exception as e:
            self.logger.error(f"Lỗi khi mở thư mục báo cáo: {e}", exc_info=True)
            ui_builder.show_message(
                "Lỗi", f"Không thể mở thư mục báo cáo:\n{e}"
            )

    # --- Public Methods for JSON Context Files ---

    def refresh_json_list(self) -> None:
        """Làm mới danh sách các tệp JSON ngữ cảnh (ctx_*.json) và hiển thị trên UI."""
        self._refresh_file_list(self.app.json_list, "ctx_*.json", "_json_files")

    def preview_json_selected(self) -> None:
        """Hiển thị nội dung của tệp JSON được chọn."""
        self._preview_selected_file(self.app.json_list, "_json_files", "JSON")

    def open_json_selected(self) -> None:
        """Mở tệp JSON được chọn bằng ứng dụng mặc định."""
        self._open_selected_file(self.app.json_list, "_json_files", "JSON")

    def delete_json_selected(self) -> None:
        """Xóa tệp JSON được chọn."""
        self._delete_selected_file(
            self.app.json_list, "_json_files", self.refresh_json_list, "JSON"
        )

    def open_json_folder(self) -> None:
        """Mở thư mục chứa các tệp JSON."""
        self.logger.debug("Bắt đầu mở thư mục JSON.")
        # Re-use the same folder as reports
        self.open_reports_folder()
