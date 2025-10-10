from __future__ import annotations

import json
import logging
import ssl
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

import certifi
import tradingeconomics as te

from APP.configs.app_config import TEConfig

logger = logging.getLogger(__name__)

_TE_BASE_URL = "https://api.tradingeconomics.com/calendar"
_TE_USER_AGENT = "GeminiApp/1.0 (+https://tradingeconomics.com)"


class TEService:
    """Wrapper đơn giản cho Trading Economics API."""

    def __init__(self, config: TEConfig):
        self.config = config
        try:
            te.login(self.config.api_key)
            logger.info("Đăng nhập thành công vào Trading Economics API.")
        except Exception as exc:  # pragma: no cover - logging path
            logger.error("Lỗi khi đăng nhập vào Trading Economics API: %s", exc)
            raise

    def get_calendar_events(self) -> list[dict]:
        """Lấy lịch kinh tế với SDK, fallback sang REST nếu cần."""
        logger.debug("Đang thực hiện cuộc gọi API đến Trading Economics...")

        original_create_context = ssl._create_default_https_context
        try:
            if self.config.skip_ssl_verify:
                logger.warning("Bỏ qua xác minh SSL cho Trading Economics API.")
                ssl._create_default_https_context = ssl._create_unverified_context

            calendar_data = te.getCalendarData()
            if isinstance(calendar_data, list) and calendar_data:
                logger.info(
                    "Lấy thành công %d sự kiện từ Trading Economics (SDK).",
                    len(calendar_data),
                )
                return calendar_data

            logger.warning(
                "Trading Economics SDK trả về dữ liệu không hợp lệ hoặc rỗng. Thử REST fallback."
            )
            return self._fetch_via_rest()
        except Exception as exc:  # pragma: no cover - logging path
            logger.warning(
                "Trading Economics SDK gặp lỗi (%s). Thử REST fallback.",
                exc,
            )
            return self._fetch_via_rest()
        finally:
            ssl._create_default_https_context = original_create_context
            logger.debug("Đã khôi phục context SSL mặc định.")

    def _fetch_via_rest(self) -> list[dict]:
        """Gọi REST API của TE. Thử khóa chính, fallback sang guest."""
        context = ssl.create_default_context(cafile=certifi.where())
        if self.config.skip_ssl_verify:
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE

        keys_to_try: list[tuple[str, str]] = []
        api_key = (self.config.api_key or "").strip()
        if api_key:
            keys_to_try.append(("primary", api_key))
        if api_key.lower() != "guest:guest":
            keys_to_try.append(("guest", "guest:guest"))

        for label, key in keys_to_try:
            data = self._request_calendar_data(key, context, label)
            if data:
                return data

        logger.error("REST fallback không lấy được dữ liệu Trading Economics.")
        return []

    def _request_calendar_data(
        self,
        api_key: str,
        context: ssl.SSLContext,
        label: str,
    ) -> list[dict]:
        encoded_key = quote(api_key.strip(), safe=":")
        request = Request(
            url=f"{_TE_BASE_URL}?c={encoded_key}",
            headers={"User-Agent": _TE_USER_AGENT},
        )
        try:
            with urlopen(request, timeout=20, context=context) as response:
                payload = response.read().decode("utf-8")
        except HTTPError as exc:
            logger.warning(
                "TE REST (%s) lỗi HTTP %s: %s",
                label,
                exc.code,
                exc.reason,
            )
            # Nếu khóa chính bị cấm, thử khóa tiếp theo.
            return []
        except ssl.SSLCertVerificationError as exc:
            logger.warning("TE REST (%s) lỗi xác minh SSL: %s", label, exc)
            return []
        except URLError as exc:
            logger.warning(
                "TE REST (%s) không thể kết nối (%s)",
                label,
                getattr(exc, "reason", exc),
            )
            return []
        except Exception as exc:  # pragma: no cover - logging path
            logger.error("TE REST (%s) gặp lỗi không xác định: %s", label, exc)
            return []

        try:
            data = json.loads(payload)
        except json.JSONDecodeError as exc:
            logger.warning("TE REST (%s) không parse được JSON: %s", label, exc)
            return []

        if isinstance(data, list) and data:
            logger.info(
                "Lấy thành công %d sự kiện từ Trading Economics (REST/%s).",
                len(data),
                label,
            )
            return data

        logger.warning("TE REST (%s) trả về dữ liệu không hợp lệ hoặc rỗng.", label)
        return []