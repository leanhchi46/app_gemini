from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__) # Khởi tạo logger

_trade_log_lock = threading.Lock() # Khóa riêng cho việc ghi log giao dịch

def setup_logging():
    """
    Cấu hình hệ thống logging để ghi log vào file app_debug.log.
    """
    logger.debug("Bắt đầu setup_logging.")
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
    logger.info(f"Đã cấu hình logging, ghi vào: {log_file}")
    logger.debug("Kết thúc setup_logging.")

def log_trade_decision(data: Dict, folder_override: Optional[str] = None):
    """
    Ghi lại các quyết định giao dịch vào file log JSONL.
    """
    logger.debug(f"Bắt đầu log_trade_decision. Stage: {data.get('stage')}, Folder override: {folder_override}")
    try:
        # Logic để xác định thư mục Reports.
        # Vì hàm này không có quyền truy cập vào đối tượng 'app',
        # chúng ta cần một cách khác để xác định thư mục báo cáo.
        # Tạm thời, tôi sẽ sử dụng một đường dẫn cố định hoặc một biến cấu hình toàn cục.
        # Trong một hệ thống thực tế, 'app' hoặc một đối tượng cấu hình sẽ được truyền vào.
        # Để đơn giản, tôi sẽ giả định thư mục Reports nằm ở gốc dự án hoặc trong XAUUSD/Reports.
        # Cần điều chỉnh sau khi có cấu trúc rõ ràng hơn về cách lấy thư mục báo cáo.
        
        # Tạm thời sử dụng đường dẫn cố định cho mục đích sửa lỗi
        # Cần thay thế bằng logic lấy đường dẫn từ cấu hình ứng dụng thực tế
        reports_base_dir = Path("XAUUSD/Reports") # Hoặc Path("Reports") tùy thuộc vào cấu hình
        if folder_override:
            d = reports_base_dir / folder_override
        else:
            d = reports_base_dir
        
        if not d:
            logger.warning("Không thể xác định thư mục Reports để ghi log giao dịch.")
            return

        p = d / f"trade_log_{data.get('t', '').split(' ')[0].replace('-', '')}.jsonl" # Sử dụng thời gian từ data nếu có
        if not data.get('t'): # Nếu không có thời gian trong data, dùng thời gian hiện tại
            from datetime import datetime
            p = d / f"trade_log_{datetime.now().strftime('%Y%m%d')}.jsonl"

        line = (json.dumps(data, ensure_ascii=False, separators=(',', ':')) + "\n").encode("utf-8")

        p.parent.mkdir(parents=True, exist_ok=True)

        with _trade_log_lock: # Sử dụng lock cục bộ
            need_leading_newline = False
            if p.exists():
                try:
                    sz = p.stat().st_size
                    if sz > 0:
                        with open(p, "rb") as fr:
                            fr.seek(-1, os.SEEK_END)
                            need_leading_newline = (fr.read(1) != b"\n")
                except Exception as e:
                    logger.warning(f"Lỗi khi kiểm tra file log {p}: {e}")
                    need_leading_newline = False

            with open(p, "ab") as f:
                if need_leading_newline:
                    f.write(b"\n")
                f.write(line)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except Exception as e:
                    logger.warning(f"Lỗi khi fsync file log {p}: {e}")
                    pass
        logger.debug(f"Đã ghi log giao dịch vào {p.name}.")
    except Exception as e:
        logger.error(f"Lỗi khi ghi log giao dịch: {e}")
        pass
