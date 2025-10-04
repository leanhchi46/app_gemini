from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING

from zoneinfo import ZoneInfo

from APP.services import mt5_service, news_service
from APP.ui.utils import ui_builder

if TYPE_CHECKING:
    from APP.configs.app_config import RunConfig
    from APP.ui.app_ui import AppUI
    from APP.utils.safe_data import SafeMT5Data

logger = logging.getLogger(__name__)


def handle_early_exit(app: AppUI, reason: str):
    """
    Xử lý các trường hợp thoát sớm bằng cách cập nhật UI và ghi log.
    """
    logger.info(f"Thoát sớm khỏi worker: {reason}")
    app.ui_status(reason)
    # Các hành động khác như lưu báo cáo nhanh có thể được xử lý trong analysis_worker
    # trước khi gọi hàm này.


def check_no_run_conditions(cfg: RunConfig) -> tuple[bool, str]:
    """
    Kiểm tra các điều kiện không cho phép chạy phân tích (ví dụ: cuối tuần).
    """
    logger.debug("Kiểm tra điều kiện NO-RUN.")
    now = datetime.now()
    reasons = []

    if cfg.no_run_weekend_enabled and now.weekday() >= 5:
        reasons.append("Không chạy vào cuối tuần.")

    if cfg.no_run_killzone_enabled:
        kill_zones = mt5_service.get_killzone_ranges(d=now)
        now_hhmm = now.strftime("%H:%M")
        is_in_kill_zone = any(
            (start <= now_hhmm < end)
            if start <= end
            else (now_hhmm >= start or now_hhmm < end)
            for start, end in (
                (z["start"], z["end"]) for z in kill_zones.values()
            )
        )
        if not is_in_kill_zone:
            reasons.append("Không chạy ngoài các Kill Zone đã định nghĩa.")

    if reasons:
        return False, "\n- ".join(reasons)

    return True, "Các điều kiện NO-RUN được thỏa mãn."


def check_no_trade_conditions(
    cfg: RunConfig, safe_mt5_data: SafeMT5Data, news_events: list[dict]
) -> tuple[bool, str]:
    """
    Kiểm tra các điều kiện không cho phép giao dịch (ví dụ: tin tức, spread cao).
    """
    logger.debug("Kiểm tra điều kiện NO-TRADE.")
    if not cfg.nt_enabled or not safe_mt5_data or not safe_mt5_data.raw:
        return True, ""

    reasons = []
    mt5_raw = safe_mt5_data.raw
    symbol_info = mt5_raw.get("info", {})

    # 1. Kiểm tra tin tức
    if cfg.trade_news_block_enabled:
        is_in_window, news_reason = news_service.is_within_news_window(
            events=news_events,
            symbol=cfg.mt5_symbol,
            minutes_before=cfg.trade_news_block_before_min,
            minutes_after=cfg.trade_news_block_after_min,
        )
        if is_in_window:
            reasons.append(f"Tin tức quan trọng: {news_reason}")

    # 2. Kiểm tra Spread
    if cfg.nt_spread_factor > 0 and symbol_info:
        spread_pips = mt5_service.get_spread_pips(symbol_info)
        if spread_pips > cfg.nt_spread_factor:
            reasons.append(f"Spread quá cao ({spread_pips:.2f} > {cfg.nt_spread_factor:.2f} pips).")

    # 3. Kiểm tra Biến động (ATR)
    if cfg.nt_min_atr_m5_pips > 0 and symbol_info:
        atr_pips = mt5_service.get_atr_pips(mt5_raw, "M5", symbol_info)
        if atr_pips is not None and atr_pips < cfg.nt_min_atr_m5_pips:
            reasons.append(f"Biến động quá thấp (ATR M5 {atr_pips:.2f} < {cfg.nt_min_atr_m5_pips:.2f} pips).")

    # 4. Kiểm tra Phiên giao dịch
    allowed_sessions = {
        "asia": cfg.trade_allow_session_asia,
        "london": cfg.trade_allow_session_london,
        "ny": cfg.trade_allow_session_ny,
    }
    if any(allowed_sessions.values()) and not mt5_service.is_in_allowed_session(allowed_sessions):
        reasons.append("Không nằm trong phiên giao dịch được phép.")

    if reasons:
        return False, "\n- ".join(reasons)

    return True, "Các điều kiện NO-TRADE được thỏa mãn."
