from __future__ import annotations

import json
import logging
import ssl
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Optional, Tuple

from APP.utils.general_utils import tg_html_escape

if TYPE_CHECKING:
    from APP.configs.app_config import RunConfig

logger = logging.getLogger(__name__)

try:
    import certifi
except ImportError:
    certifi = None
    logger.warning("Không thể import certifi. Sẽ sử dụng CA mặc định của hệ thống.")


def build_ssl_context(cafile: Optional[str], skip_verify: bool) -> ssl.SSLContext:
    """Tạo SSLContext để sử dụng cho các kết nối HTTPS."""
    try:
        if cafile:
            ctx = ssl.create_default_context(cafile=cafile)
        elif certifi:
            ctx = ssl.create_default_context(cafile=certifi.where())
        else:
            ctx = ssl.create_default_context()
    except Exception as e:
        logger.error(f"Lỗi khi tạo SSLContext, sử dụng mặc định: {e}")
        ctx = ssl.create_default_context()

    if skip_verify:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        logger.warning("Đã bỏ qua xác minh SSL (INSECURE).")
    return ctx


@dataclass
class TelegramClient:
    token: str
    chat_id: Optional[str] = None
    ca_path: Optional[str] = None
    skip_verify: bool = False
    timeout: int = 15

    @classmethod
    def from_config(cls, cfg: RunConfig, timeout: int = 15) -> "TelegramClient":
        """Tạo một instance của TelegramClient từ đối tượng cấu hình."""
        return cls(
            token=cfg.telegram.token,
            chat_id=cfg.telegram.chat_id or None,
            ca_path=cfg.telegram.ca_path or None,
            skip_verify=bool(getattr(cfg.telegram, "skip_verify", False)),
            timeout=timeout,
        )

    def _get_opener(self) -> urllib.request.OpenerDirector:
        """Tạo một opener cho urllib với SSL context đã được cấu hình."""
        ctx = build_ssl_context(self.ca_path, self.skip_verify)
        return urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx))

    def api_call(self, method: str, params: dict) -> Tuple[bool, dict]:
        """Thực hiện một lệnh gọi API đến Telegram Bot API."""
        if not self.token:
            return False, {"error": "missing_token"}

        base_url = f"https://api.telegram.org/bot{self.token}/{method}"
        data = urllib.parse.urlencode(params).encode("utf-8")
        opener = self._get_opener()

        try:
            req = urllib.request.Request(base_url, data=data)  # POST request
            with opener.open(req, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8", errors="ignore")
                response_json = json.loads(body)
                return bool(response_json.get("ok")), response_json
        except Exception as e:
            logger.error(f"Lỗi khi gọi API Telegram '{method}': {e}")
            return False, {"error": str(e)}

    def send_message(
        self,
        text: str,
        *,
        chat_id: Optional[str] = None,
        parse_mode: str = "HTML",
        truncate_to: int = 3900,
    ) -> Tuple[bool, dict]:
        """Gửi một tin nhắn văn bản đến một chat."""
        cid = (chat_id or self.chat_id or "").strip()
        if not cid:
            return False, {"error": "missing_chat_id"}

        if len(text) > truncate_to:
            text = text[:truncate_to] + "\n... (đã rút gọn)"

        params = {
            "chat_id": cid,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }
        return self.api_call("sendMessage", params)

    @staticmethod
    def build_report_message(
        seven_lines: list[str],
        saved_report_path: Optional[Path],
        *,
        folder: str,
        now: Optional[datetime] = None,
    ) -> str:
        """Xây dựng nội dung tin nhắn báo cáo từ các dòng phân tích."""
        ts = (now or datetime.now()).strftime("%Y-%m-%d %H:%M:%S")
        cleaned_lines = [tg_html_escape(line.strip()) for line in seven_lines]

        folder_safe = tg_html_escape(folder)
        saved_safe = tg_html_escape(saved_report_path.name) if saved_report_path else ""

        lines = [
            "🔔 <b>Setup xác suất cao</b>",
            f"🕒 {ts}",
            f"📂 {folder_safe}",
            "",
            *cleaned_lines,
        ]
        if saved_safe:
            lines.extend(["", f"(Đã lưu: {saved_safe})"])

        return "\n".join(lines)
