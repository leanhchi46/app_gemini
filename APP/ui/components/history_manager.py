# -*- coding: utf-8 -*-
"""
Quản lý việc hiển thị và tương tác với các tệp lịch sử (báo cáo, ngữ cảnh).

Module này được tái cấu trúc để sử dụng một cách tiếp cận hướng đối tượng,
loại bỏ sự lặp lại code và tăng tính module hóa.

- Lớp `FileListView`: Một thành phần UI có thể tái sử dụng, quản lý một
  tk.Listbox duy nhất và các hành động liên quan (làm mới, xem, mở, xóa).
- Lớp `HistoryManager`: Lớp điều phối chính, tạo và quản lý các instance
  của `FileListView` cho các loại tệp khác nhau (ví dụ: .md, .json).
"""

from __future__ import annotations

import logging
import os
import tkinter as tk
from pathlib import Path
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from APP.ui.app_ui import AppUI

from APP.configs import workspace_config
from APP.ui.utils import ui_builder

logger = logging.getLogger(__name__)


class FileListView:
    """
    Quản lý một Listbox hiển thị danh sách tệp và các hành động liên quan.

    Đây là một thành phần có thể tái sử dụng để quản lý bất kỳ loại tệp nào.
    """

    def __init__(
        self,
        app: "AppUI",
        listbox: tk.Listbox,
        file_glob: str,
        file_type_name: str,
    ):
        """
        Khởi tạo một trình quản lý danh sách tệp.

        Args:
            app (AppUI): Instance của ứng dụng chính.
            listbox (tk.Listbox): Widget Listbox để quản lý.
            file_glob (str): Mẫu glob để tìm kiếm tệp (ví dụ: "*.md").
            file_type_name (str): Tên hiển thị cho loại tệp (ví dụ: "Báo cáo").
        """
        self.app = app
        self.listbox = listbox
        self.file_glob = file_glob
        self.file_type_name = file_type_name
        self._file_paths: List[Path] = []
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

        # Gán các phương thức của instance này cho các sự kiện của listbox
        self.listbox.bind("<<ListboxSelect>>", self.preview_selected)

    def refresh(self) -> None:
        """
        Làm mới danh sách tệp bằng cách quét tất cả các thư mục symbol con.
        Logic này không còn phụ thuộc vào symbol hiện tại đang được chọn.
        """
        self.logger.debug(f"Bắt đầu làm mới danh sách toàn diện cho '{self.file_glob}'")
        try:
            self.listbox.delete(0, "end")
            self._file_paths.clear()

            base_folder_str = self.app.folder_path.get()
            if not base_folder_str:
                self.logger.warning("Thư mục gốc (Screenshots) chưa được đặt.")
                return

            base_folder = Path(base_folder_str)
            all_files = []

            # Duyệt qua tất cả các thư mục con trực tiếp trong thư mục gốc
            for symbol_dir in base_folder.iterdir():
                if symbol_dir.is_dir():
                    reports_dir = symbol_dir / "Reports"
                    if reports_dir.is_dir():
                        # Thu thập tất cả các tệp khớp với mẫu glob
                        found_files = list(reports_dir.glob(self.file_glob))
                        all_files.extend(found_files)

            # Sắp xếp tất cả các tệp đã tìm thấy theo ngày sửa đổi, mới nhất trước
            # Điều này đảm bảo các báo cáo gần đây nhất luôn ở trên cùng
            sorted_files = sorted(all_files, key=lambda p: p.stat().st_mtime, reverse=True)

            self._file_paths = sorted_files
            for p in self._file_paths:
                # Hiển thị tên tệp cùng với symbol của nó để dễ phân biệt
                display_name = f"{p.parent.parent.name}/{p.name}"
                self.listbox.insert("end", display_name)

            self.logger.info(f"Đã làm mới và tìm thấy {len(self._file_paths)} tệp '{self.file_glob}' trong tất cả các symbol.")
        except Exception as e:
            self.logger.error(f"Lỗi nghiêm trọng khi làm mới danh sách tệp: {e}", exc_info=True)
            ui_builder.show_message("Lỗi", f"Không thể làm mới danh sách {self.file_type_name}:\n{e}")

    def _get_selected_path(self) -> Optional[Path]:
        """Lấy đường dẫn của tệp đang được chọn trong Listbox."""
        try:
            selected_indices = self.listbox.curselection()
            if not selected_indices:
                return None
            index = selected_indices[0]
            # Lấy lại đường dẫn từ listbox để đảm bảo khớp, vì tên hiển thị đã thay đổi
            # Ví dụ: "XAUUSD/report_...md"
            selected_text = self.listbox.get(index)
            
            # Tách symbol và tên tệp
            parts = selected_text.split('/', 1)
            if len(parts) != 2:
                self.logger.warning(f"Định dạng tên hiển thị không hợp lệ: {selected_text}")
                return None
            
            symbol, filename = parts
            
            base_folder_str = self.app.folder_path.get()
            if not base_folder_str:
                return None
                
            # Xây dựng lại đường dẫn đầy đủ
            file_path = Path(base_folder_str) / symbol / "Reports" / filename
            
            if file_path.exists():
                return file_path
            else:
                # Fallback: thử tìm trong danh sách cache nếu logic trên thất bại
                self.logger.warning(f"Không tìm thấy đường dẫn đã xây dựng lại: {file_path}. Thử tìm trong cache.")
                if 0 <= index < len(self._file_paths):
                    return self._file_paths[index]

        except (IndexError, tk.TclError):
            self.logger.warning("Lựa chọn không hợp lệ, danh sách có thể đã thay đổi hoặc widget đã bị hủy.")
        return None

    def preview_selected(self, event: Optional[tk.Event] = None) -> None:
        """Hiển thị nội dung của tệp được chọn trong ô chi tiết."""
        del event  # Không sử dụng tham số event
        file_path = self._get_selected_path()
        if not file_path or not self.app.detail_text:
            return

        self.logger.debug(f"Xem trước tệp: {file_path.name}")
        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
            self.app.detail_text.config(state="normal")
            self.app.detail_text.delete("1.0", "end")
            self.app.detail_text.insert("1.0", content)
            self.app.detail_text.config(state="disabled")
            self.app.ui_status(f"Đang xem {self.file_type_name}: {file_path.name}")
        except Exception as e:
            self.logger.error(f"Lỗi khi xem trước tệp '{file_path.name}': {e}", exc_info=True)
            ui_builder.show_message("Lỗi", f"Không thể xem trước tệp:\n{e}")

    def open_selected(self) -> None:
        """Mở tệp được chọn bằng ứng dụng mặc định của hệ điều hành."""
        file_path = self._get_selected_path()
        if not file_path:
            return

        self.logger.debug(f"Yêu cầu mở tệp: {file_path}")
        try:
            os.startfile(file_path)
        except Exception as e:
            self.logger.error(f"Lỗi khi mở tệp '{file_path.name}': {e}", exc_info=True)
            ui_builder.show_message("Lỗi", f"Không thể mở tệp:\n{e}")

    def delete_selected(self) -> None:
        """Xóa tệp được chọn sau khi xác nhận."""
        file_path = self._get_selected_path()
        if not file_path:
            return

        self.logger.debug(f"Yêu cầu xóa tệp: {file_path.name}")
        if ui_builder.ask_confirmation(
            title="Xác nhận Xóa",
            message=f"Bạn có chắc chắn muốn xóa tệp:\n{file_path.name}?",
        ):
            try:
                file_path.unlink()
                self.refresh()
                if self.app.detail_text:
                    self.app.detail_text.config(state="normal")
                    self.app.detail_text.delete("1.0", "end")
                    self.app.detail_text.config(state="disabled")
                self.app.ui_status(f"Đã xóa {self.file_type_name}: {file_path.name}")
                self.logger.info(f"Đã xóa tệp: {file_path.name}")
            except Exception as e:
                self.logger.error(f"Lỗi khi xóa tệp '{file_path.name}': {e}", exc_info=True)
                ui_builder.show_message("Lỗi", f"Không thể xóa tệp:\n{e}")


class HistoryManager:
    """
    Điều phối các thành phần UI liên quan đến lịch sử (báo cáo và ngữ cảnh).
    """

    def __init__(self, app: "AppUI") -> None:
        """
        Khởi tạo HistoryManager.
        Lưu ý: Các widget UI chưa tồn tại ở giai đoạn này.
        """
        self.app = app
        self.logger = logging.getLogger(__name__)
        self.md_manager: Optional[FileListView] = None
        self.json_manager: Optional[FileListView] = None

    def link_ui_widgets(self) -> None:
        """
        Liên kết với các widget UI sau khi chúng đã được tạo.
        Phương thức này phải được gọi sau khi build_ui() hoàn tất.
        """
        self.logger.debug("Bắt đầu liên kết các widget UI cho HistoryManager.")
        if self.app.history_list:
            self.md_manager = FileListView(
                app=self.app,
                listbox=self.app.history_list,
                file_glob="report_*.md",
                file_type_name="Báo cáo",
            )
            self.logger.debug("Đã tạo md_manager cho history_list.")
        else:
            self.logger.error("Không tìm thấy widget history_list để liên kết.")

        if self.app.json_list:
            self.json_manager = FileListView(
                app=self.app,
                listbox=self.app.json_list,
                file_glob="ctx_*.json",
                file_type_name="JSON",
            )
            self.logger.debug("Đã tạo json_manager cho json_list.")
        else:
            self.logger.error("Không tìm thấy widget json_list để liên kết.")

    def refresh_all_lists(self) -> None:
        """Làm mới tất cả danh sách tệp được quản lý."""
        self.logger.info("Bắt đầu làm mới tất cả danh sách lịch sử.")
        if self.md_manager:
            self.md_manager.refresh()
        if self.json_manager:
            self.json_manager.refresh()

    def open_reports_folder(self) -> None:
        """
        Mở thư mục chứa báo cáo.

        - Nếu một mục đang được chọn trong danh sách, mở thư mục Reports của symbol đó.
        - Nếu không, mở thư mục gốc (Screenshots).
        """
        self.logger.debug("Yêu cầu mở thư mục báo cáo.")
        try:
            base_folder_str = self.app.folder_path.get()
            if not base_folder_str:
                ui_builder.show_message("Thông báo", "Vui lòng chọn thư mục ảnh trước.")
                return

            target_path: Path | None = None
            base_folder = Path(base_folder_str)

            # Sửa lỗi: Gọi _get_selected_path từ md_manager (hoặc json_manager)
            selected_path: Path | None = None
            if self.md_manager:
                selected_path = self.md_manager._get_selected_path()

            if selected_path:
                target_path = selected_path.parent  # Thư mục Reports của mục được chọn
            else:
                # Nếu không có gì được chọn, mặc định mở thư mục gốc
                target_path = base_folder

            if target_path and target_path.is_dir():
                os.startfile(target_path)
                self.logger.info(f"Đã gửi yêu cầu mở thư mục: {target_path}")
            else:
                self.logger.warning(f"Thư mục đích không tồn tại: {target_path}")
                ui_builder.show_message("Thông báo", "Thư mục đích không tồn tại.")
        except Exception as e:
            self.logger.error(f"Lỗi khi mở thư mục báo cáo: {e}", exc_info=True)
            ui_builder.show_message("Lỗi", f"Không thể mở thư mục báo cáo:\n{e}")

    # --- Compatibility Layer ---
    # Các phương thức này được giữ lại để tương thích ngược với ui_builder,
    # chúng chỉ đơn giản ủy quyền lệnh gọi cho các manager tương ứng.

    def refresh_history_list(self) -> None:
        """Tương thích ngược: Làm mới danh sách báo cáo .md."""
        if self.md_manager:
            self.md_manager.refresh()

    def open_history_selected(self) -> None:
        """Tương thích ngược: Mở báo cáo .md được chọn."""
        if self.md_manager:
            self.md_manager.open_selected()

    def delete_history_selected(self) -> None:
        """Tương thích ngược: Xóa báo cáo .md được chọn."""
        if self.md_manager:
            self.md_manager.delete_selected()

    def refresh_json_list(self) -> None:
        """Tương thích ngược: Làm mới danh sách .json."""
        if self.json_manager:
            self.json_manager.refresh()

    def open_json_selected(self) -> None:
        """Tương thích ngược: Mở tệp .json được chọn."""
        if self.json_manager:
            self.json_manager.open_selected()

    def delete_json_selected(self) -> None:
        """Tương thích ngược: Xóa tệp .json được chọn."""
        if self.json_manager:
            self.json_manager.delete_selected()
