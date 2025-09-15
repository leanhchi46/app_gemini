import os
import sys
import base64
import hashlib


def _xor_bytes(data: bytes, key: bytes) -> bytes:
    if not key:
        return data
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(data))


def _machine_key() -> bytes:
    base = (
        os.name + os.getenv("USERNAME", "") + os.getenv("COMPUTERNAME", "") + sys.executable
    ).encode("utf-8")
    return hashlib.sha256(base).digest()


def obfuscate_text(s: str) -> str:
    raw = s.encode("utf-8")
    key = _machine_key()
    enc = _xor_bytes(raw, key)
    return base64.urlsafe_b64encode(enc).decode("ascii")


def deobfuscate_text(s: str) -> str:
    if not s:
        return ""
    try:
        enc = base64.urlsafe_b64decode(s.encode("ascii"))
        raw = _xor_bytes(enc, _machine_key())
        return raw.decode("utf-8")
    except Exception:
        return ""


def _tg_html_escape(s: str) -> str:
    if s is None:
        return ""
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

