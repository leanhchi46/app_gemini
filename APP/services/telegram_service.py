# -*- coding: utf-8 -*-
"""
Module để tương tác với API của Telegram.

Chứa lớp TelegramClient chịu trách nhiệm gửi tin nhắn và thực hiện các cuộc gọi API.
"""

from __future__ import annotations

import http.client
import json
import logging
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Optional, Tuple

# Sử dụng certifi nếu có để tăng cường bảo mật SSL
try:
    import certifi  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    certifi = None  # type: ignore

from APP.utils.general_utils import tg_html_escape
from APP.configs.app_config import TelegramConfig

if TYPE_CHECKING:
    from APP.configs.app_config import RunConfig

logger = logging.getLogger(__name__)


def build_ssl_context(cafile: Optional[str], skip_verify: bool) -> ssl.SSLContext:
    """
    Tạo một SSLContext an toàn để sử dụng cho các kết nối HTTPS.

    Ưu tiên sử dụng CA file được cung cấp, sau đó đến certifi, và cuối cùng là
    CA mặc định của hệ thống.

    Args:
        cafile: Đường dẫn đến file CA bundle (PEM/CRT).
        skip_verify: Nếu True, sẽ vô hiệu hóa kiểm tra hostname và xác minh
                     chứng chỉ (không an toàn, chỉ dùng để debug).

    Returns:
        Một instance của ssl.SSLContext đã được cấu hình.
    """
    logger.debug(f"Bắt đầu tạo SSL context. cafile: {cafile}, skip_verify: {skip_verify}")
    try:
        if cafile:
            ctx = ssl.create_default_context(cafile=cafile)
            logger.debug(f"Đã tạo SSL context với cafile tùy chỉnh: {cafile}")
        elif certifi:
            ctx = ssl.create_default_context(cafile=certifi.where())
            logger.debug("Đã tạo SSL context với certifi.")
        else:
            ctx = ssl.create_default_context()
            logger.info("Đang sử dụng CA mặc định của hệ thống. Cân nhắc cài đặt 'certifi'.")
    except Exception:
        logger.exception("Lỗi khi tạo SSL context, sẽ sử dụng context mặc định không an toàn.")
        ctx = ssl.create_default_context()

    if skip_verify:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        logger.warning("!!! BỎ QUA XÁC MINH SSL (INSECURE) !!!")

    logger.debug("Tạo SSL context thành công.")
    return ctx


@dataclass(frozen=True)
class TelegramClient:
    """
    Một client để tương tác với Telegram Bot API một cách đơn giản và an toàn.

    Attributes:
        token: API token của bot.
        chat_id: ID mặc định của cuộc trò chuyện để gửi tin nhắn.
        ca_path: Đường dẫn tùy chỉnh đến CA bundle.
        skip_verify: Bỏ qua xác minh SSL (không khuyến khích).
        timeout: Thời gian chờ (giây) cho mỗi yêu cầu mạng.
    """
    token: str
    chat_id: Optional[str] = None
    ca_path: Optional[str] = None
    skip_verify: bool = False
    timeout: int = 15

    @classmethod
    def from_config(cls, cfg: RunConfig, timeout: int = 15) -> TelegramClient:
        """
        Tạo một instance TelegramClient từ đối tượng cấu hình RunConfig.

        Args:
            cfg: Đối tượng RunConfig chứa thông tin cấu hình.
            timeout: Thời gian chờ cho các yêu cầu.

        Returns:
            Một instance mới của TelegramClient.
        """
        logger.debug("Đang khởi tạo TelegramClient từ cấu hình.")
        return cls(
            token=cfg.telegram.token,
            chat_id=cfg.telegram.chat_id or None,
            ca_path=cfg.telegram.ca_path or None,
            skip_verify=cfg.telegram.skip_verify,
            timeout=timeout,
        )

    def _get_opener(self) -> urllib.request.OpenerDirector:
        """Tạo một opener cho urllib với SSL context đã được cấu hình."""
        logger.debug("Đang tạo urllib opener với SSL context.")
        ctx = build_ssl_context(self.ca_path, self.skip_verify)
        return urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx))

    def _parse_response(
        self, response: http.client.HTTPResponse
    ) -> Tuple[bool, dict]:
        """
        Phân tích cú pháp phản hồi HTTP từ API Telegram và trả về kết quả.

        Args:
            response: Đối tượng phản hồi HTTP từ urllib.

        Returns:
            Một tuple (bool, dict) chứa trạng thái thành công và dữ liệu JSON.
        """
        body = response.read().decode("utf-8", errors="ignore")
        response_json = json.loads(body)
        is_ok = bool(response_json.get("ok"))
        return is_ok, response_json

    def api_call(self, method: str, params: dict) -> Tuple[bool, dict]:
        """
        Thực hiện một cuộc gọi đến Telegram Bot API.

        Thử gửi bằng phương thức POST trước, nếu thất bại sẽ thử lại bằng GET.

        Args:
            method: Tên phương thức API (ví dụ: "sendMessage").
            params: Một dictionary chứa các tham số cho cuộc gọi API.

        Returns:
            Một tuple (bool, dict) trong đó:
            - bool: True nếu cuộc gọi thành công, False nếu thất bại.
            - dict: Phản hồi từ API dưới dạng dictionary.
        """
        if not self.token:
            logger.error("Không thể thực hiện cuộc gọi API: Thiếu Telegram token.")
            return False, {"error": "missing_token"}

        base_url = f"https://api.telegram.org/bot{self.token}/{method}"
        data = urllib.parse.urlencode(params).encode("utf-8")
        opener = self._get_opener()

        # Ưu tiên sử dụng POST
        try:
            logger.debug(f"Đang thực hiện API call (POST) đến method '{method}'.")
            req = urllib.request.Request(base_url, data=data)
            with opener.open(req, timeout=self.timeout) as resp:
                is_ok, response_json = self._parse_response(resp)
                logger.debug(f"Cuộc gọi API (POST) thành công. OK={is_ok}.")
                return is_ok, response_json
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="ignore") if hasattr(e, "read") else ""
            logger.warning(f"Lỗi HTTPError (POST) khi gọi method '{method}': {e.code}. Body: {body[:200]}")
        except Exception:
            logger.exception(f"Lỗi không xác định (POST) khi gọi method '{method}'.")

        # Nếu POST thất bại, thử lại bằng GET
        try:
            logger.debug(f"Thử lại API call (GET) cho method '{method}'.")
            full_url = f"{base_url}?{urllib.parse.urlencode(params)}"
            with opener.open(full_url, timeout=self.timeout) as resp:
                is_ok, response_json = self._parse_response(resp)
                logger.debug(f"Cuộc gọi API (GET) thành công. OK={is_ok}.")
                return is_ok, response_json
        except Exception:
            logger.exception(f"Lỗi không xác định (GET) khi gọi method '{method}'.")
            return False, {"error": "API call failed after fallback to GET"}

    def send_message(
        self,
        text: str,
        *,
        chat_id: Optional[str] = None,
        parse_mode: str = "HTML",
        disable_web_page_preview: bool = True,
        truncate_to: int = 3900,
    ) -> Tuple[bool, dict]:
        """
        Gửi một tin nhắn văn bản đến một cuộc trò chuyện.

        Args:
            text: Nội dung tin nhắn.
            chat_id: ID của cuộc trò chuyện. Nếu None, sử dụng chat_id mặc định.
            parse_mode: Chế độ phân tích cú pháp (HTML hoặc MarkdownV2).
            disable_web_page_preview: Vô hiệu hóa xem trước link trong tin nhắn.
            truncate_to: Cắt ngắn tin nhắn nếu dài hơn giới hạn ký tự.

        Returns:
            Tuple (bool, dict) từ kết quả của `api_call`.
        """
        target_chat_id = (chat_id or self.chat_id or "").strip()
        if not target_chat_id:
            logger.error("Không thể gửi tin nhắn: Thiếu chat_id.")
            return False, {"error": "missing_chat_id"}

        if truncate_to and len(text) > truncate_to:
            text = text[:truncate_to] + "\n... (đã rút gọn)"
            logger.warning(f"Tin nhắn đã được rút gọn xuống còn {truncate_to} ký tự.")

        params = {
            "chat_id": target_chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": str(disable_web_page_preview),
        }
        logger.info(f"Đang gửi tin nhắn đến chat_id: {target_chat_id[:5]}...")
        return self.api_call("sendMessage", params)

    @staticmethod
    def build_trade_message(
        lines: list[str],
        saved_report_path: Optional[Path],
        *,
        symbol: str,
        now: Optional[datetime] = None,
        max_per_line: int = 220,
    ) -> str:
        """
        Xây dựng một tin nhắn được định dạng chuẩn để thông báo về một cơ hội giao dịch.

        Args:
            lines: Danh sách các dòng nội dung chính của tin nhắn.
            saved_report_path: Đường dẫn đến file báo cáo đã lưu.
            symbol: Tên của cặp tiền tệ/tài sản.
            now: Thời gian hiện tại (để testing).
            max_per_line: Giới hạn ký tự cho mỗi dòng trong `lines`.

        Returns:
            Một chuỗi đã được định dạng HTML sẵn sàng để gửi qua Telegram.
        """
        logger.debug(f"Đang xây dựng tin nhắn giao dịch cho symbol: {symbol}.")
        timestamp = (now or datetime.now()).strftime("%Y-%m-%d %H:%M:%S")

        cleaned_lines: list[str] = []
        for line in lines:
            line = re.sub(r"\s+", " ", (line or "")).strip()
            if len(line) > max_per_line:
                line = line[: max_per_line - 1] + "…"
            cleaned_lines.append(tg_html_escape(line))

        symbol_safe = tg_html_escape(symbol)
        saved_safe = tg_html_escape(saved_report_path.name) if saved_report_path else "N/A"
        ts_safe = tg_html_escape(timestamp)

        message_body = "\n".join(cleaned_lines)
        message = (
            f"🔔 <b>TÍN HIỆU GIAO DỊCH</b>\n"
            f"🕒 {ts_safe}\n"
            f"📈 <b>Symbol:</b> {symbol_safe}\n\n"
            f"{message_body}\n\n"
            f"<i>(Đã lưu báo cáo: {saved_safe})</i>"
        )
        logger.debug(f"Đã xây dựng xong tin nhắn. Độ dài: {len(message)} ký tự.")
        return message
