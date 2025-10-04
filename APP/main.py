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
import tkinter as tk
from pathlib import Path
import logging

# Thêm thư mục gốc của dự án vào sys.path để có thể import các module từ `APP`
# Điều này đảm bảo script có thể chạy từ bất kỳ đâu và vẫn tìm thấy module APP.
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from APP.persistence.log_handler import setup_logging
from APP.ui.app_ui import AppUI

logger = logging.getLogger(__name__)

def main():
    """
    Hàm chính để khởi tạo và chạy ứng dụng.
    Thiết lập cấu hình ghi log và khởi tạo giao diện người dùng.
    """
    try:
        setup_logging()
        logger.debug("Đã thiết lập logging trong main.")
        logging.info("Ứng dụng đang khởi động.")

        root = tk.Tk()
        # Giả định AppUI sẽ được tái cấu trúc để không cần app_logic
        # Lớp logic sẽ được tích hợp vào các thành phần phù hợp khác.
        app = AppUI(root)
        root.mainloop()
    except Exception:
        logging.exception("Đã xảy ra một ngoại lệ chưa được xử lý trong main.")
        raise

if __name__ == "__main__":
    logger.debug("Bắt đầu thực thi main() từ APP/main.py")
    main()
