# src/ui/timeframe_detector.py
from __future__ import annotations

from pathlib import Path
import re
from typing import TYPE_CHECKING
import logging # Thêm import logging

logger = logging.getLogger(__name__) # Khởi tạo logger


def _detect_timeframe_from_name(name: str) -> str:
    """
    Phát hiện khung thời gian (timeframe) từ tên file ảnh bằng cách sử dụng các mẫu regex.
    Ví dụ: "EURUSD_M5.png" sẽ trả về "M5".
    """
    logger.debug(f"Bắt đầu _detect_timeframe_from_name cho tên file: {name}")
    s = Path(name).stem.lower()

    # Các mẫu regex để nhận dạng khung thời gian từ tên tệp.
    # `(?<![a-z0-9])` và `(?![a-z0-9])` đảm bảo rằng chúng ta khớp toàn bộ từ (ví dụ: "m5" chứ không phải "m50").
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
            logger.debug(f"Đã phát hiện timeframe '{tf}' cho '{name}' bằng pattern '{pat}'.")
            return tf
    logger.debug(f"Không phát hiện được timeframe cho '{name}', trả về '?'.")
    return "?"

def _build_timeframe_section(names: list[str]) -> str:
    """
    Xây dựng một chuỗi văn bản liệt kê các file ảnh và khung thời gian tương ứng của chúng.
    """
    logger.debug(f"Bắt đầu _build_timeframe_section với {len(names)} tên file.")
    lines = []
    for n in names:
        tf = _detect_timeframe_from_name(n)
        lines.append(f"- {n} ⇒ {tf}")
        logger.debug(f"Đã thêm '{n} ⇒ {tf}' vào section.")
    result = "\n".join(lines)
    logger.debug("Kết thúc _build_timeframe_section.")
    return result

def images_tf_map(names: list[str], detect_timeframe_func) -> dict[str, str]:
    """
    Tạo một bản đồ (dictionary) từ tên file ảnh sang khung thời gian (timeframe) tương ứng.
    """
    logger.debug(f"Bắt đầu images_tf_map với {len(names)} tên file.")
    result = {name: detect_timeframe_func(name) for name in names}
    logger.debug(f"Kết thúc images_tf_map. Map: {result}")
    return result
