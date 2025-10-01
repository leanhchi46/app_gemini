from __future__ import annotations
from typing import TYPE_CHECKING, Tuple

if TYPE_CHECKING:
    from scripts.tool import TradingToolApp

def check_no_run_conditions(app: "TradingToolApp") -> Tuple[bool, str]:
    """
    Kiểm tra các điều kiện NO-RUN.
    Trả về (True, "") nếu không có điều kiện NO-RUN nào được kích hoạt,
    hoặc (False, "Lý do") nếu có.
    """
    # TODO: Triển khai logic kiểm tra NO-RUN thực tế tại đây
    # Ví dụ: Kiểm tra thời gian, trạng thái thị trường, v.v.
    
    # Hiện tại, luôn cho phép chạy
    return True, ""
