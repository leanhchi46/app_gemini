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
from pathlib import Path

# Thêm thư mục gốc của dự án vào sys.path để có thể import các module từ `src`
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

import tkinter as tk
import logging

# Import các module nội bộ của dự án
from src.config.constants import APP_DIR # APP_DIR sẽ không còn được dùng cho log file

# Import các module mới
from src.ui.app_ui import TradingToolApp
from src.core.app_logic import AppLogic


def main():
    """
    Hàm chính để khởi tạo và chạy ứng dụng.
    Thiết lập cấu hình ghi log và khởi tạo giao diện người dùng.
    """
    # Định nghĩa thư mục Log trong thư mục gốc của dự án
    log_dir = project_root / "Log"
    log_dir.mkdir(parents=True, exist_ok=True) # Tạo thư mục nếu chưa tồn tại
    log_file_path = log_dir / "app_debug.log" # Cập nhật đường dẫn file log
    try:
        # Cấu hình ghi log ra file để dễ dàng gỡ lỗi
        logging.basicConfig(
            level=logging.DEBUG,
            format='%(asctime)s - %(levelname)s - %(name)s - %(message)s',
            filename=str(log_file_path),
            filemode='w',
        )
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
