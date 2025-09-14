"""
Lấy dữ liệu từ MetaTrader5, snapshot, tính toán chỉ số
"""

from datetime import datetime, timedelta, timezone
import hashlib

def session_ranges(m1_rates, tz_shift_hours=None, source_tz="UTC", target_tz="Asia/Ho_Chi_Minh", day=None):
    # ...hàm _session_ranges từ file gốc...
    pass

def killzones_vn_for_date(day=None, target_tz="Asia/Ho_Chi_Minh"):
    # ...hàm _killzones_vn_for_date từ file gốc...
    pass

def value_per_point_safe(symbol: str, info_obj=None, mt5_lib=None) -> float | None:
    # ...hàm _value_per_point_safe từ file gốc...
    pass