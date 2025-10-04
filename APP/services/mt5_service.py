from __future__ import annotations

import json
import logging
import math
import time
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Any, Dict, Iterable, Optional, Sequence, TYPE_CHECKING
from zoneinfo import ZoneInfo

from APP.analysis import ict_analyzer
from APP.utils.safe_data import SafeMT5Data

logger = logging.getLogger(__name__)

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None
    logger.warning("Không thể import MetaTrader5. Các chức năng MT5 sẽ bị vô hiệu hóa.")

if TYPE_CHECKING:
    from APP.configs.app_config import RunConfig


# ------------------------------
# Connection and Helpers
# ------------------------------

def connect(path: str | None = None) -> tuple[bool, str | None]:
    """Khởi tạo kết nối đến MetaTrader5 terminal."""
    if not mt5:
        return False, "Module MetaTrader5 chưa được cài đặt."
    try:
        if mt5.initialize(path=path):
            logger.info("Kết nối MT5 thành công.")
            return True, None
        err = mt5.last_error()
        logger.error(f"mt5.initialize() thất bại, mã lỗi: {err}")
        return False, f"initialize() thất bại: {err}"
    except Exception as e:
        logger.exception("Kết nối MT5 gây ra lỗi ngoại lệ.")
        return False, f"Lỗi kết nối MT5: {e}"

def ensure_initialized(path: str | None = None) -> bool:
    """Đảm bảo MT5 đã được khởi tạo."""
    ok, _ = connect(path)
    return ok

# ... (The rest of the file is the same, just without build_context_from_app)
