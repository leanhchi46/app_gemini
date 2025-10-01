from __future__ import annotations
import json
from datetime import datetime
from typing import TYPE_CHECKING, Optional, Dict

if TYPE_CHECKING:
    from scripts.tool import TradingToolApp


def log_trade_decision(
    app: "TradingToolApp", data: Dict, folder_override: Optional[str] = None
):
    """
    Ghi lại các quyết định hoặc sự kiện quan trọng vào file log JSONL.
    Sử dụng khóa (lock) để đảm bảo an toàn khi ghi file từ nhiều luồng.
    """
    try:
        # Sử dụng phương thức _get_reports_dir từ app_logic
        d = app._get_reports_dir(folder_override=folder_override)
        if not d:
            return

        log_file = d / f"trade_log_{datetime.now().strftime('%Y%m%d')}.jsonl"
        line = json.dumps(data, ensure_ascii=False)

        # Sử dụng lock để đảm bảo ghi file an toàn từ nhiều luồng
        with app._trade_log_lock:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(line + "\n")
    except Exception:
        # logging.error(f"Lỗi khi ghi trade log: {e}") # Không import logging ở đây để tránh phụ thuộc
        pass  # Bỏ qua lỗi ghi log để không làm ảnh hưởng đến luồng chính
