# -*- coding: utf-8 -*-
"""
Các hàm tiện ích chung được sử dụng trong toàn bộ ứng dụng.

Bao gồm các chức năng mã hóa/giải mã văn bản, dọn dẹp file cũ,
và các hàm hỗ trợ khác không thuộc về một module cụ thể nào.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import logging
import os
import platform
import re
from collections import Counter
from datetime import timedelta
from pathlib import Path
from typing import Iterable, Mapping, Sequence

logger = logging.getLogger(__name__)


_SYMBOL_STOPWORDS = {
    "IMG",
    "IMAGE",
    "SCREENSHOT",
    "SNAPSHOT",
    "PHOTO",
    "WHATSAPP",
    "TELEGRAM",
    "EXPORT",
    "CAPTURE",
    "ANALYSIS",
    "REPORT",
    "SETUP",
    "TRADINGVIEW",
    "CHART",
    "PLAN",
    "TRADE",
    "ENTRY",
    "EXIT",
    "BUY",
    "SELL",
    "LONG",
    "SHORT",
}

_TIMEFRAME_SUFFIXES = (
    "M1",
    "M5",
    "M15",
    "M30",
    "H1",
    "H2",
    "H4",
    "D1",
    "D4",
    "W1",
    "MN",
    "MN1",
)


def _xor_bytes(a: bytes, b: bytes) -> bytes:
    """
    Thực hiện phép toán XOR bitwise giữa hai chuỗi byte.

    Args:
        a: Chuỗi byte thứ nhất.
        b: Chuỗi byte thứ hai.

    Returns:
        Chuỗi byte kết quả của phép XOR.
    """
    logger.debug("Thực hiện XOR bytes.")
    return bytes(x ^ y for x, y in zip(a, b))


def _machine_key() -> bytes:
    """
    Tạo một khóa máy duy nhất dựa trên thông tin hệ thống.

    Returns:
        Khóa máy dưới dạng chuỗi byte SHA256.
    """
    logger.debug("Tạo machine key.")
    # Loại bỏ platform.node() để tránh lỗi khi tên máy tính thay đổi.
    # Khóa giờ đây sẽ ổn định hơn trên cùng một máy.
    info = f"{platform.system()}-{platform.machine()}"
    key = hashlib.sha256(info.encode("utf-8")).digest()
    logger.debug(f"Đã tạo machine key. Độ dài: {len(key)} bytes.")
    return key


def obfuscate_text(text: str, salt: str) -> str:
    """
    Mã hóa một chuỗi văn bản bằng cách sử dụng phép XOR với khóa máy, salt và mã hóa Base64.

    Args:
        text: Chuỗi văn bản cần mã hóa.
        salt: Chuỗi salt để tăng cường bảo mật.

    Returns:
        Chuỗi văn bản đã được mã hóa Base64.
    """
    logger.debug("Bắt đầu obfuscate text với salt.")
    machine = _machine_key()
    salt_bytes = hashlib.sha256(salt.encode("utf-8")).digest()
    key = hashlib.sha256(machine + salt_bytes).digest()

    data = text.encode("utf-8")
    encrypted = _xor_bytes(data, key * (len(data) // len(key) + 1))
    result = base64.b64encode(encrypted).decode("utf-8")
    logger.debug("Đã obfuscate text thành công.")
    return result


def deobfuscate_text(b64_text: str, salt: str) -> str:
    """
    Giải mã một chuỗi văn bản đã được mã hóa Base64 bằng cách sử dụng phép XOR với khóa máy và salt.

    Args:
        b64_text: Chuỗi văn bản đã được mã hóa Base64.
        salt: Chuỗi salt đã được sử dụng để mã hóa.

    Returns:
        Chuỗi văn bản đã được giải mã. Trả về chuỗi rỗng nếu có lỗi giải mã.
    """
    logger.debug("Bắt đầu deobfuscate text với salt.")
    machine = _machine_key()
    salt_bytes = hashlib.sha256(salt.encode("utf-8")).digest()
    key = hashlib.sha256(machine + salt_bytes).digest()
    try:
        # Fix incorrect padding
        b64_text += "=" * (-len(b64_text) % 4)
        encrypted = base64.b64decode(b64_text.encode("utf-8"))
        decrypted = _xor_bytes(encrypted, key * (len(encrypted) // len(key) + 1))
        # Sử dụng errors='replace' để xử lý các byte không hợp lệ,
        # tránh crash và trả về một chuỗi có thể kiểm tra được.
        result = decrypted.decode("utf-8", errors="replace")
        # Kiểm tra xem kết quả có chứa ký tự thay thế không (U+FFFD),
        # điều này cho thấy có lỗi giải mã.
        if "\ufffd" in result:
            logger.warning(
                "Giải mã text tạo ra các ký tự không hợp lệ. "
                "Khóa hoặc dữ liệu có thể bị hỏng. Trả về chuỗi rỗng."
            )
            return ""
        logger.debug("Đã deobfuscate text thành công.")
        return result
    except (ValueError, TypeError, binascii.Error) as e:
        logger.warning(f"Lỗi khi deobfuscate text: {e}. Trả về chuỗi rỗng.")
        # Return empty string if the key is corrupted or invalid
        return ""


def tg_html_escape(text: str) -> str:
    """
    Thực hiện HTML escape cho văn bản để sử dụng an toàn trong Telegram.

    Args:
        text: Chuỗi văn bản cần escape.

    Returns:
        Chuỗi văn bản đã được HTML escape.
    """
    logger.debug("Thực hiện HTML escape cho Telegram.")
    if not text:
        return ""
    return text.replace("&", "&").replace("<", "<").replace(">", ">")


def cleanup_old_files(directory: Path, pattern: str, keep_n: int) -> None:
    """
    Xóa các tệp cũ nhất trong một thư mục khớp với một mẫu, chỉ giữ lại n tệp mới nhất.

    Args:
        directory: Đường dẫn đến thư mục cần dọn dẹp.
        pattern: Mẫu glob để khớp với tên tệp (ví dụ: "*.log").
        keep_n: Số lượng tệp mới nhất cần giữ lại.
    """
    logger.debug(
        f"Bắt đầu cleanup_old_files trong thư mục: {directory}, "
        f"pattern: {pattern}, giữ lại: {keep_n} file."
    )
    if not directory or not directory.is_dir() or keep_n < 0:
        logger.warning(
            "Điều kiện cleanup không hợp lệ (directory trống/không tồn tại, hoặc keep_n < 0)."
        )
        return
    try:
        files = sorted(directory.glob(pattern), key=os.path.getmtime, reverse=True)
        if len(files) > keep_n:
            for p in files[keep_n:]:
                try:
                    p.unlink()
                    logger.debug(f"Đã xóa file cũ: {p.name}")
                except OSError as e:
                    logger.warning(f"Lỗi khi xóa file '{p.name}': {e}")
    except Exception as e:
        logger.error(f"Lỗi trong quá trình cleanup_old_files: {e}")
    finally:
        logger.debug("Kết thúc cleanup_old_files.")


def _strip_timeframe_suffix(token: str) -> str:
    """Loại bỏ hậu tố timeframe phổ biến (ví dụ: M15, H4)."""

    for suffix in _TIMEFRAME_SUFFIXES:
        if token.endswith(suffix) and len(token) > len(suffix) + 2:
            return token[: -len(suffix)]
    return token


def _strip_long_digit_suffix(token: str) -> str:
    """Loại bỏ chuỗi chữ số dài ở cuối token (thường là ngày/tháng)."""

    match = re.search(r"(.*?)(\d{3,})$", token)
    if match and len(match.group(1)) >= 3:
        return match.group(1)
    return token


def _normalize_symbol_token(token: str) -> str | None:
    """Chuẩn hóa token thành symbol hợp lệ hoặc trả về None nếu không phù hợp."""

    token = token.strip().upper()
    if not token:
        return None

    token = _strip_timeframe_suffix(token)
    token = _strip_long_digit_suffix(token)

    if not token or token in _SYMBOL_STOPWORDS:
        return None

    token = token.lstrip("0123456789")
    if not token or token in _SYMBOL_STOPWORDS:
        return None

    letters = sum(1 for c in token if c.isalpha())
    digits = sum(1 for c in token if c.isdigit())

    if letters == 0:
        return None

    if letters < 3:
        if not (letters == 2 and digits and len(token) >= 4):
            return None

    if len(token) < 4 and digits == 0:
        return None

    if any(not c.isalnum() for c in token):
        return None

    return token


def _extract_symbol_candidates(filename: str) -> list[str]:
    """Trích xuất các symbol tiềm năng từ tên file."""

    stem = Path(filename).stem.upper()
    if not stem:
        return []

    raw_tokens = [t for t in re.split(r"[^A-Z0-9]+", stem) if t]
    matches = [m.group(0) for m in re.finditer(r"[A-Z]{3,}[A-Z0-9]*", stem)]
    tokens = raw_tokens + matches

    candidates: list[str] = []

    for token in tokens:
        normalized = _normalize_symbol_token(token)
        if normalized:
            candidates.append(normalized)

    for idx in range(len(raw_tokens) - 1):
        left, right = raw_tokens[idx], raw_tokens[idx + 1]
        if len(left) == len(right) == 3 and left.isalpha() and right.isalpha():
            combined = _normalize_symbol_token(left + right)
            if combined:
                candidates.append(combined)

    return candidates


def _symbol_rank(symbol: str) -> tuple[int, int, int, int, str]:
    """Xác định độ ưu tiên của symbol (ưu tiên độ dài ~6 và ít chữ số)."""

    letters = sum(1 for c in symbol if c.isalpha())
    digits = sum(1 for c in symbol if c.isdigit())
    return (
        1 if letters >= 3 else 0,
        -abs(len(symbol) - 6),
        letters,
        -digits,
        symbol,
    )


def guess_symbol_from_filenames(
    filenames: Sequence[str] | Iterable[str],
    allowed_symbols: Iterable[str] | None = None,
) -> tuple[str | None, Mapping[str, int]]:
    """Đoán symbol phổ biến nhất từ danh sách tên file."""

    allowed = {sym.strip().upper() for sym in allowed_symbols or [] if sym.strip()}
    counter: Counter[str] = Counter()

    for name in filenames:
        if not name:
            continue
        candidates = set(_extract_symbol_candidates(name))
        if allowed:
            candidates = {c for c in candidates if c in allowed}
        for cand in candidates:
            counter[cand] += 1

    if not counter:
        return None, {}

    best_symbol, _ = max(counter.items(), key=lambda item: (item[1], _symbol_rank(item[0])))
    sorted_counts = dict(sorted(counter.items(), key=lambda item: (-item[1], item[0])))
    return best_symbol, sorted_counts


def extract_symbol_from_filename(filename: str) -> str | None:
    """
    Trích xuất mã symbol (ví dụ: XAUUSD, EURUSD) từ tên file.

    Sử dụng các heuristics để tìm symbol tiềm năng và chọn kết quả phù hợp nhất.

    Args:
        filename: Tên file đầu vào.

    Returns:
        Symbol được tìm thấy hoặc None nếu không tìm thấy.
    """
    symbol, _ = guess_symbol_from_filenames([filename])
    if symbol:
        logger.debug(f"Đã trích xuất symbol '{symbol}' từ '{filename}'.")
        return symbol
    logger.debug(f"Không tìm thấy symbol nào trong '{filename}'.")
    return None


def format_timedelta(td: timedelta) -> str:
    """
    Định dạng một đối tượng timedelta thành một chuỗi dễ đọc.

    Ví dụ: 2 days, 5 hours -> "2d 5h", 30 minutes -> "30m"

    Args:
        td: Đối tượng timedelta cần định dạng.

    Returns:
        Chuỗi đã được định dạng.
    """
    parts = []
    total_seconds = int(td.total_seconds())
    
    if total_seconds < 0:
        return "đã qua"

    days = total_seconds // 86400
    hours = (total_seconds % 86400) // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60

    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0 and days == 0: # Chỉ hiển thị phút nếu không có ngày
        parts.append(f"{minutes}m")
    if not parts and seconds > 0: # Chỉ hiển thị giây nếu không có gì khác
        parts.append(f"{seconds}s")
    
    return " ".join(parts) if parts else "bây giờ"
