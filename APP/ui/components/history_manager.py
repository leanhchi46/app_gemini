# -*- coding: utf-8 -*-
"""
Quản lý việc hiển thị và tương tác với lịch sử báo cáo và các tệp ngữ cảnh.

Lớp HistoryManager đóng gói tất cả logic liên quan đến việc làm mới, xem trước,
mở và xóa các tệp báo cáo (.md) và tệp ngữ cảnh (.json) từ giao diện người dùng.
"""

from __future__ import annotations

import logging
import tkinter as tk
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from APP.ui.app_ui import AppUI

from APP.configs import workspace_config
from APP.ui.utils import ui_builder
from APP.utils import general_utils

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
        self, listbox: tk.Listbox, file_glob: str, target_attr: str
    ) -> None:
        """
        Hàm chung để làm mới danh sách tệp trên một Listbox cụ thể.

        Args:
            listbox (tk.Listbox): Widget Listbox cần cập nhật.
            file_glob (str): Mẫu glob để tìm kiếm tệp (ví dụ: "report_*.md").
            target_attr (str): Tên thuộc tính trên `app` để lưu danh sách tệp (ví dụ: "_history_files").
        """
        self.logger.debug(f"Bắt đầu làm mới danh sách cho mẫu: {file_glob}")
        try:
            listbox.delete(0, "end")
            reports_dir = workspace_config.get_reports_dir()
            if not reports_dir or not reports_dir.exists():
                self.logger.warning(f"Thư mục báo cáo không tồn tại, không thể làm mới {target_attr}.")
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
                title="Lỗi", message=f"Không thể làm mới danh sách tệp:\n{e}"
            )

    def _preview_selected_file(self, listbox: tk.Listbox, file_list_attr: str, file_type: str) -> None:
        """
        Hàm chung để hiển thị nội dung của tệp được chọn.

        Args:
            listbox (tk.Listbox): Widget Listbox chứa lựa chọn.
            file_list_attr (str): Tên thuộc tính trên `app` chứa danh sách tệp.
            file_type (str): Loại tệp để hiển thị trong thanh trạng thái (ví dụ: "Báo cáo").
        """
        self.logger.debug(f"Bắt đầu xem trước tệp loại: {file_type}")
        file_path = None
        try:
            sel = listbox.curselection()
            if not sel:
                return

            file_list = getattr(self.app, file_list_attr)
            file_path = file_list[sel[0]]
            content = file_path.read_text(encoding="utf-8", errors="ignore")

            self.app.detail_text.config(state="normal")
            self.app.detail_text.delete("1.0", "end")
            self.app.detail_text.insert("1.0", content)
            self.app.detail_text.config(state="disabled")

            ui_builder.update_status_bar(self.app.status_bar, f"Đang xem {file_type}: {file_path.name}")
            self.logger.debug(f"Đã hiển thị xem trước cho: {file_path.name}")
        except IndexError:
            self.logger.warning(f"Lựa chọn không hợp lệ cho {file_type}, có thể danh sách đã thay đổi.")
        except Exception as e:
            error_msg = f"Lỗi khi xem trước {file_type}"
            if file_path:
                error_msg += f" '{file_path.name}'"
            self.logger.error(f"{error_msg}: {e}", exc_info=True)
            ui_builder.show_message(title="Lỗi", message=f"Không thể xem trước tệp:\n{e}")

    def _delete_selected_file(self, listbox: tk.Listbox, file_list_attr: str, refresh_func: callable, file_type: str) -> None:
        """
        Hàm chung để xóa tệp được chọn.

        Args:
            listbox (tk.Listbox): Widget Listbox chứa lựa chọn.
            file_list_attr (str): Tên thuộc tính trên `app` chứa danh sách tệp.
            refresh_func (callable): Hàm để gọi để làm mới danh sách sau khi xóa.
            file_type (str): Loại tệp để hiển thị trong thông báo.
        """
        self.logger.debug(f"Bắt đầu xóa tệp loại: {file_type}")
        file_path = None
        try:
            sel = listbox.curselection()
            if not sel:
                return

            file_list = getattr(self.app, file_list_attr)
            file_path = file_list[sel[0]]

            if ui_builder.ask_confirmation(
                title="Xác nhận Xóa", message=f"Bạn có chắc chắn muốn xóa tệp:\n{file_path.name}?"
            ):
                file_path.unlink()
                refresh_func()
                self.app.detail_text.config(state="normal")
                self.app.detail_text.delete("1.0", "end")
                self.app.detail_text.config(state="disabled")
                ui_builder.update_status_bar(self.app.status_bar, f"Đã xóa {file_type}: {file_path.name}")
                self.logger.info(f"Đã xóa {file_type}: {file_path.name}")
        except Exception as e:
            error_msg = f"Lỗi khi xóa {file_type}"
            if file_path:
                error_msg += f" '{file_path.name}'"
            self.logger.error(f"{error_msg}: {e}", exc_info=True)
            ui_builder.show_message(title="Lỗi", message=f"Không thể xóa tệp:\n{e}")

    # --- Public Methods for MD Reports ---

    def refresh_history_list(self) -> None:
        """Làm mới danh sách các báo cáo lịch sử (report_*.md) và hiển thị trên UI."""
        self._refresh_file_list(self.app.history_list, "report_*.md", "_history_files")

    def preview_history_selected(self) -> None:
        """Hiển thị nội dung của báo cáo lịch sử được chọn."""
        self._preview_selected_file(self.app.history_list, "_history_files", "Báo cáo")

    def open_history_selected(self) -> None:
        """Mở báo cáo lịch sử được chọn bằng ứng dụng mặc định."""
        self.logger.debug("Bắt đầu mở tệp báo cáo được chọn.")
        file_path = None
        try:
            sel = self.app.history_list.curselection()
            if not sel:
                return
            file_path = self.app._history_files[sel[0]]
            general_utils.open_path(file_path)
            self.logger.debug(f"Đã yêu cầu mở tệp: {file_path}")
        except Exception as e:
            error_msg = "Lỗi khi mở báo cáo"
            if file_path:
                error_msg += f" '{file_path.name}'"
            self.logger.error(f"{error_msg}: {e}", exc_info=True)
            ui_builder.show_message(title="Lỗi", message=f"Không thể mở tệp:\n{e}")

    def delete_history_selected(self) -> None:
        """Xóa báo cáo lịch sử được chọn."""
        self._delete_selected_file(
            self.app.history_list, "_history_files", self.refresh_history_list, "Báo cáo"
        )

    def open_reports_folder(self) -> None:
        """Mở thư mục chứa các báo cáo và tệp ngữ cảnh."""
        self.logger.debug("Bắt đầu mở thư mục báo cáo.")
        try:
            reports_dir = workspace_config.get_reports_dir()
            if reports_dir and reports_dir.exists():
                general_utils.open_path(reports_dir)
                self.logger.debug(f"Đã yêu cầu mở thư mục: {reports_dir}")
            else:
                self.logger.warning("Thư mục báo cáo không tồn tại.")
                ui_builder.show_message(title="Thông báo", message="Thư mục báo cáo không tồn tại.")
        except Exception as e:
            self.logger.error(f"Lỗi khi mở thư mục báo cáo: {e}", exc_info=True)
            ui_builder.show_message(
                title="Lỗi", message=f"Không thể mở thư mục báo cáo:\n{e}"
            )

    # --- Public Methods for JSON Context Files ---

    def refresh_json_list(self) -> None:
        """Làm mới danh sách các tệp JSON ngữ cảnh (ctx_*.json) và hiển thị trên UI."""
        self._refresh_file_list(self.app.json_list, "ctx_*.json", "json_files")

    def preview_json_selected(self) -> None:
        """Hiển thị nội dung của tệp JSON được chọn."""
        self._preview_selected_file(self.app.json_list, "json_files", "JSON")

    def delete_json_selected(self) -> None:
        """Xóa tệp JSON được chọn."""
        self._delete_selected_file(
            self.app.json_list, "json_files", self.refresh_json_list, "JSON"
        )
