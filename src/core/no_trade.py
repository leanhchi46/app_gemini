from __future__ import annotations
from typing import TYPE_CHECKING, Tuple, List, Dict, Any

if TYPE_CHECKING:
    from src.config.config import RunConfig
    from src.utils.safe_data import SafeMT5Data

def evaluate(
    safe_mt5_data: SafeMT5Data,
    cfg: "RunConfig",
    cache_events: List[Dict[str, Any]],
    cache_fetch_time: float,
    ttl_sec: int
) -> Tuple[bool, List[str], List[Dict[str, Any]], float, int]:
    """
    Đánh giá các điều kiện NO-TRADE.
    Trả về (True, [], ...) nếu không có điều kiện NO-TRADE nào được kích hoạt,
    hoặc (False, ["Lý do"], ...) nếu có.
    """
    # TODO: Triển khai logic kiểm tra NO-TRADE thực tế tại đây
    # Ví dụ: Kiểm tra tin tức, spread, v.v.

    # Hiện tại, luôn cho phép giao dịch
    return True, [], cache_events, cache_fetch_time, ttl_sec
