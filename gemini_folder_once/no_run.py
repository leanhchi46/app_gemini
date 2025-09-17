from __future__ import annotations
import datetime
from zoneinfo import ZoneInfo
from typing import TYPE_CHECKING

# Import the killzone logic from mt5_utils
from . import mt5_utils

if TYPE_CHECKING:
    # This avoids circular import issues with type hinting
    from ..gemini_batch_image_analyzer import GeminiFolderOnceApp

def check_no_run_conditions(app: "GeminiFolderOnceApp") -> tuple[bool, str | None]:
    """
    Kiểm tra xem có nên bỏ qua phân tích dựa trên cài đặt trong UI hay không.

    Trả về: (should_run, reason_if_not).
    """
    # Luôn sử dụng múi giờ Việt Nam để đảm bảo tính nhất quán
    now = datetime.datetime.now(ZoneInfo("Asia/Ho_Chi_Minh"))

    # 1. Kiểm tra điều kiện chặn cuối tuần
    if app.norun_weekend_var.get():
        # Monday is 0, Sunday is 6
        if now.weekday() >= 5:  # Thứ 7 hoặc Chủ Nhật
            return False, "Bỏ qua vì đang là cuối tuần"

    # 2. Kiểm tra điều kiện chỉ chạy trong Kill Zone
    if app.norun_killzone_var.get():
        kills = mt5_utils._killzone_ranges_vn(d=now)
        now_hhmm = now.strftime("%H:%M")
        is_in_killzone = False

        # Lặp qua tất cả các kill zone đã định nghĩa
        for session in ["asia", "london", "newyork_am", "newyork_pm"]:
            kz = kills.get(session)
            if kz and kz.get("start") and kz.get("end"):
                # Xử lý trường hợp kill zone qua nửa đêm (ví dụ: 00:00 - 03:00)
                if kz["start"] > kz["end"]:
                    if now_hhmm >= kz["start"] or now_hhmm < kz["end"]:
                        is_in_killzone = True
                        break
                else:
                    if kz["start"] <= now_hhmm < kz["end"]:
                        is_in_killzone = True
                        break
        
        if not is_in_killzone:
            return False, "Bỏ qua vì ngoài giờ Kill Zone"

    # Nếu tất cả các điều kiện đều được thỏa mãn
    return True, None
