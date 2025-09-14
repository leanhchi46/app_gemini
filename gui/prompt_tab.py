import tkinter as tk
from tkinter import ttk

class PromptTab:
    """
    Tab Prompt: quản lý prompt, nạp file, chỉnh sửa
    """
    def __init__(self, parent, app):
        self.parent = parent
        self.app = app
        # ...khởi tạo UI prompt, các nút thao tác...

    def load_prompt_from_file(self, path=None):
        # ...nạp prompt từ file...
        pass

    def pick_prompt_file(self):
        # ...chọn file prompt...
        pass

    def reformat_prompt_area(self):
        # ...định dạng lại prompt...
        pass

    def show_prompt(self, text):
        # ...hiển thị prompt lên giao diện...
        pass