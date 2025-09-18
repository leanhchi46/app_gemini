import base64
import hashlib
import os
from pathlib import Path
import platform
import ssl
from datetime import datetime

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
