from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)

_trade_log_lock = threading.Lock()


def setup_logging():
    """
    Cấu hình hệ thống logging để ghi log vào tệp và console.
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
            logging.StreamHandler(os.sys.stdout)
        ]
    )
    logger.info(f"Đã cấu hình logging, ghi vào: {log_file}")


def log_trade(data: Dict, reports_dir: Path):
    """
    Ghi lại một quyết định hoặc hành động giao dịch vào tệp JSONL.
    """
    if not reports_dir:
        logger.warning("Không có thư mục reports được cung cấp, không thể ghi log giao dịch.")
        return

    try:
        from datetime import datetime
        ts = data.get('t') or datetime.now().strftime('%Y%m%d')
        log_filename = f"trade_log_{ts.split(' ')[0].replace('-', '')}.jsonl"
        log_path = reports_dir / log_filename

        line = (json.dumps(data, ensure_ascii=False, separators=(',', ':')) + "\n").encode("utf-8")

        log_path.parent.mkdir(parents=True, exist_ok=True)

        with _trade_log_lock:
            with open(log_path, "ab") as f:
                f.write(line)
    except Exception as e:
        logger.error(f"Lỗi khi ghi log giao dịch: {e}", exc_info=True)


def log_proposed_trade(data: Dict, reports_dir: Path):
    """
    Ghi lại một giao dịch được đề xuất vào tệp JSONL riêng cho backtesting.
    """
    if not reports_dir:
        logger.warning("Không có thư mục reports được cung cấp, không thể ghi log proposed trade.")
        return
        
    log_path = reports_dir / "proposed_trades.jsonl"
    try:
        line = (json.dumps(data, ensure_ascii=False) + "\n").encode("utf-8")
        with _trade_log_lock:
            with open(log_path, "ab") as f:
                f.write(line)
    except Exception as e:
        logger.error(f"Lỗi khi ghi log proposed trade: {e}", exc_info=True)
