from __future__ import annotations

import json
import re
import ssl
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Tuple

try:
    import certifi  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    certifi = None  # type: ignore

from .utils import _tg_html_escape


def build_ssl_context(cafile: Optional[str], skip_verify: bool) -> ssl.SSLContext:
    """Create an SSLContext using a provided CA file, certifi, or system defaults.

    - cafile: path to CA bundle (PEM/CRT). If None, try certifi, else system default.
    - skip_verify: if True, disable hostname check and verification (insecure).
    """
    try:
        if cafile:
            ctx = ssl.create_default_context(cafile=cafile)
        elif certifi is not None:
            ctx = ssl.create_default_context(cafile=certifi.where())
        else:
            ctx = ssl.create_default_context()
    except Exception:
        ctx = ssl.create_default_context()
    if skip_verify:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
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
        return cls(
            token=cfg.telegram_token,
            chat_id=(cfg.telegram_chat_id or None),
            ca_path=(cfg.telegram_ca_path or None),
            skip_verify=bool(getattr(cfg, "telegram_skip_verify", False)),
            timeout=timeout,
        )

    def _opener(self):
        ctx = build_ssl_context(self.ca_path, self.skip_verify)
        return urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx))

    def api_call(self, method: str, params: dict, use_get_fallback: bool = True) -> Tuple[bool, dict]:
        if not self.token:
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
                    except json.JSONDecodeError:
                        obj = None
                if obj is None:
                    obj = {"ok": resp.status == 200, "body": body}
                ok = bool(obj.get("ok", resp.status == 200))
                return ok, obj
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="ignore") if hasattr(e, "read") else str(e)
            if not use_get_fallback:
                return False, {"error": f"HTTP {getattr(e, 'code', '?')}", "body": body}
        except urllib.error.URLError as e:
            if not use_get_fallback:
                return False, {"error": f"URLError: {getattr(e, 'reason', e)}"}
        except json.JSONDecodeError as e:
            if not use_get_fallback:
                return False, {"error": f"JSONDecodeError: {e}"}
        except Exception as e:
            if not use_get_fallback:
                return False, {"error": str(e)}

        # Fallback to GET
        try:
            url = base + "?" + urllib.parse.urlencode(params)
            with opener.open(url, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8", errors="ignore")
                obj = None
                if body.startswith("{"):
                    try:
                        obj = json.loads(body)
                    except json.JSONDecodeError:
                        obj = None
                if obj is None:
                    obj = {"ok": resp.status == 200, "body": body}
                ok = bool(obj.get("ok", resp.status == 200))
                return ok, obj
        except Exception as e2:
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
        cid = (chat_id or self.chat_id or "").strip()
        if not cid:
            return False, {"error": "missing_chat_id"}
        if text is None:
            text = ""
        if truncate_to and len(text) > truncate_to:
            text = text[:truncate_to] + "\n. (đã rút gọn)"
        params = {
            "chat_id": cid,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": disable_web_page_preview,
        }
        return self.api_call("sendMessage", params)

    @staticmethod
    def build_message(
        seven_lines: list[str],
        saved_report_path: Optional[Path],
        *,
        folder: str,
        now: Optional[datetime] = None,
        max_per_line: int = 220,
    ) -> str:
        ts = (now or datetime.now()).strftime("%Y-%m-%d %H:%M:%S")
        cleaned: list[str] = []
        for ln in seven_lines:
            ln = re.sub(r"\s+", " ", (ln or "")).strip()
            if len(ln) > max_per_line:
                ln = ln[: max_per_line - 1] + "."
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
        return msg

