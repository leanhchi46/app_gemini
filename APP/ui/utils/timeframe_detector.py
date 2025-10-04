from __future__ import annotations

from pathlib import Path
import re
import logging

logger = logging.getLogger(__name__)


def detect_from_name(name: str) -> str:
    """
    Phát hiện khung thời gian (timeframe) từ tên tệp hình ảnh.
    """
    s = Path(name).stem.lower()
    patterns = [
        ("MN1", r"(?<![a-z0-9])(?:mn1|1mo|monthly)(?![a-z0-9])"),
        ("W1", r"(?<![a-z0-9])(?:w1|1w|weekly)(?![a-z0-9])"),
        ("D1", r"(?<![a-z0-9])(?:d1|1d|daily)(?![a-z0-9])"),
        ("H4", r"(?<![a-z0-9])(?:h4|4h)(?![a-z0-9])"),
        ("H1", r"(?<![a-z0-9])(?:h1|1h)(?![a-z0-9])"),
        ("M30", r"(?<![a-z0-9])(?:m30|30m)(?![a-z0-9])"),
        ("M15", r"(?<![a-z0-9])(?:m15|15m)(?![a-z0-9])"),
        ("M5", r"(?<![a-z0-9])(?:m5|5m)(?![a-z0-9])"),
        ("M1", r"(?<![a-z0-9])(?:m1|1m)(?![a-z0-9])"),
    ]
    for tf, pat in patterns:
        if re.search(pat, s):
            return tf
    return "?"


def build_timeframe_section(names: list[str]) -> str:
    """
    Xây dựng một chuỗi văn bản liệt kê các tệp và khung thời gian tương ứng.
    """
    lines = [f"- {n} ⇒ {detect_from_name(n)}" for n in names]
    return "\n".join(lines)


def create_timeframe_map(names: list[str]) -> dict[str, str]:
    """
    Tạo một dictionary từ tên tệp sang khung thời gian.
    """
    return {name: detect_from_name(name) for name in names}
