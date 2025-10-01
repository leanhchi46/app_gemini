from __future__ import annotations
import logging
from pathlib import Path
import os

def setup_logging():
    """
    Cấu hình hệ thống logging để ghi log vào file app_debug.log.
    """
    log_dir = Path("Log")
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / "app_debug.log"

    # Xóa các handler cũ để tránh ghi log trùng lặp
    for handler in logging.root.handlers[:]:
        logging.root.removeHandler(handler)
    
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(os.sys.stdout) # Ghi ra console nữa
        ]
    )
    logging.info(f"Đã cấu hình logging, ghi vào: {log_file}")
