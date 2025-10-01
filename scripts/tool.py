# -*- coding: utf-8 -*-
"""
ỨNG DỤNG: PHÂN TÍCH ẢNH HÀNG LOẠT VÀ GIAO DỊCH TỰ ĐỘNG
================================================================
Mục tiêu:
- Tự động nạp và phân tích ảnh từ một thư mục.
- Tích hợp dữ liệu từ MetaTrader 5 để làm giàu ngữ cảnh.
- Sử dụng Google Gemini để tạo báo cáo phân tích theo mẫu.
- Hỗ trợ các tính năng nâng cao: cache ảnh, gửi thông báo Telegram, và tự động giao dịch.
"""

from __future__ import annotations

import sys
import os # Thêm import os
from pathlib import Path
import subprocess # Thêm import subprocess

# Thêm thư mục gốc của dự án vào sys.path để có thể import các module từ `src`
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

import tkinter as tk
import logging

# Import các module nội bộ của dự án
from src.config.constants import APP_DIR # APP_DIR sẽ không còn được dùng cho log file
from src.utils.logging_utils import setup_logging # Import hàm setup_logging

# Import các module mới
from src.ui.app_ui import TradingToolApp
from src.core.app_logic import AppLogic


def main():
    """
    Hàm chính để khởi tạo và chạy ứng dụng.
    Thiết lập cấu hình ghi log và khởi tạo giao diện người dùng.
    """
    try:
        setup_logging() # Gọi hàm cấu hình logging
        logging.info("Ứng dụng đang khởi động.")    

        root = tk.Tk()
        app_logic = AppLogic() # Khởi tạo AppLogic mà không truyền UI ban đầu
        app = TradingToolApp(root, app_logic) # Truyền AppLogic vào TradingToolApp
        app_logic.set_ui_references(app) # Thiết lập tham chiếu UI sau khi app được tạo
        root.mainloop()
    except Exception:
        logging.exception("Đã xảy ra một ngoại lệ chưa được xử lý trong main.")
        raise

if __name__ == "__main__":
    main()
