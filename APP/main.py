# -*- coding: utf-8 -*-
"""
Điểm khởi đầu của ứng dụng.

Khởi tạo và chạy giao diện người dùng chính của ứng dụng giao dịch.
"""

from __future__ import annotations

import argparse
import logging
import sys
import tkinter as tk
from pathlib import Path
from typing import Optional

# Thêm thư mục gốc của dự án vào sys.path
try:
    project_root = Path(__file__).resolve().parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
except (NameError, IndexError):
    project_root = Path.cwd()
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

from APP.configs import workspace_config
from APP.configs.app_config import LoggingConfig
from APP.persistence.log_handler import setup_logging
from APP.ui.app_ui import AppUI

logger = logging.getLogger(__name__)


def parse_arguments() -> argparse.Namespace:
    """
    Phân tích các đối số dòng lệnh được truyền vào khi chạy ứng dụng.
    """
    parser = argparse.ArgumentParser(description="Ứng dụng Giao dịch và Phân tích Tự động.")
    parser.add_argument(
        "--workspace",
        type=str,
        default=None,
        help="Đường dẫn đến file workspace.json cần tải khi khởi động.",
    )
    return parser.parse_args()


def main(workspace_path: Optional[str] = None) -> None:
    """
    Hàm chính để khởi tạo và chạy ứng dụng.

    Thực hiện các bước:
    1. Tải cấu hình ban đầu từ file workspace.
    2. Thiết lập logging dựa trên cấu hình vừa tải.
    3. Khởi tạo cửa sổ chính Tkinter.
    4. Tạo instance của AppUI, truyền cấu hình vào.
    5. Thiết lập xử lý tắt ứng dụng an toàn (graceful shutdown).
    6. Bắt đầu vòng lặp sự kiện chính.
    """
    try:
        # Đảm bảo thư mục làm việc tồn tại trước khi thực hiện bất kỳ thao tác nào khác
        workspace_config.setup_workspace()

        # Tải cấu hình ban đầu một cách tường minh
        initial_config = workspace_config.load_config_from_file(workspace_path)

        # Trích xuất hoặc tạo cấu hình logging
        logging_dict = initial_config.get("logging", {})
        logging_config = LoggingConfig(**logging_dict)

        # Thiết lập logging VỚI cấu hình
        setup_logging(config=logging_config)

        logger.info("Ứng dụng đang khởi động...")

        root = tk.Tk()
        app = AppUI(root, initial_config=initial_config)

        # Cải tiến 3: Thêm xử lý tắt ứng dụng (Graceful Shutdown)
        # Gán phương thức shutdown của app cho sự kiện đóng cửa sổ.
        root.protocol("WM_DELETE_WINDOW", app.shutdown)

        root.mainloop()

        logger.info("Ứng dụng đã đóng thành công.")
    except Exception:
        logger.exception("Đã xảy ra lỗi nghiêm trọng trong hàm main.")
        raise


if __name__ == "__main__":
    # Cải tiến 1: Thêm cơ chế xử lý đối số dòng lệnh
    args = parse_arguments()
    # Cải tiến 2: Cấu hình một cách tường minh hơn
    main(workspace_path=args.workspace)
