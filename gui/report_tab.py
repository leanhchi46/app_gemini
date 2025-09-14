import tkinter as tk
from tkinter import ttk

class ReportTab:
    """
    Tab Report: hiển thị danh sách ảnh, trạng thái, lịch sử báo cáo
    """
    def __init__(self, parent, app):
        self.parent = parent
        self.app = app
        # ...khởi tạo UI Treeview, Listbox, các nút thao tác...

    def refresh_history_list(self):
        # ...refresh danh sách báo cáo...
        pass

    def preview_history_selected(self):
        # ...xem trước báo cáo được chọn...
        pass

    def open_history_selected(self):
        # ...mở file báo cáo được chọn...
        pass

    def delete_history_selected(self):
        # ...xoá file báo cáo được chọn...
        pass

    def open_reports_folder(self):
        # ...mở thư mục chứa báo cáo...
        pass
