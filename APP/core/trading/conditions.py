from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import TYPE_CHECKING, Any

import holidays

from APP.services import mt5_service, news_service, telegram_service
from APP.ui.utils import ui_builder

if TYPE_CHECKING:
    from APP.configs.app_config import RunConfig
    from APP.core.analysis_worker import AnalysisWorker
from APP.utils.safe_data import SafeData


logger = logging.getLogger(__name__)


# =============================================================================
# SECTION: NO-RUN CONDITIONS
# =============================================================================


def check_no_run_conditions(cfg: RunConfig) -> tuple[bool, str]:
    """Kiểm tra các điều kiện NO-RUN cấp cao nhất.

    Args:
        cfg: Đối tượng cấu hình RunConfig.

    Returns:
        Tuple (bool, str): (True, "Lý do chạy") hoặc (False, "Lý do dừng").
    """
    logger.debug("Bắt đầu kiểm tra các điều kiện NO-RUN.")
    now = datetime.now()
    reasons: list[str] = []

    # 1. Kiểm tra cuối tuần
    if cfg.no_run.weekend_enabled and now.weekday() >= 5:
        reasons.append("Không chạy vào cuối tuần.")

    # 2. Kiểm tra ngày lễ
    if cfg.no_run.holiday_check_enabled:
        country_holidays = holidays.country_holidays(cfg.no_run.holiday_check_country)
        if now in country_holidays:
            reasons.append(
                f"Không chạy vào ngày lễ của {cfg.no_run.holiday_check_country}: "
                f"{country_holidays.get(now)}"
            )

    # 3. Kiểm tra Kill Zone
    active_kill_zone = ""
    if cfg.no_run.killzone_enabled:
        is_in_kill_zone, zone_name = mt5_service.is_in_killzone(
            d=now, target_tz=cfg.no_run.timezone
        )
        if not is_in_kill_zone:
            reasons.append("Không chạy ngoài các Kill Zone đã định nghĩa.")
        else:
            active_kill_zone = zone_name

    if reasons:
        reason_str = "\n- ".join(reasons)
        logger.info(f"Điều kiện NO-RUN được kích hoạt: {reason_str}")
        return False, reason_str

    run_reason = (
        f"Đang chạy trong {active_kill_zone}."
        if active_kill_zone
        else "Các điều kiện cho phép."
    )
    logger.debug(f"Điều kiện NO-RUN được thỏa mãn. Lý do: {run_reason}")
    return True, run_reason


# =============================================================================
# SECTION: NO-TRADE CONDITIONS (STRATEGY PATTERN)
# =============================================================================


class AbstractCondition(ABC):
    """Lớp trừu tượng cho một điều kiện kiểm tra."""

    @abstractmethod
    def check(
        self, safe_mt5_data: SafeData, cfg: RunConfig, **kwargs: Any
    ) -> str | None:
        """
        Kiểm tra điều kiện.
        Trả về một chuỗi lý do nếu điều kiện bị vi phạm, ngược lại trả về None.
        """
        pass


class NewsCondition(AbstractCondition):
    """Kiểm tra các tin tức quan trọng."""

    def check(
        self, safe_mt5_data: SafeData, cfg: RunConfig, **kwargs: Any
    ) -> str | None:
        news_events = kwargs.get("news_events")
        if cfg.news.block_enabled and news_events:
            is_in_window, news_reason = news_service.is_within_news_window(
                events=news_events,
                symbol=cfg.mt5.symbol,
                minutes_before=cfg.news.block_before_min,
                minutes_after=cfg.news.block_after_min,
            )
            if is_in_window:
                return f"Tin tức quan trọng: {news_reason}"
        return None


class SpreadCondition(AbstractCondition):
    """Kiểm tra spread hiện tại."""

    def check(
        self, safe_mt5_data: SafeData, cfg: RunConfig, **kwargs: Any
    ) -> str | None:
        if cfg.no_trade.spread_max_pips > 0:
            symbol_info = safe_mt5_data.get("info", {})
            current_spread_pips = mt5_service.get_spread_pips(symbol_info)
            if current_spread_pips > cfg.no_trade.spread_max_pips:
                return (
                    f"Spread quá cao ({current_spread_pips:.2f} pips > "
                    f"{cfg.no_trade.spread_max_pips:.2f} pips)."
                )
        return None


class ATRCondition(AbstractCondition):
    """Kiểm tra biến động thị trường qua ATR."""

    def check(
        self, safe_mt5_data: SafeData, cfg: RunConfig, **kwargs: Any
    ) -> str | None:
        if cfg.no_trade.min_atr_m5_pips > 0:
            atr_m5 = safe_mt5_data.get_nested("volatility.ATR.M5")
            if atr_m5 is not None:
                symbol_info = safe_mt5_data.get("info", {})
                atr_m5_pips = mt5_service.points_to_pips(atr_m5, symbol_info)
                if atr_m5_pips < cfg.no_trade.min_atr_m5_pips:
                    return (
                        f"Biến động quá thấp (ATR M5 {atr_m5_pips:.2f} pips < "
                        f"{cfg.no_trade.min_atr_m5_pips:.2f} pips)."
                    )
            else:
                return "Không có dữ liệu ATR M5 để kiểm tra biến động."
        return None


class SessionCondition(AbstractCondition):
    """Kiểm tra phiên giao dịch hiện tại."""

    def check(
        self, safe_mt5_data: SafeData, cfg: RunConfig, **kwargs: Any
    ) -> str | None:
        allowed_sessions = {
            "asia": cfg.no_trade.allow_session_asia,
            "london": cfg.no_trade.allow_session_london,
            "ny": cfg.no_trade.allow_session_ny,
        }
        # Chỉ kiểm tra nếu có ít nhất 1 phiên bị tắt
        if not all(allowed_sessions.values()):
            if not mt5_service.is_in_allowed_session(allowed_sessions):
                return "Không nằm trong phiên giao dịch được phép."
        return None


class KeyLevelCondition(AbstractCondition):
    """Kiểm tra khoảng cách đến các mức giá quan trọng."""

    def check(
        self, safe_mt5_data: SafeData, cfg: RunConfig, **kwargs: Any
    ) -> str | None:
        if cfg.no_trade.min_dist_keylvl_pips > 0:
            current_price = safe_mt5_data.get_nested("tick.bid") or safe_mt5_data.get_nested("tick.last") or 0.0
            if current_price > 0:
                key_levels_nearby = safe_mt5_data.get("key_levels_nearby", [])
                for level in key_levels_nearby:
                    dist_pips = level.get("distance_pips")
                    if dist_pips is not None and dist_pips < cfg.no_trade.min_dist_keylvl_pips:
                        return (
                            f"Giá quá gần mức key level {level.get('name')} "
                            f"({dist_pips:.2f} pips < {cfg.no_trade.min_dist_keylvl_pips:.2f} pips)."
                        )
        return None


def check_no_trade_conditions(
    safe_mt5_data: SafeData,
    cfg: RunConfig,
    news_events: list[dict[str, Any]] | None,
) -> list[str]:
    """
    Đánh giá các điều kiện NO-TRADE bằng cách sử dụng Strategy Pattern.

    Args:
        safe_mt5_data: Dữ liệu an toàn từ MT5.
        cfg: Đối tượng cấu hình RunConfig.
        news_events: Danh sách các sự kiện tin tức đã được cache.

    Returns:
        Danh sách các lý do vi phạm. Rỗng nếu không có vi phạm nào.
    """
    if not cfg.no_trade.enabled:
        return []

    logger.debug("Bắt đầu kiểm tra các điều kiện NO-TRADE.")
    
    conditions: list[AbstractCondition] = [
        NewsCondition(),
        SpreadCondition(),
        ATRCondition(),
        SessionCondition(),
        KeyLevelCondition(),
    ]
    
    reasons: list[str] = []
    for condition in conditions:
        reason = condition.check(
            safe_mt5_data, cfg, news_events=news_events
        )
        if reason:
            reasons.append(reason)

    if reasons:
        logger.info(f"Điều kiện NO-TRADE được kích hoạt: {', '.join(reasons)}")

    return reasons


# =============================================================================
# SECTION: EARLY EXIT HANDLER
# =============================================================================


def handle_early_exit(
    worker: AnalysisWorker, stage: str, reason: str, notify: bool = False
) -> None:
    """
    Xử lý các trường hợp cần thoát sớm khỏi quy trình phân tích.
    Hàm này chỉ cập nhật trạng thái, ghi log và thông báo. Việc dọn dẹp
    và lưu trữ báo cáo cuối cùng sẽ được thực hiện trong khối `finally`
    của worker.
    """
    from APP.persistence import log_handler
    from APP.services import telegram_service

    logger.info(f"Thoát sớm. Giai đoạn: {stage}, Lý do: {reason}")
    worker.app.ui_status(f"Dừng: {reason}")

    # Đặt văn bản báo cáo cuối cùng để khối finally có thể lưu lại
    worker.combined_text = f"Dừng sớm: {reason}."
    if worker.context_block:
        worker.combined_text += f"\n\n--- NGỮ CẢNH ---\n{worker.context_block}"

    # Ghi log quyết định
    log_handler.log_trade(
        run_config=worker.cfg,
        trade_data={"stage": stage, "reason": reason},
    )

    # Gửi thông báo nếu được yêu cầu
    if notify and worker.cfg.telegram.enabled:
        telegram_service.send_telegram_message(
            message=f"*[EARLY EXIT]*\n- Stage: {stage}\n- Reason: {reason}",
            cfg=worker.cfg.telegram,
        )
