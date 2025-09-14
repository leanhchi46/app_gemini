"""
Mã hóa/giải mã, obfuscate API key, các hàm bảo mật
"""

import os
import sys
import base64
import hashlib


def _xor_bytes(data: bytes, key: bytes) -> bytes:
    """
    Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
    """
    if not key:
        return data
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(data))


def _machine_key() -> bytes:
    """
    Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
    """
    base = (os.name + os.getenv("USERNAME", "") + os.getenv("COMPUTERNAME", "") + sys.executable).encode("utf-8")
    return hashlib.sha256(base).digest()


def obfuscate_text(s: str) -> str:
    """
    Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
    """
    raw = s.encode("utf-8")
    key = _machine_key()
    enc = _xor_bytes(raw, key)
    return base64.urlsafe_b64encode(enc).decode("ascii")


def deobfuscate_text(s: str) -> str:
    """
    Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
    """
    if not s:
        return ""
    try:
        enc = base64.urlsafe_b64decode(s.encode("ascii"))
        raw = _xor_bytes(enc, _machine_key())
        return raw.decode("utf-8")
    except Exception:
        return ""
