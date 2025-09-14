"""
Các hàm tiện ích khác (miscellaneous)
"""

import re
import math

def parse_float(s: str):
    if s is None:
        return None
    s = s.replace(",", "").strip()
    s = re.sub(r"^\s*\d+\s*[\.\)\-–:]\s*", "", s)
    nums = re.findall(r"[-+]?\d+(?:\.\d+)?", s)
    return float(nums[-1]) if nums else None

def parse_direction_from_line1(line1: str):
    if not line1:
        return None
    s = line1.lower()
    if "mua" in s or "long" in s:
        return "long"
    if "bán" in s or "short" in s:
        return "short"
    return None