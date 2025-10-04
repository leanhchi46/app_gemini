from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)


class SafeData:
    """
    Lớp SafeData cung cấp một trình bao bọc an toàn cho từ điển dữ liệu,
    giúp truy cập các giá trị lồng nhau mà không gặp lỗi 'NoneType' object has no attribute 'get'.
    """

    def __init__(self, data: Optional[dict[str, Any]]):
        """
        Khởi tạo một đối tượng SafeData.

        Args:
            data: Từ điển chứa dữ liệu, có thể là None.
        """
        logger.debug(f"Khởi tạo SafeData với data có: {data is not None}")
        self._data = data if data is not None else {}

    @property
    def raw(self) -> dict[str, Any]:
        """
        Trả về từ điển dữ liệu cơ bản.

        Returns:
            Từ điển dữ liệu thô.
        """
        logger.debug("Truy cập raw data.")
        return self._data

    def get(self, key: str, default: Any = None) -> Any:
        """
        Truy cập an toàn một giá trị từ các khóa cấp cao nhất.

        Args:
            key: Khóa cần truy cập.
            default: Giá trị mặc định nếu khóa không tồn tại.

        Returns:
            Giá trị tương ứng với khóa hoặc giá trị mặc định.
        """
        result = self._data.get(key, default)
        logger.debug(f"Get top-level key '{key}': {result}")
        return result

    def get_tick_value(self, key: str, default: Any = None) -> Any:
        """
        Truy cập an toàn một giá trị từ từ điển 'tick'.
        """
        result = (self._data.get("tick") or {}).get(key, default)
        logger.debug(f"Get tick value '{key}': {result}")
        return result

    def get_info_value(self, key: str, default: Any = None) -> Any:
        """
        Truy cập an toàn một giá trị từ từ điển 'info'.
        """
        result = (self._data.get("info") or {}).get(key, default)
        logger.debug(f"Get info value '{key}': {result}")
        return result

    def get_pip_value(self, key: str, default: Any = None) -> Any:
        """
        Truy cập an toàn một giá trị từ từ điển 'pip'.
        """
        result = (self._data.get("pip") or {}).get(key, default)
        logger.debug(f"Get pip value '{key}': {result}")
        return result

    def get_level_value(self, level_type: str, key: str, default: Any = None) -> Any:
        """
        Truy cập an toàn một giá trị từ một loại level cụ thể (ví dụ: 'daily', 'prev_day').
        """
        result = ((self._data.get("levels") or {}).get(level_type) or {}).get(key, default)
        logger.debug(f"Get level value for '{level_type}' key '{key}': {result}")
        return result

    def get_vwap(self, key: str, default: Any = None) -> Any:
        """
        Truy cập an toàn một giá trị từ từ điển 'vwap'.
        """
        result = (self._data.get("vwap") or {}).get(key, default)
        logger.debug(f"Get vwap '{key}': {result}")
        return result

    def get_ema(self, timeframe: str, key: str, default: Any = None) -> Any:
        """
        Truy cập an toàn một giá trị EMA cho một khung thời gian nhất định.
        """
        result = (
            ((self._data.get("trend_refs") or {}).get("EMA") or {}).get(timeframe)
            or {}
        ).get(key, default)
        logger.debug(f"Get EMA for '{timeframe}' key '{key}': {result}")
        return result

    def get_ict_pattern(self, pattern_key: str, default: Any = None) -> Any:
        """
        Truy cập an toàn một giá trị từ từ điển 'ict_patterns'.
        """
        result = (self._data.get("ict_patterns") or {}).get(pattern_key, default)
        logger.debug(f"Get ICT pattern '{pattern_key}': {result}")
        return result

    def get_rr_projection(self, key: str, default: Any = None) -> Any:
        """
        Truy cập an toàn một giá trị từ từ điển 'rr_projection'.
        """
        result = (self._data.get("rr_projection") or {}).get(key, default)
        logger.debug(f"Get RR projection '{key}': {result}")
        return result

    def get_plan_value(self, key: str, default: Any = None) -> Any:
        """
        Truy cập an toàn một giá trị từ từ điển 'plan'.
        """
        result = (self._data.get("plan") or {}).get(key, default)
        logger.debug(f"Get plan value '{key}': {result}")
        return result

    def get_active_session(self, tz: str = "Asia/Ho_Chi_Minh") -> Optional[str]:
        """
        Xác định phiên giao dịch hiện đang hoạt động dựa trên múi giờ được cung cấp.
        """
        logger.debug(f"Bắt đầu get_active_session với timezone: {tz}")
        sessions = self._data.get("sessions_today", {})
        if not sessions:
            logger.debug("Không có session data, trả về None.")
            return None

        try:
            now_time = datetime.now(ZoneInfo(tz))
            now_hhmm = now_time.strftime("%H:%M")
        except Exception as e:
            logger.error(f"Lỗi khi làm việc với timezone '{tz}': {e}. Sử dụng giờ hệ thống.")
            now_hhmm = datetime.now().strftime("%H:%M")


        for session_name, details in sessions.items():
            start = details.get("start")
            end = details.get("end")
            if start and end:
                # Xử lý trường hợp phiên qua đêm (ví dụ: NY PM)
                if start > end:
                    if now_hhmm >= start or now_hhmm < end:
                        logger.debug(f"Tìm thấy phiên hoạt động (qua đêm): {session_name}")
                        return session_name
                # Xử lý trường hợp phiên trong ngày
                elif start <= now_hhmm < end:
                    logger.debug(f"Tìm thấy phiên hoạt động (trong ngày): {session_name}")
                    return session_name
                    
        logger.debug("Không có active session.")
        return None

    def get_atr_pips(self, timeframe: str, default: float = 0.0) -> float:
        """
        Truy cập an toàn ATR cho một khung thời gian và chuyển đổi nó thành pips.
        """
        logger.debug(
            f"Bắt đầu get_atr_pips cho timeframe: {timeframe}, default: {default}"
        )
        try:
            atr_val = (
                self._data.get("volatility", {}).get("ATR", {}) or {}
            ).get(timeframe)
            value_per_point = self.get_pip_value("value_per_point")
            points_per_pip = self.get_pip_value("points_per_pip")

            if (
                atr_val is not None
                and value_per_point is not None
                and points_per_pip is not None
                and value_per_point * points_per_pip > 0
            ):
                pip_value_per_lot = value_per_point * points_per_pip
                result = atr_val / pip_value_per_lot
                logger.debug(f"ATR pips cho {timeframe}: {result}")
                return result
        except (TypeError, ValueError) as e:
            logger.warning(f"Lỗi khi tính ATR pips cho {timeframe}: {e}")
            pass
        logger.debug(
            f"Không thể tính ATR pips cho {timeframe}, trả về default: {default}"
        )
        return default
