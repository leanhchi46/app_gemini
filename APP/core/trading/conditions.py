from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import holidays

from APP.core.trading.no_trade_metrics import (
    NoTradeMetrics,
    collect_no_trade_metrics,
)
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


@dataclass(frozen=True)
class NoTradeViolation:
    """Kết quả một điều kiện No-Trade bị vi phạm."""

    condition_id: str
    message: str
    severity: str = "error"
    blocking: bool = True
    data: dict[str, Any] | None = None

    @property
    def icon(self) -> str:
        if self.blocking:
            return "⛔"
        if self.severity == "warning":
            return "⚠️"
        return "ℹ️"

    def to_display(self) -> str:
        return f"{self.icon} [{self.condition_id}] {self.message}"

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "condition_id": self.condition_id,
            "message": self.message,
            "severity": self.severity,
            "blocking": self.blocking,
        }
        if self.data is not None:
            payload["data"] = self.data
        return payload


@dataclass(frozen=True)
class NoTradeCheckResult:
    """Tổng hợp toàn bộ vi phạm/warning của lần kiểm tra No-Trade."""

    blocking: tuple[NoTradeViolation, ...] = ()
    warnings: tuple[NoTradeViolation, ...] = ()
    metrics: NoTradeMetrics | None = None

    def has_blockers(self) -> bool:
        return bool(self.blocking)

    def to_messages(self, include_warnings: bool = True) -> list[str]:
        messages = [violation.to_display() for violation in self.blocking]
        if include_warnings:
            messages.extend(warning.to_display() for warning in self.warnings)
        return messages

    def summary(self, include_warnings: bool = True) -> str:
        return ", ".join(self.to_messages(include_warnings=include_warnings))

    def to_dict(self, *, include_messages: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "blocking": [violation.to_dict() for violation in self.blocking],
            "warnings": [violation.to_dict() for violation in self.warnings],
        }
        if self.metrics is not None:
            payload["metrics"] = self.metrics.to_dict()
        if include_messages:
            payload["messages"] = self.to_messages(include_warnings=True)
            payload["status"] = (
                "blocked"
                if self.has_blockers()
                else ("warning" if self.warnings else "ok")
            )
        return payload


class AbstractCondition(ABC):
    """Lớp trừu tượng cho một điều kiện kiểm tra."""

    condition_id: str = "abstract"
    default_severity: str = "error"
    blocking: bool = True

    @abstractmethod
    def check(
        self, safe_mt5_data: Optional[SafeData], cfg: RunConfig, **kwargs: Any
    ) -> NoTradeViolation | None:
        """
        Kiểm tra điều kiện.
        Trả về NoTradeViolation nếu điều kiện bị vi phạm, ngược lại trả về None.
        """
        pass

    def violation(
        self,
        message: str,
        *,
        severity: Optional[str] = None,
        blocking: Optional[bool] = None,
        data: Optional[dict[str, Any]] = None,
    ) -> NoTradeViolation:
        """Helper tạo đối tượng NoTradeViolation với metadata chuẩn."""

        return NoTradeViolation(
            condition_id=self.condition_id,
            message=message,
            severity=severity or self.default_severity,
            blocking=self.blocking if blocking is None else blocking,
            data=data,
        )


class NewsCondition(AbstractCondition):
    """Kiểm tra các tin tức quan trọng bằng NewsService."""

    condition_id = "news_blackout"

    def check(
        self, safe_mt5_data: Optional[SafeData], cfg: RunConfig, **kwargs: Any
    ) -> NoTradeViolation | None:
        news_service: NewsService | None = kwargs.get("news_service")
        if not news_service:
            logger.error(
                "NewsService không được cung cấp cho NewsCondition. Bỏ qua kiểm tra."
            )
            return self.violation(
                "Lỗi cấu hình: NewsService không khả dụng.",
                severity="error",
                data={"service_available": False},
            )

        if cfg.news.block_enabled:
            is_in_blackout, reason = news_service.is_in_news_blackout(
                symbol=cfg.mt5.symbol
            )
            if is_in_blackout:
                return self.violation(
                    f"Tin tức quan trọng: {reason}",
                    data={"reason": reason},
                )
        return None


class SpreadCondition(AbstractCondition):
    """Kiểm tra spread hiện tại."""

    condition_id = "spread"

    def check(
        self, safe_mt5_data: Optional[SafeData], cfg: RunConfig, **kwargs: Any
    ) -> NoTradeViolation | None:
        if not safe_mt5_data:
            return self.violation(
                "Không có dữ liệu MT5 để kiểm tra spread.",
                data={"has_mt5_data": False},
            )

        if cfg.no_trade.spread_max_pips <= 0:
            return None

        metrics: NoTradeMetrics | None = kwargs.get("metrics")
        if metrics is None:
            metrics = collect_no_trade_metrics(safe_mt5_data, cfg)

        spread_metrics = metrics.spread if metrics else None
        if not spread_metrics or spread_metrics.current_pips is None:
            return self.violation(
                "Không xác định được spread hiện tại để so sánh với ngưỡng.",
                data={"has_spread": False},
            )

        current_spread = spread_metrics.current_pips
        threshold = cfg.no_trade.spread_max_pips
        if current_spread > threshold:
            recommended = None
            if spread_metrics.p90_5m_pips:
                recommended = spread_metrics.p90_5m_pips * 1.05
            return self.violation(
                (
                    f"Spread quá cao ({current_spread:.2f} pips > "
                    f"{threshold:.2f} pips)."
                ),
                data={
                    "current_spread_pips": current_spread,
                    "max_spread_pips": threshold,
                    "median_5m_pips": spread_metrics.median_5m_pips,
                    "p90_5m_pips": spread_metrics.p90_5m_pips,
                    "median_30m_pips": spread_metrics.median_30m_pips,
                    "p90_30m_pips": spread_metrics.p90_30m_pips,
                    "spread_as_pct_of_atr": spread_metrics.atr_pct,
                    "recommended_threshold_pips": recommended,
                },
            )

        if (
            spread_metrics.p90_5m_pips is not None
            and threshold > 0
            and spread_metrics.p90_5m_pips > threshold
        ):
            recommended = spread_metrics.p90_5m_pips * 1.05
            return self.violation(
                (
                    "Ngưỡng spread đang đặt thấp hơn P90 5 phút "
                    f"({threshold:.2f} < {spread_metrics.p90_5m_pips:.2f} pips)."
                ),
                severity="warning",
                blocking=False,
                data={
                    "current_spread_pips": current_spread,
                    "max_spread_pips": threshold,
                    "p90_5m_pips": spread_metrics.p90_5m_pips,
                    "p90_30m_pips": spread_metrics.p90_30m_pips,
                    "recommended_threshold_pips": recommended,
                },
            )

        return None


class ATRCondition(AbstractCondition):
    """Kiểm tra biến động thị trường qua ATR."""

    condition_id = "atr"

    def check(
        self, safe_mt5_data: Optional[SafeData], cfg: RunConfig, **kwargs: Any
    ) -> NoTradeViolation | None:
        if not safe_mt5_data:
            return self.violation(
                "Không có dữ liệu MT5 để kiểm tra ATR.",
                data={"has_mt5_data": False},
            )

        if cfg.no_trade.min_atr_m5_pips <= 0:
            return None

        metrics: NoTradeMetrics | None = kwargs.get("metrics")
        if metrics is None:
            metrics = collect_no_trade_metrics(safe_mt5_data, cfg)

        atr_metrics = metrics.atr if metrics else None
        if not atr_metrics or atr_metrics.atr_m5_pips is None:
            return self.violation(
                "Không có dữ liệu ATR M5 để kiểm tra biến động.",
                data={"has_atr_m5": False},
            )

        atr_current = atr_metrics.atr_m5_pips
        threshold = cfg.no_trade.min_atr_m5_pips
        if atr_current < threshold:
            return self.violation(
                (
                    f"Biến động quá thấp (ATR M5 {atr_current:.2f} pips < "
                    f"{threshold:.2f} pips)."
                ),
                data={
                    "atr_m5_pips": atr_current,
                    "min_atr_m5_pips": threshold,
                    "adr20_pips": atr_metrics.adr20_pips,
                    "atr_pct_of_adr20": atr_metrics.atr_pct_of_adr20,
                },
            )

        if (
            atr_metrics.adr20_pips is not None
            and threshold > atr_metrics.adr20_pips * 0.35
        ):
            recommended = atr_metrics.adr20_pips * 0.25
            return self.violation(
                (
                    "Ngưỡng ATR M5 quá cao so với ADR20 (" 
                    f"{threshold:.2f} pips > 35% của ADR20 {atr_metrics.adr20_pips:.2f} pips)."
                ),
                severity="warning",
                blocking=False,
                data={
                    "min_atr_m5_pips": threshold,
                    "adr20_pips": atr_metrics.adr20_pips,
                    "suggested_max_threshold_pips": recommended,
                },
            )

        return None


class SessionCondition(AbstractCondition):
    """Kiểm tra phiên giao dịch hiện tại."""

    condition_id = "session"

    def check(
        self, safe_mt5_data: Optional[SafeData], cfg: RunConfig, **kwargs: Any
    ) -> NoTradeViolation | None:
        if not safe_mt5_data:
            return None  # Không kiểm tra được phiên nếu thiếu dữ liệu MT5
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
        current_session_key = (
            session_map.get(killzone_active, None) if killzone_active else None
        )

        if not all(allowed_sessions.values()):
            if current_session_key:
                if not allowed_sessions.get(current_session_key, True):
                    return self.violation(
                        f"Không được phép giao dịch trong phiên {current_session_key}.",
                        data={"session": current_session_key},
                    )
            else:
                return self.violation(
                    "Không nằm trong phiên giao dịch được phép (ngoài killzone).",
                    data={"session": None},
                )
        return None


class KeyLevelCondition(AbstractCondition):
    """Kiểm tra khoảng cách đến các mức giá quan trọng."""

    condition_id = "key_level"

    def check(
        self, safe_mt5_data: Optional[SafeData], cfg: RunConfig, **kwargs: Any
    ) -> NoTradeViolation | None:
        if not safe_mt5_data:
            return self.violation(
                "Không có dữ liệu MT5 để kiểm tra key level.",
                data={"has_mt5_data": False},
            )

        if cfg.no_trade.min_dist_keylvl_pips <= 0:
            return None

        metrics: NoTradeMetrics | None = kwargs.get("metrics")
        if metrics is None:
            metrics = collect_no_trade_metrics(safe_mt5_data, cfg)

        key_metrics = metrics.key_levels if metrics else None
        if not key_metrics:
            return self.violation(
                "Không lấy được dữ liệu key level để kiểm tra an toàn.",
                data={"has_key_levels": False},
            )

        nearest = key_metrics.nearest
        if nearest and nearest.distance_pips is not None:
            if nearest.distance_pips < cfg.no_trade.min_dist_keylvl_pips:
                return self.violation(
                    (
                        f"Giá quá gần mức {nearest.name or '?'} "
                        f"({nearest.distance_pips:.2f} pips < "
                        f"{cfg.no_trade.min_dist_keylvl_pips:.2f} pips)."
                    ),
                    data={
                        "level": nearest.name,
                        "distance_pips": nearest.distance_pips,
                        "min_distance_pips": cfg.no_trade.min_dist_keylvl_pips,
                        "levels": [lvl.to_dict() for lvl in key_metrics.levels],
                    },
                )

        if not key_metrics.levels:
            return self.violation(
                "Không có mức giá quan trọng nào quanh thị trường hiện tại để đối chiếu.",
                severity="warning",
                blocking=False,
                data={"min_distance_pips": cfg.no_trade.min_dist_keylvl_pips},
            )

        return None


class UpcomingNewsWarningCondition(AbstractCondition):
    """Cảnh báo nếu sắp có tin tức lớn trong thời gian ngắn."""

    condition_id = "upcoming_news"
    default_severity = "warning"
    blocking = False

    def check(
        self, safe_mt5_data: Optional[SafeData], cfg: RunConfig, **kwargs: Any
    ) -> NoTradeViolation | None:
        news_service: NewsService | None = kwargs.get("news_service")
        if not news_service or not cfg.news.block_enabled:
            return None

        now = kwargs.get("now_utc")
        if now is None:
            now = datetime.now(timezone.utc)

        events = news_service.get_upcoming_events(cfg.mt5.symbol, now=now)
        if not events:
            return None

        warn_window_min = max(
            cfg.news.block_before_min + cfg.news.block_after_min,
            15,
        )

        for event in events:
            event_time = event.get("when_utc")
            if not event_time:
                continue
            minutes_until = (event_time - now).total_seconds() / 60
            if minutes_until < 0:
                continue
            if minutes_until <= warn_window_min and minutes_until > cfg.news.block_before_min:
                title = event.get("title", "Sự kiện kinh tế")
                country = event.get("country", "N/A")
                return self.violation(
                    (
                        f"Sắp có tin {country} ({title}) trong ~{minutes_until:.0f} phút."
                    ),
                    data={
                        "minutes_until": minutes_until,
                        "event": title,
                        "country": country,
                        "warn_window_min": warn_window_min,
                    },
                )
        return None


def check_no_trade_conditions(
    safe_mt5_data: Optional[SafeData],
    cfg: RunConfig,
    news_service: NewsService,
    *,
    now_utc: datetime | None = None,
) -> NoTradeCheckResult:
    """
    Đánh giá các điều kiện NO-TRADE bằng cách sử dụng Strategy Pattern.

    Args:
        safe_mt5_data: Dữ liệu an toàn từ MT5.
        cfg: Đối tượng cấu hình RunConfig.
        news_service: Instance của dịch vụ tin tức.

    Returns:
        Danh sách các lý do vi phạm. Rỗng nếu không có vi phạm nào.
    """
    metrics = (
        collect_no_trade_metrics(safe_mt5_data, cfg)
        if safe_mt5_data is not None
        else None
    )

    if not cfg.no_trade.enabled:
        return NoTradeCheckResult(metrics=metrics)

    logger.debug("Bắt đầu kiểm tra các điều kiện NO-TRADE.")

    conditions: list[AbstractCondition] = [
        NewsCondition(),
        SpreadCondition(),
        ATRCondition(),
        SessionCondition(),
        KeyLevelCondition(),
        UpcomingNewsWarningCondition(),
    ]

    # Truyền news_service vào kwargs để các điều kiện con có thể sử dụng
    kwargs = {
        "news_service": news_service,
        "now_utc": now_utc,
        "metrics": metrics,
    }

    blocking: list[NoTradeViolation] = []
    warnings: list[NoTradeViolation] = []
    for condition in conditions:
        violation = condition.check(safe_mt5_data, cfg, **kwargs)
        if violation:
            if violation.blocking:
                blocking.append(violation)
            else:
                warnings.append(violation)

    result = NoTradeCheckResult(tuple(blocking), tuple(warnings), metrics)

    if blocking or warnings:
        logger.info(
            "Điều kiện NO-TRADE được kích hoạt: %s",
            result.summary(include_warnings=True),
        )

    return result


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
