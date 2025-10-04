# -*- coding: utf-8 -*-
"""
Lớp tiện ích để phát hiện khung thời gian (timeframe) từ tên file ảnh.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Dict, List, Pattern

logger = logging.getLogger(__name__)


class TimeframeDetector:
    """
    Lớp tiện ích để phát hiện khung thời gian từ tên file ảnh.

    Cung cấp các phương thức để phân tích tên file và trích xuất thông tin
    về khung thời gian dựa trên các mẫu regex được định nghĩa trước.
    Các mẫu regex được biên dịch trước để tối ưu hóa hiệu suất.
    """

    def __init__(self) -> None:
        """
        Khởi tạo TimeframeDetector và biên dịch trước các mẫu regex.
        """
        # Các mẫu regex để nhận dạng khung thời gian từ tên tệp.
        # `(?<![a-z0-9])` và `(?![a-z0-9])` đảm bảo rằng chúng ta khớp toàn bộ từ
        # (ví dụ: "m5" chứ không phải "m50").
        raw_patterns: List[tuple[str, str]] = [
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
        
        # Cải tiến: Biên dịch trước các mẫu regex để tăng hiệu suất
        self.compiled_patterns: List[tuple[str, Pattern[str]]] = [
            (tf, re.compile(pattern)) for tf, pattern in raw_patterns
        ]
        
        logger.debug(
            "TimeframeDetector đã được khởi tạo và biên dịch %d mẫu regex.",
            len(self.compiled_patterns)
        )

    def detect_from_name(self, name: str) -> str:
        """
        Phát hiện khung thời gian (timeframe) từ một tên file ảnh.

        Args:
            name: Tên file ảnh (ví dụ: "EURUSD_M5.png").

        Returns:
            Chuỗi đại diện cho khung thời gian (ví dụ: "M5") hoặc "?" nếu không phát hiện được.
        """
        logger.debug("Bắt đầu phát hiện timeframe cho tên file: %s", name)
        stem = Path(name).stem.lower()

        for tf, compiled_pattern in self.compiled_patterns:
            if compiled_pattern.search(stem):
                logger.debug(
                    "Đã phát hiện timeframe '%s' cho '%s' bằng pattern đã biên dịch.",
                    tf, name
                )
                return tf

        logger.warning("Không phát hiện được timeframe cho '%s', trả về '?'.", name)
        return "?"

    def build_timeframe_section(self, names: List[str]) -> str:
        """
        Xây dựng một chuỗi văn bản liệt kê các file ảnh và khung thời gian tương ứng.

        Args:
            names: Danh sách các tên file ảnh.

        Returns:
            Một chuỗi đa dòng, mỗi dòng có định dạng "- {tên_file} ⇒ {timeframe}".
        """
        logger.debug("Bắt đầu xây dựng section timeframe với %d tên file.", len(names))
        lines = [f"- {n} ⇒ {self.detect_from_name(n)}" for n in names]
        result = "\n".join(lines)
        logger.debug("Kết thúc xây dựng section timeframe.")
        return result

    def create_images_tf_map(self, names: List[str]) -> Dict[str, str]:
        """
        Tạo một dictionary ánh xạ từ tên file ảnh sang khung thời gian tương ứng.

        Args:
            names: Danh sách các tên file ảnh.

        Returns:
            Một dictionary với key là tên file và value là khung thời gian.
        """
        logger.debug("Bắt đầu tạo map timeframe với %d tên file.", len(names))
        result = {name: self.detect_from_name(name) for name in names}
        logger.debug("Kết thúc tạo map timeframe. Map: %s", result)
        return result
