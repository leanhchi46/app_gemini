from __future__ import annotations
from typing import Any, Optional
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class SafeMT5Data:
    """
    Lớp bao bọc an toàn cho từ điển dữ liệu MT5, giúp truy cập các giá trị lồng nhau
    mà không gây ra lỗi.
    """
    def __init__(self, data: Optional[dict[str, Any]]):
        self._data = data if data is not None else {}

    @property
    def raw(self) -> dict[str, Any]:
        """Trả về từ điển dữ liệu thô."""
        return self._data

    def get(self, key: str, default: Any = None) -> Any:
        """Truy cập an toàn một giá trị từ cấp cao nhất."""
        return self._data.get(key, default)

    def get_tick_value(self, key: str, default: Any = None) -> Any:
        """Truy cập an toàn một giá trị từ từ điển 'tick'."""
        return (self._data.get("tick") or {}).get(key, default)

    def get_info_value(self, key: str, default: Any = None) -> Any:
        """Truy cập an toàn một giá trị từ từ điển 'info'."""
        return (self._data.get("info") or {}).get(key, default)

    # ... (Thêm các phương thức get an toàn khác nếu cần)

    def get_active_session(self) -> Optional[str]:
        """Xác định phiên giao dịch hiện đang hoạt động."""
        sessions = self._data.get("sessions_today", {})
        if not sessions:
            return None
        
        now_hhmm = datetime.now().strftime("%H:%M")
        
        for session_name, details in sessions.items():
            start = details.get("start")
            end = details.get("end")
            if start and end and start <= now_hhmm < end:
                return session_name
        return None

    def get_atr_pips(self, timeframe: str, default: float = 0.0) -> float:
        """Truy cập an toàn ATR và chuyển đổi nó thành pips."""
        try:
            atr_val = (self._data.get("volatility", {}).get("ATR", {}) or {}).get(timeframe)
            pip_info = self._data.get("pip", {})
            value_per_point = pip_info.get("value_per_point")
            points_per_pip = pip_info.get("points_per_pip")

            if all(v is not None for v in [atr_val, value_per_point, points_per_pip]):
                pip_value = value_per_point * points_per_pip
                if pip_value > 0:
                    return atr_val / pip_value
        except (TypeError, ValueError) as e:
            logger.warning(f"Lỗi khi tính toán ATR pips cho {timeframe}: {e}")
        return default
