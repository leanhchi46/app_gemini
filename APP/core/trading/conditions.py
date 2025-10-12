from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import holidays

from APP.services import mt5_service, telegram_service
from APP.services.news_service import NewsService
from APP.utils.safe_data import SafeData

if TYPE_CHECKING:
    from APP.configs.app_config import RunConfig
    from APP.core.analysis_worker import AnalysisWorker


logger = logging.getLogger(__name__)


# =============================================================================
# SECTION: NO-RUN CONDITIONS
# =============================================================================


def check_no_run_conditions(
    cfg: RunConfig, news_service: NewsService
) -> tuple[bool, str]:
    """Kiểm tra các điều kiện NO-RUN cấp cao nhất.

    Args:
        cfg: Đối tượng cấu hình RunConfig.
        news_service: Instance của dịch vụ tin tức.

    Returns:
        Tuple (bool, str): (True, "Lý do chạy") hoặc (False, "Lý do dừng").
    """
    logger.debug("Bắt đầu kiểm tra các điều kiện NO-RUN.")
    tz_name = cfg.no_run.timezone or mt5_service.DEFAULT_TIMEZONE
    try:
        tz = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        logger.warning(
            "Không thể tải timezone '%s'. Sử dụng múi giờ mặc định %s.",
            tz_name,
            mt5_service.DEFAULT_TIMEZONE,
        )
        tz = ZoneInfo(mt5_service.DEFAULT_TIMEZONE)
        tz_name = mt5_service.DEFAULT_TIMEZONE

    now = datetime.now(tz)
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
    killzone_overrides = {
        "summer": cfg.no_run.killzone_summer,
        "winter": cfg.no_run.killzone_winter,
    }
    if cfg.no_run.killzone_enabled:
        is_in_kill_zone, zone_name = mt5_service.get_active_killzone(
            d=now, target_tz=tz_name, killzone_overrides=killzone_overrides
        )
        if not is_in_kill_zone:
            reasons.append("Không chạy ngoài các Kill Zone đã định nghĩa.")
        elif zone_name:
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
        self, safe_mt5_data: Optional[SafeData], cfg: RunConfig, **kwargs: Any
    ) -> str | None:
        """
        Kiểm tra điều kiện.
        Trả về một chuỗi lý do nếu điều kiện bị vi phạm, ngược lại trả về None.
        """
        pass


class NewsCondition(AbstractCondition):
    """Kiểm tra các tin tức quan trọng bằng NewsService."""

    def check(
        self, safe_mt5_data: Optional[SafeData], cfg: RunConfig, **kwargs: Any
    ) -> str | None:
        news_service: NewsService | None = kwargs.get("news_service")
        if not news_service:
            # Đây là một lỗi logic nếu news_service không được truyền vào
            logger.error("NewsService không được cung cấp cho NewsCondition. Bỏ qua kiểm tra.")
            return "Lỗi cấu hình: NewsService không khả dụng."

        if cfg.news.block_enabled:
            is_in_blackout, reason = news_service.is_in_news_blackout(
                symbol=cfg.mt5.symbol
            )
            if is_in_blackout:
                return f"Tin tức quan trọng: {reason}"
        return None


class SpreadCondition(AbstractCondition):
    """Kiểm tra spread hiện tại."""

    def check(
        self, safe_mt5_data: Optional[SafeData], cfg: RunConfig, **kwargs: Any
    ) -> str | None:
        if not safe_mt5_data:
            return "Không có dữ liệu MT5 để kiểm tra spread."
        if cfg.no_trade.spread_max_pips > 0:
            symbol_info = safe_mt5_data.get("info")
            tick_info = safe_mt5_data.get("tick")
            if symbol_info and tick_info:
                current_spread_pips = mt5_service.get_spread_pips(symbol_info, tick_info)
                if current_spread_pips is not None and current_spread_pips > cfg.no_trade.spread_max_pips:
                    return (
                        f"Spread quá cao ({current_spread_pips:.2f} pips > "
                        f"{cfg.no_trade.spread_max_pips:.2f} pips)."
                    )
        return None


class ATRCondition(AbstractCondition):
    """Kiểm tra biến động thị trường qua ATR."""

    def check(
        self, safe_mt5_data: Optional[SafeData], cfg: RunConfig, **kwargs: Any
    ) -> str | None:
        if not safe_mt5_data:
            return "Không có dữ liệu MT5 để kiểm tra ATR."
        if cfg.no_trade.min_atr_m5_pips > 0:
            atr_m5 = safe_mt5_data.get_nested("volatility.ATR.M5")
            if atr_m5 is not None:
                symbol_info = safe_mt5_data.get("info")
                if not symbol_info:
                    return "Không có thông tin symbol để kiểm tra ATR."
                atr_m5_pips = mt5_service.points_to_pips(atr_m5, symbol_info)
                if atr_m5_pips is not None and atr_m5_pips < cfg.no_trade.min_atr_m5_pips:
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
        self, safe_mt5_data: Optional[SafeData], cfg: RunConfig, **kwargs: Any
    ) -> str | None:
        if not safe_mt5_data:
            return None # Cannot check session without MT5 data
        allowed_sessions = {
            "asia": cfg.no_trade.allow_session_asia,
            "london": cfg.no_trade.allow_session_london,
            "ny": cfg.no_trade.allow_session_ny,
        }
        killzone_active = safe_mt5_data.get("killzone_active")
        
        session_map = {
            "asia": "asia",
            "london": "london",
            "newyork_am": "ny",
            "newyork_pm": "ny",
        }
        current_session_key = session_map.get(killzone_active, None) if killzone_active else None

        if not all(allowed_sessions.values()):
            if current_session_key:
                if not allowed_sessions.get(current_session_key, True):
                    return f"Không được phép giao dịch trong phiên {current_session_key}."
            else:
                return "Không nằm trong phiên giao dịch được phép (ngoài killzone)."
        return None


class KeyLevelCondition(AbstractCondition):
    """Kiểm tra khoảng cách đến các mức giá quan trọng."""

    def check(
        self, safe_mt5_data: Optional[SafeData], cfg: RunConfig, **kwargs: Any
    ) -> str | None:
        if not safe_mt5_data:
            return "Không có dữ liệu MT5 để kiểm tra key level."
        if cfg.no_trade.min_dist_keylvl_pips > 0:
            current_price = safe_mt5_data.get_tick_value("bid") or safe_mt5_data.get_tick_value("last") or 0.0
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
    safe_mt5_data: Optional[SafeData], cfg: RunConfig, news_service: NewsService
) -> list[str]:
    """
    Đánh giá các điều kiện NO-TRADE bằng cách sử dụng Strategy Pattern.

    Args:
        safe_mt5_data: Dữ liệu an toàn từ MT5.
        cfg: Đối tượng cấu hình RunConfig.
        news_service: Instance của dịch vụ tin tức.

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

    # Truyền news_service vào kwargs để các điều kiện con có thể sử dụng
    kwargs = {"news_service": news_service}

    reasons: list[str] = []
    for condition in conditions:
        reason = condition.check(safe_mt5_data, cfg, **kwargs)
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

    logger.info(f"Thoát sớm. Giai đoạn: {stage}, Lý do: {reason}")

    report_text = f"Dừng sớm: {reason}."
    worker.combined_text = report_text

    worker.app.ui_queue.put(lambda: worker.app.ui_status(f"Dừng: {reason.splitlines()[0]}"))
    worker.app.ui_queue.put(lambda: worker.app.ui_detail_replace(report_text))
    if worker.context_block:
        worker.combined_text += f"\n\n--- NGỮ CẢNH ---\n{worker.context_block}"

    log_handler.log_trade(
        run_config=worker.cfg,
        trade_data={"stage": stage, "reason": reason},
    )

    if notify and worker.cfg.telegram.enabled:
        try:
            client = telegram_service.TelegramClient.from_config(worker.cfg)
            client.send_message(f"*[EARLY EXIT]*\n- Stage: {stage}\n- Reason: {reason}")
        except Exception:
            logger.exception("Lỗi khi gửi thông báo Telegram về việc thoát sớm.")
