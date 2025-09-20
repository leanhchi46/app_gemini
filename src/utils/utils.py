import base64
import hashlib
import os
from pathlib import Path
import platform
import ssl
from datetime import datetime
import re

def _xor_bytes(a: bytes, b: bytes) -> bytes:
    return bytes(x ^ y for x, y in zip(a, b))

def _machine_key() -> bytes:
    info = f"{platform.system()}-{platform.machine()}-{platform.node()}"
    return hashlib.sha256(info.encode("utf-8")).digest()

def obfuscate_text(text: str) -> str:
    key = _machine_key()
    data = text.encode("utf-8")
    encrypted = _xor_bytes(data, key * (len(data) // len(key) + 1))
    return base64.b64encode(encrypted).decode("utf-8")

def deobfuscate_text(b64_text: str) -> str:
    key = _machine_key()
    try:
        # Fix incorrect padding
        b64_text += '=' * (-len(b64_text) % 4)
        encrypted = base64.b64decode(b64_text.encode("utf-8"))
        decrypted = _xor_bytes(encrypted, key * (len(encrypted) // len(key) + 1))
        return decrypted.decode("utf-8")
    except (ValueError, TypeError, base64.binascii.Error):
        # Return empty string if the key is corrupted or invalid
        return ""

def _tg_html_escape(text: str) -> str:
    if not text:
        return ""
    return text.replace("&", "&").replace("<", "<").replace(">", ">")

def cleanup_old_files(directory: Path, pattern: str, keep_n: int):
    """
    Deletes the oldest files in a directory matching a pattern, keeping only the n newest ones.
    """
    if not directory or not directory.is_dir() or keep_n <= 0:
        return
    try:
        files = sorted(directory.glob(pattern), key=os.path.getmtime, reverse=True)
        if len(files) > keep_n:
            for p in files[keep_n:]:
                try:
                    p.unlink()
                except Exception:
                    pass # Silently ignore if a single file fails to delete
    except Exception:
        pass # Silently ignore if the cleanup process fails

def detect_timeframe_from_name(name: str) -> str:
    """
    Nhận diện khung thời gian (timeframe) từ tên tệp.
    """
    s = Path(name).stem.lower()
    patterns = [
        ("MN1", r"(?<![a-z0-9])(?:mn1|1mo|monthly)(?![a-z0-9])"),
        ("W1",  r"(?<![a-z0-9])(?:w1|1w|weekly)(?![a-z0-9])"),
        ("D1",  r"(?<![a-z0-9])(?:d1|1d|daily)(?![a-z0-9])"),
        ("H4",  r"(?<![a-z0-9])(?:h4|4h)(?![a-z0-9])"),
        ("H1",  r"(?<![a-z0-9])(?:h1|1h)(?![a-z0-9])"),
        ("M30", r"(?<![a-z0-9])(?:m30|30m)(?![a-z0-9])"),
        ("M15", r"(?<![a-z0-9])(?:m15|15m)(?![a-z0-9])"),
        ("M5",  r"(?<![a-z0-9])(?:m5|5m)(?![a-z0-9])"),
        ("M1",  r"(?<![a-z0-9])(?:m1|1m)(?![a-z0-9])"),
    ]
    for tf, pat in patterns:
        if re.search(pat, s):
            return tf
    return "?"

def build_timeframe_section(names: list[str]) -> str:
    """
    Xây dựng một chuỗi mô tả các khung thời gian được nhận diện từ danh sách tên tệp.
    """
    lines = []
    for n in names:
        tf = detect_timeframe_from_name(n)
        lines.append(f"- {n} ⇒ {tf}")
    return "\n".join(lines)
