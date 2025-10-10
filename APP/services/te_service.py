from __future__ import annotations

import logging
from typing import Tuple

import tradingeconomics as te
from urllib.error import HTTPError

from APP.configs.app_config import TEConfig

logger = logging.getLogger(__name__)


class TEService:
    """
    Dịch vụ để tương tác với API của Trading Economics (TE).
    Lớp này chỉ chịu trách nhiệm gọi API và trả về dữ liệu thô.
    Việc cache được quản lý bởi lớp NewsService cấp cao hơn.
    """

    def __init__(self, config: TEConfig):
        """
        Khởi tạo TEService.

        Args:
            config: Đối tượng cấu hình TEConfig chứa API key.
        """
        self.config = config
        api_key = (self.config.api_key or "").strip()

        if not api_key:
            raise ValueError("API key cho Trading Economics không được bỏ trống")

        login_key, login_format = self._prepare_login_args(api_key)

        try:
            te.login(login_key)
            logger.info(
                "Đăng nhập thành công vào Trading Economics API với định dạng key %s.",
                login_format,
            )
        except Exception as e:
            logger.error("Lỗi khi đăng nhập vào Trading Economics API: %s", e)
            # Ném lại ngoại lệ để ngăn việc khởi tạo nếu không có key
            raise

    def get_calendar_events(self) -> list[dict]:
        """
        Lấy dữ liệu lịch kinh tế từ Trading Economics.

        Returns:
            Danh sách các sự kiện kinh tế.
            
        Raises:
            Exception: Nếu có lỗi xảy ra trong quá trình gọi API.
        """
        import ssl
        
        logger.debug("Đang thực hiện cuộc gọi API đến Trading Economics...")

        # Lưu trữ hàm gốc, không phải kết quả của nó
        original_create_context = ssl._create_default_https_context

        try:
            if self.config.skip_ssl_verify:
                logger.warning("Bỏ qua xác minh SSL cho Trading Economics API.")
                # Thay thế bằng hàm tạo context không xác minh
                ssl._create_default_https_context = ssl._create_unverified_context

            # API của TE không hỗ trợ lọc theo ngày, nó trả về một khoảng thời gian mặc định
            calendar_data = te.getCalendarData()

            if not isinstance(calendar_data, list):
                logger.warning("TE API không trả về danh sách: %s", calendar_data)
                return []

            logger.info("Lấy thành công %d sự kiện từ Trading Economics.", len(calendar_data))
            return calendar_data
        except HTTPError as http_err:
            if http_err.code in (401, 403):
                logger.warning(
                    "Trading Economics trả về lỗi %s - có thể do API key không hợp lệ hoặc hết hạn. "
                    "Trả về danh sách rỗng để tránh dừng hệ thống.",
                    http_err.code,
                )
                return []
            logger.error("HTTPError khi gọi TE API: %s", http_err)
            raise
        except Exception as e:
            logger.error("Lỗi khi gọi TE API: %s", e)
            # Ném lại ngoại lệ để lớp gọi (NewsService) có thể xử lý
            raise
        finally:
            # Luôn khôi phục lại hàm gốc
            ssl._create_default_https_context = original_create_context
            logger.debug("Đã khôi phục context SSL mặc định.")

    @staticmethod
    def _prepare_login_args(api_key: str) -> Tuple[str, str]:
        """Chuẩn hóa API key để tương thích với tradingeconomics.login."""

        login_format = "single key"
        if ":" in api_key:
            username, password = api_key.split(":", 1)
            username = username.strip()
            password = password.strip()
            if not username or not password:
                raise ValueError("API key Trading Economics không hợp lệ – thiếu username hoặc password")
            api_key = f"{username}:{password}"
            login_format = "username/password"

        return api_key, login_format
