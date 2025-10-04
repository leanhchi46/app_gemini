from __future__ import annotations

import base64
import hashlib
import platform
import logging

logger = logging.getLogger(__name__)

def _xor_bytes(a: bytes, b: bytes) -> bytes:
    """
    Thực hiện phép toán XOR bitwise giữa hai chuỗi byte.
    """
    return bytes(x ^ y for x, y in zip(a, b))

def _machine_key() -> bytes:
    """
    Tạo một khóa máy duy nhất dựa trên thông tin hệ thống.
    """
    info = f"{platform.system()}-{platform.machine()}-{platform.node()}"
    key = hashlib.sha256(info.encode("utf-8")).digest()
    return key

def obfuscate_text(text: str) -> str:
    """
    Mã hóa một chuỗi văn bản bằng cách sử dụng phép XOR với khóa máy và mã hóa Base64.
    """
    if not text:
        return ""
    key = _machine_key()
    data = text.encode("utf-8")
    encrypted = _xor_bytes(data, key * (len(data) // len(key) + 1))
    return base64.b64encode(encrypted).decode("utf-8")

def deobfuscate_text(b64_text: str) -> str:
    """
    Giải mã một chuỗi văn bản đã được mã hóa Base64.
    """
    if not b64_text:
        return ""
    key = _machine_key()
    try:
        b64_text += '=' * (-len(b64_text) % 4)
        encrypted = base64.b64decode(b64_text.encode("utf-8"))
        decrypted = _xor_bytes(encrypted, key * (len(encrypted) // len(key) + 1))
        return decrypted.decode("utf-8")
    except Exception:
        return ""

def tg_html_escape(text: str) -> str:
    """
    Thực hiện HTML escape cho văn bản để sử dụng an toàn trong Telegram.
    """
    if not text:
        return ""
    return text.replace("&", "&").replace("<", "<").replace(">", ">")
