from __future__ import annotations

import logging
from datetime import datetime, timedelta

try:
    import investpy  # type: ignore[import]
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    investpy = None

try:
    import pandas as pd  # type: ignore[import]
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    pd = None
import pytz

from APP.configs.app_config import FMPConfig

logger = logging.getLogger(__name__)


class FMPService:
    """
    Dịch vụ để tương tác với API của Financial Modeling Prep (FMP) và các dịch vụ dữ liệu khác.
    Lớp này chỉ chịu trách nhiệm gọi API và trả về dữ liệu thô.
    Việc cache được quản lý bởi lớp NewsService cấp cao hơn.
    """

    def __init__(self, config: FMPConfig):
        """
        Khởi tạo FMPService.

        Args:
            config: Đối tượng cấu hình FMPConfig chứa API key.
        """
        self.config = config
        self.is_available: bool = investpy is not None
        self._dependency_notes: list[str] = []
        if investpy is None:
            self._dependency_notes.append('Thi?u thu vi?n investpy - kh�ng th? goi economic_calendar.')
        if pd is None:
            self._dependency_notes.append(
                'pandas chua du?c c�i d?t - dung fallback chuy?n d?i danh s�ch (kh�ng ?nh hu?ng ?n investpy).'
            )

    @property
    def dependency_notes(self) -> list[str]:
        """Tr? v? danh s�ch ghi ch� phu thu?c hi?n c� (neu co)."""

        return list(self._dependency_notes)

    def get_economic_calendar(self, days: int = 7) -> list[dict]:
        """
        Lấy dữ liệu lịch kinh tế cho số ngày tới bằng investpy.

        Args:
            days: Số ngày tới để lấy dữ liệu.

        Returns:
            Danh sách các sự kiện kinh tế.
        
        Raises:
            Exception: Nếu có lỗi xảy ra trong quá trình gọi API.
        """
        logger.debug("Đang lấy dữ liệu lịch kinh tế từ investpy...")
        if investpy is None:
            logger.warning(
                "Không thể lấy dữ liệu lịch kinh tế vì thiếu thư viện investpy."
            )
            return []
        if pd is None:
            logger.warning(
                "pandas chưa được cài đặt. Sử dụng cơ chế chuyển đổi dữ liệu dự phòng."
            )
        try:
            today = datetime.now(pytz.utc)
            end_date = today + timedelta(days=days)
            
            # investpy yêu cầu định dạng 'dd/mm/yyyy'
            from_date_str = today.strftime('%d/%m/%Y')
            to_date_str = end_date.strftime('%d/%m/%Y')

            calendar_df = investpy.economic_calendar(
                from_date=from_date_str,
                to_date=to_date_str,
            )

            if pd is not None and isinstance(calendar_df, pd.DataFrame):
                calendar_data = calendar_df.to_dict('records')
            elif isinstance(calendar_df, list):
                calendar_data = calendar_df
            else:
                logger.warning("Không thể chuyển đổi dữ liệu lịch kinh tế: %s", calendar_df)
                return []

            logger.info("Lấy thành công %d sự kiện từ investpy cho %d ngày tới.", len(calendar_data), days)
            return calendar_data
        except Exception as e:
            logger.error("Lỗi khi lấy dữ liệu từ investpy: %s", e)
            # Ném lại ngoại lệ để lớp gọi (NewsService) có thể xử lý
            raise
