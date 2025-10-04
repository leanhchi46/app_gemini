from __future__ import annotations

import json
import re
import ssl
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple
import logging # Thêm import logging

from src.utils.utils import _tg_html_escape

logger = logging.getLogger(__name__) # Khởi tạo logger

try:
    import certifi  # type: ignore
except Exception as e:  # pragma: no cover - optional dependency
    certifi = None  # type: ignore
    logger.warning(f"Không thể import certifi: {e}. Sẽ sử dụng CA mặc định của hệ thống.")


def build_ssl_context(cafile: Optional[str], skip_verify: bool) -> ssl.SSLContext:
    """Create an SSLContext using a provided CA file, certifi, or system defaults.

    - cafile: path to CA bundle (PEM/CRT). If None, try certifi, else system default.
    - skip_verify: if True, disable hostname check and verification (insecure).
    """
    logger.debug(f"Bắt đầu build_ssl_context. cafile: {cafile}, skip_verify: {skip_verify}")
    try:
        if cafile:
            ctx = ssl.create_default_context(cafile=cafile)
            logger.debug(f"Đã tạo SSLContext với cafile: {cafile}")
        elif certifi is not None:
            ctx = ssl.create_default_context(cafile=certifi.where())
            logger.debug("Đã tạo SSLContext với certifi.")
        else:
            ctx = ssl.create_default_context()
            logger.debug("Đã tạo SSLContext mặc định.")
    except Exception as e:
        ctx = ssl.create_default_context()
        logger.error(f"Lỗi khi tạo SSLContext, sử dụng mặc định: {e}")
    if skip_verify:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        logger.warning("Đã bỏ qua xác minh SSL (INSECURE).")
    logger.debug("Kết thúc build_ssl_context.")
    return ctx


@dataclass
class TelegramClient:
    token: str
    chat_id: Optional[str] = None
    ca_path: Optional[str] = None
    skip_verify: bool = False
    timeout: int = 15

    @classmethod
    def from_config(cls, cfg, timeout: int = 15) -> "TelegramClient":
        logger.debug("Bắt đầu TelegramClient.from_config.")
        client = cls(
            token=cfg.telegram_token,
            chat_id=(cfg.telegram_chat_id or None),
            ca_path=(cfg.telegram_ca_path or None),
            skip_verify=bool(getattr(cfg, "telegram_skip_verify", False)),
            timeout=timeout,
        )
        logger.debug("Đã tạo TelegramClient từ config.")
        return client

    def _opener(self):
        logger.debug("Bắt đầu _opener.")
        ctx = build_ssl_context(self.ca_path, self.skip_verify)
        opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx))
        logger.debug("Đã tạo urllib opener.")
        return opener

    def api_call(self, method: str, params: dict, use_get_fallback: bool = True) -> Tuple[bool, dict]:
        logger.debug(f"Bắt đầu api_call cho method: {method}, params: {params}.")
        if not self.token:
            logger.error("Thiếu Telegram token.")
            return False, {"error": "missing_token"}
        base = f"https://api.telegram.org/bot{self.token}/{method}"
        data = urllib.parse.urlencode(params).encode("utf-8")
        opener = self._opener()

        # Try POST first
        try:
            req = urllib.request.Request(base, data=data)
            with opener.open(req, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8", errors="ignore")
                obj = None
                if body.startswith("{"):
                    try:
                        obj = json.loads(body)
                    except json.JSONDecodeError as e:
                        logger.warning(f"Lỗi JSONDecodeError khi parse body POST: {e}. Body: {body[:200]}...")
                        obj = None
                if obj is None:
                    obj = {"ok": resp.status == 200, "body": body}
                ok = bool(obj.get("ok", resp.status == 200))
                logger.debug(f"API POST call thành công. OK: {ok}, response: {obj}")
                return ok, obj
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="ignore") if hasattr(e, "read") else str(e)
            logger.warning(f"HTTPError trong API POST call: {getattr(e, 'code', '?')}. Body: {body[:200]}...")
            if not use_get_fallback:
                return False, {"error": f"HTTP {getattr(e, 'code', '?')}", "body": body}
        except urllib.error.URLError as e:
            logger.warning(f"URLError trong API POST call: {getattr(e, 'reason', e)}.")
            if not use_get_fallback:
                return False, {"error": f"URLError: {getattr(e, 'reason', e)}"}
        except json.JSONDecodeError as e:
            logger.warning(f"JSONDecodeError trong API POST call: {e}.")
            if not use_get_fallback:
                return False, {"error": f"JSONDecodeError: {e}"}
        except Exception as e:
            logger.error(f"Lỗi không xác định trong API POST call: {e}.")
            if not use_get_fallback:
                return False, {"error": str(e)}

        # Fallback to GET
        logger.debug("Thử lại API call với GET fallback.")
        try:
            url = base + "?" + urllib.parse.urlencode(params)
            with opener.open(url, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8", errors="ignore")
                obj = None
                if body.startswith("{"):
                    try:
                        obj = json.loads(body)
                    except json.JSONDecodeError as e:
                        logger.warning(f"Lỗi JSONDecodeError khi parse body GET: {e}. Body: {body[:200]}...")
                        obj = None
                if obj is None:
                    obj = {"ok": resp.status == 200, "body": body}
                ok = bool(obj.get("ok", resp.status == 200))
                logger.debug(f"API GET call thành công. OK: {ok}, response: {obj}")
                return ok, obj
        except Exception as e2:
            logger.error(f"Lỗi không xác định trong API GET call: {e2}.")
            return False, {"error": str(e2)}

    def send_message(
        self,
        text: str,
        *,
        chat_id: Optional[str] = None,
        parse_mode: str = "HTML",
        disable_web_page_preview: bool = True,
        truncate_to: int = 3900,
    ) -> Tuple[bool, dict]:
        logger.debug(f"Bắt đầu send_message. Chat ID: {chat_id or self.chat_id}, độ dài text: {len(text)}.")
        cid = (chat_id or self.chat_id or "").strip()
        if not cid:
            logger.error("Thiếu chat_id để gửi tin nhắn Telegram.")
            return False, {"error": "missing_chat_id"}
        if text is None:
            text = ""
        if truncate_to and len(text) > truncate_to:
            text = text[:truncate_to] + "\n. (đã rút gọn)"
            logger.warning(f"Tin nhắn đã bị rút gọn xuống {truncate_to} ký tự.")
        params = {
            "chat_id": cid,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": disable_web_page_preview,
        }
        ok, res = self.api_call("sendMessage", params)
        logger.debug(f"Kết thúc send_message. OK: {ok}, response: {res}")
        return ok, res

    @staticmethod
    def build_message(
        seven_lines: list[str],
        saved_report_path: Optional[Path],
        *,
        folder: str,
        now: Optional[datetime] = None,
        max_per_line: int = 220,
    ) -> str:
        logger.debug(f"Bắt đầu build_message. Folder: {folder}, saved_report_path: {saved_report_path}.")
        ts = (now or datetime.now()).strftime("%Y-%m-%d %H:%M:%S")
        cleaned: list[str] = []
        for ln in seven_lines:
            ln = re.sub(r"\s+", " ", (ln or "")).strip()
            if len(ln) > max_per_line:
                ln = ln[: max_per_line - 1] + "."
                logger.debug(f"Dòng tin nhắn bị rút gọn: {ln}")
            cleaned.append(_tg_html_escape(ln))

        folder_safe = _tg_html_escape(folder)
        saved_safe = _tg_html_escape(saved_report_path.name) if saved_report_path else None
        ts_safe = _tg_html_escape(ts)

        msg = (
            "🔔 <b>Setup xác suất cao</b>\n"
            f"🕒 {ts_safe}\n"
            f"📂 {folder_safe}\n\n"
            + "\n".join(cleaned)
            + (f"\n\n(Đã lưu: {saved_safe})" if saved_safe else "")
        )
        logger.debug(f"Đã xây dựng tin nhắn Telegram. Độ dài: {len(msg)}.")
        return msg
