from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from http.client import HTTPResponse
from typing import Any, Final
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import certifi
import pytz
import ssl

from APP.configs.app_config import FMPConfig

logger = logging.getLogger(__name__)

_USER_AGENT: Final[str] = "GeminiApp/1.0 (+https://financialmodelingprep.com)"
_BASE_URL: Final[str] = "https://financialmodelingprep.com/api/v3"


class FMPService:
    """
    Dịch vụ để tương tác với Financial Modeling Prep (FMP).
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
        # Use certifi CA bundle to avoid missing root certificates on Windows.
        self._ssl_context = ssl.create_default_context(cafile=certifi.where())

    def _build_calendar_url(self, days: int) -> str:
        today = datetime.now(pytz.utc).date()
        end_date = today + timedelta(days=max(days, 1))
        query = urlencode(
            {
                "from": today.strftime("%Y-%m-%d"),
                "to": end_date.strftime("%Y-%m-%d"),
                "apikey": self.config.api_key,
            }
        )
        return f"{_BASE_URL}/economic_calendar?{query}"

    def _fetch(self, url: str) -> HTTPResponse:
        request = Request(url=url, headers={"User-Agent": _USER_AGENT})
        try:
            return urlopen(request, timeout=15, context=self._ssl_context)
        except ssl.SSLCertVerificationError as exc:
            logger.warning(
                "FMP gặp lỗi xác minh SSL với bundle certifi (%s). Thử lại với kết nối không xác minh SSL.",
                exc,
            )
            insecure_context = ssl._create_unverified_context()
            return urlopen(request, timeout=15, context=insecure_context)

    def get_economic_calendar(self, days: int = 7) -> list[dict[str, Any]]:
        """
        Lấy dữ liệu lịch kinh tế cho số ngày tới bằng API của FMP.

        Args:
            days: Số ngày tới để lấy dữ liệu.

        Returns:
            Danh sách các sự kiện kinh tế.

        Raises:
            Exception: Nếu có lỗi xảy ra trong quá trình gọi API.
        """
        if not self.config.enabled:
            logger.info("FMPService bị vô hiệu hóa trong cấu hình.")
            return []
        if not self.config.api_key:
            logger.warning("Không có API key cho FMPService, bỏ qua việc gọi API.")
            return []

        url = self._build_calendar_url(days)
        safe_url = url.replace(self.config.api_key, "****")
        logger.debug("Đang lấy dữ liệu lịch kinh tế từ FMP: %s", safe_url)

        try:
            with self._fetch(url) as response:
                payload = response.read().decode("utf-8")
        except HTTPError as exc:
            logger.warning("FMP trả về lỗi HTTP %s: %s. Dùng investpy fallback.", exc.code, exc.reason)
            return self._fallback_investpy(days)
        except URLError as exc:
            reason = getattr(exc, "reason", exc)
            if isinstance(reason, ssl.SSLCertVerificationError):
                logger.warning("FMP gặp lỗi xác minh SSL: %s. Dùng investpy fallback.", reason)
            else:
                logger.warning("Không thể kết nối tới FMP: %s. Dùng investpy fallback.", reason)
            return self._fallback_investpy(days)
        except ssl.SSLCertVerificationError as exc:
            logger.warning("FMP gặp lỗi xác minh SSL trực tiếp: %s. Dùng investpy fallback.", exc)
            return self._fallback_investpy(days)
        except Exception as exc:
            logger.warning("Lỗi không xác định khi gọi FMP: %s. Dùng investpy fallback.", exc)
            return self._fallback_investpy(days)

        try:
            data = json.loads(payload)
        except json.JSONDecodeError as exc:
            logger.warning("Không thể parse JSON từ FMP: %s. Dùng investpy fallback.", exc)
            return self._fallback_investpy(days)

        if not isinstance(data, list):
            logger.warning("FMP trả về dữ liệu không phải danh sách: %s. Dùng investpy fallback.", type(data))
            return self._fallback_investpy(days)

        if not data:
            logger.warning("FMP trả về danh sách rỗng. Dùng investpy fallback.")
            return self._fallback_investpy(days)

        logger.info("Lấy thành công %d sự kiện từ FMP cho %d ngày tới.", len(data), days)
        return data

    def _fallback_investpy(self, days: int) -> list[dict[str, Any]]:
        """Fallback sang investpy khi FMP không khả dụng."""
        try:
            import investpy  # type: ignore[import]
        except ImportError:
            logger.warning("Không tìm thấy investpy để fallback FMP.")
            return []

        today = datetime.now(pytz.utc)
        to_date = today + timedelta(days=max(days, 1))
        from_str = today.strftime("%d/%m/%Y")
        to_str = to_date.strftime("%d/%m/%Y")
        try:
            df = investpy.economic_calendar(from_date=from_str, to_date=to_str)
        except Exception as exc:  # pragma: no cover - logging path
            logger.warning("investpy.economic_calendar lỗi: %s", exc)
            return []
        if df is None or df.empty:
            logger.warning("investpy trả về dữ liệu rỗng.")
            return []

        records = df.to_dict("records")
        events: list[dict[str, Any]] = []
        for row in records:
            events.append({
                "event": row.get("event"),
                "country": row.get("country"),
                "impact": row.get("importance"),
                "date": row.get("date"),
                "time": row.get("time"),
            })
        logger.info("Lấy thành công %d sự kiện từ investpy fallback.", len(events))
        return events

