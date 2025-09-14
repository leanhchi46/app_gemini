"""
Gửi báo cáo qua Telegram, kiểm tra kết nối, gửi thử
"""

import urllib.parse
import urllib.request
import json
import ssl

def telegram_api_call(token: str, method: str, params: dict, cafile=None, skip_verify=False, timeout=15):
    """
    Gửi API call tới Telegram Bot.
    """
    base = f"https://api.telegram.org/bot{token}/{method}"
    data = urllib.parse.urlencode(params).encode("utf-8")
    ctx = ssl.create_default_context(cafile=cafile) if cafile else ssl.create_default_context()
    if skip_verify:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx))
    try:
        req = urllib.request.Request(base, data=data)
        with opener.open(req, timeout=timeout) as resp:
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
    except Exception as e:
        return False, {"error": str(e)}

def send_telegram_message(token: str, chat_id: str, text: str, cafile=None, skip_verify=False):
    params = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    return telegram_api_call(token, "sendMessage", params, cafile, skip_verify)