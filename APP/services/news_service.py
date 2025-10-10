from __future__ import annotations

import logging
import re
from concurrent.futures import CancelledError, TimeoutError
from datetime import datetime, timedelta
from threading import Lock
from time import monotonic
from typing import Any, Callable, Final, List, Optional

import pytz

from APP.configs.app_config import FMPConfig, NewsConfig, RunConfig, TEConfig
from APP.services.fmp_service import FMPService
from APP.services.te_service import TEService
from APP.utils.threading_utils import CancelToken, ThreadingManager

logger = logging.getLogger(__name__)

# Ánh xạ tiền tệ và quốc gia/khu vực
CURRENCY_COUNTRY_MAP: Final[dict[str, set[str]]] = {
    "USD": {"United States", "US", "U.S.", "united states"},
    "EUR": {"Euro Area", "Eurozone", "Germany", "France", "Italy", "Spain", "EU"},
    "GBP": {"United Kingdom", "UK", "U.K."},
    "JPY": {"Japan", "JP"},
    "CAD": {"Canada", "CA"},
    "AUD": {"Australia", "AU"},
    "NZD": {"New Zealand", "NZ"},
    "CHF": {"Switzerland", "CH"},
    "CNY": {"China", "CN"},
}

# Các sự kiện kinh tế quan trọng (từ khóa tìm kiếm trong tiêu đề)
HIGH_IMPACT_KEYWORDS: Final[set[str]] = {
    "interest rate", "cpi", "consumer price index", "nfp", "non-farm payroll",
    "pmi", "purchasing managers", "retail sales", "gdp", "gross domestic product",
    "unemployment rate", "inflation rate", "trade balance", "industrial production",
    "business confidence", "consumer confidence", "ism", "ifo", "zew"
}


class NewsService:
    """
    Dịch vụ chạy nền, tự động lấy và làm mới tin tức kinh tế định kỳ.
    """

    def __init__(self):
        """Khởi tạo dịch vụ ở trạng thái chưa hoạt động."""
        self.news_config: Optional[NewsConfig] = None
        self.fmp_config: Optional[FMPConfig] = None
        self.te_config: Optional[TEConfig] = None
        self.timezone_str: str = "Asia/Ho_Chi_Minh"
        
        self.fmp_service: Optional[FMPService] = None
        self.te_service: Optional[TEService] = None

        self._cache: list[dict[str, Any]] = []
        self._cache_time: Optional[datetime] = None
        self._dedup_ids: set[str] = set()
        
        # Threading attributes
        self._lock = Lock()
        self._update_callback: Optional[Callable[[List[dict[str, Any]]], None]] = None
        self._last_refresh: Optional[datetime] = None
        self._last_latency_sec: float = 0.0

    def update_config(self, config: RunConfig):
        """Cập nhật cấu hình cho dịch vụ một cách an toàn."""
        with self._lock:
            self.news_config = config.news
            self.fmp_config = config.fmp
            self.te_config = config.te
            self.timezone_str = config.no_run.timezone
            
            # Khởi tạo lại các service con nếu cần
            self.fmp_service = FMPService(config.fmp) if config.fmp and config.fmp.enabled else None
            self.te_service = TEService(config.te) if config.te and config.te.enabled else None
            logger.debug("Cấu hình NewsService đã được cập nhật.")

    def set_update_callback(self, callback: Callable[[List[dict[str, Any]]], None]):
        """Đăng ký một hàm callback để được gọi sau mỗi lần cache được cập nhật."""
        self._update_callback = callback

    # Các phương thức dưới đây giữ lại để tương thích với code cũ.

    def start(self):  # pragma: no cover - chỉ tồn tại cho tương thích
        logger.warning("NewsService.start() không còn tạo luồng nền. Hãy dùng NewsController.start_polling().")

    def stop(self):  # pragma: no cover - chỉ tồn tại cho tương thích
        logger.warning("NewsService.stop() không còn tác dụng trong kiến trúc mới.")

    def get_cache_ttl(self) -> int:
        """Trả về TTL hiện tại của cache tin tức (giây)."""

        with self._lock:
            return self.news_config.cache_ttl_sec if self.news_config else 300

    def get_timeout_sec(self) -> int:
        """Trả về timeout mặc định cho từng provider."""

        with self._lock:
            if self.news_config and hasattr(self.news_config, "provider_timeout_sec"):
                return getattr(self.news_config, "provider_timeout_sec")
        return 20

    def is_in_news_blackout(
        self, symbol: str, now: Optional[datetime] = None
    ) -> tuple[bool, str | None]:
        """
        Kiểm tra xem có đang trong thời gian "cấm giao dịch" vì tin tức hay không.
        Đọc trực tiếp từ cache.
        """
        with self._lock:
            if not self.news_config or not self.news_config.block_enabled:
                return False, None

        now_utc = (now or datetime.now(pytz.utc)).astimezone(pytz.utc)
        # Lấy danh sách sự kiện đã được lọc và sắp xếp sẵn từ cache
        upcoming_events = self.get_upcoming_events(symbol, now_utc)

        for event in upcoming_events:
            event_time_utc = event["when_utc"]
            start_blackout = event_time_utc - timedelta(minutes=self.news_config.block_before_min)
            end_blackout = event_time_utc + timedelta(minutes=self.news_config.block_after_min)

            if start_blackout <= now_utc <= end_blackout:
                reason = (
                    f"{event['title']} ({event.get('country', 'N/A')}) @ "
                    f"{event['when_local'].strftime('%H:%M')}"
                )
                logger.warning("NO-TRADE: Đang trong thời gian cấm vì tin: %s", reason)
                return True, reason
        return False, None

    def get_upcoming_events(
        self, symbol: str, now: Optional[datetime] = None
    ) -> list[dict[str, Any]]:
        """
        Lấy danh sách các sự kiện kinh tế quan trọng sắp tới cho một symbol từ cache.
        """
        now_utc = (now or datetime.now(pytz.utc)).astimezone(pytz.utc)
        
        with self._lock:
            # Sao chép cache để tránh thay đổi dữ liệu gốc khi thêm 'when_local'
            cached_events = list(self._cache)
            local_timezone_str = self.timezone_str

        allowed_countries = self._get_countries_for_symbol(symbol)
        ho_chi_minh_tz = pytz.timezone(local_timezone_str)

        upcoming_events = []
        for event in cached_events:
            event_time_utc = event.get("when_utc")
            if not event_time_utc or event_time_utc < now_utc:
                continue

            event_country = event.get("country")
            if not event_country or event_country not in allowed_countries:
                continue
            
            # Tạo một bản sao của event để thêm các trường tính toán
            processed_event = event.copy()
            processed_event["when_local"] = event_time_utc.astimezone(ho_chi_minh_tz)
            time_diff = event_time_utc - now_utc
            processed_event["time_remaining"] = self._format_timedelta(time_diff)
            upcoming_events.append(processed_event)

        return sorted(upcoming_events, key=lambda x: x["when_utc"])

    def get_all_upcoming_events(self, now: Optional[datetime] = None, limit: Optional[int] = None) -> list[dict[str, Any]]:
        """Lấy toàn bộ sự kiện sắp tới từ cache (không lọc theo symbol)."""
        now_utc = (now or datetime.now(pytz.utc)).astimezone(pytz.utc)

        with self._lock:
            cached_events = list(self._cache)
            local_timezone_str = self.timezone_str

        ho_chi_minh_tz = pytz.timezone(local_timezone_str)
        upcoming_events: list[dict[str, Any]] = []
        for event in cached_events:
            event_time_utc = event.get("when_utc")
            if not event_time_utc or event_time_utc < now_utc:
                continue

            processed_event = event.copy()
            processed_event["when_local"] = event_time_utc.astimezone(ho_chi_minh_tz)
            processed_event["time_remaining"] = self._format_timedelta(event_time_utc - now_utc)
            upcoming_events.append(processed_event)

        upcoming_events.sort(key=lambda x: x["when_utc"])
        if limit is not None:
            return upcoming_events[:limit]
        return upcoming_events

    def get_news_analysis(self, symbol: str) -> dict[str, Any]:
        """
        Lấy phân tích tin tức tức thì từ cache.
        """
        try:
            now_utc = datetime.now(pytz.utc)
            is_in_blackout, reason = self.is_in_news_blackout(symbol=symbol, now=now_utc)
            upcoming_events = self.get_upcoming_events(symbol=symbol, now=now_utc)
            with self._lock:
                last_refresh = self._last_refresh
                latency = self._last_latency_sec

            return {
                "is_in_news_window": is_in_blackout,
                "reason": reason,
                "upcoming_events": upcoming_events[:3],  # Chỉ lấy 3 sự kiện gần nhất
                "last_refresh_utc": last_refresh,
                "latency_sec": latency,
            }
        except Exception as e:
            logger.error(f"Lỗi khi phân tích tin tức từ cache cho '{symbol}': {e}", exc_info=True)
            return {"error": "failed to analyze news from cache"}

    def refresh(
        self,
        *,
        threading_manager: ThreadingManager,
        cancel_token: CancelToken,
        priority: str,
        timeout_sec: int,
        force: bool = False,
    ) -> dict[str, Any]:
        """Làm mới cache tin tức thông qua ThreadingManager."""

        start_time = monotonic()
        now_utc = datetime.now(pytz.utc)

        with self._lock:
            ttl = self.news_config.cache_ttl_sec if self.news_config else 300
            last_time = self._cache_time
            cache_copy = list(self._cache)

        cache_age = (now_utc - last_time).total_seconds() if last_time else None
        if not force and cache_age is not None and cache_age < ttl:
            logger.debug(
                "NewsService dùng cache (age=%.1fs < ttl=%ss, priority=%s).",
                cache_age,
                ttl,
                priority,
            )
            return {
                "events": cache_copy,
                "source": "cache",
                "priority": priority,
                "ttl": ttl,
                "latency_sec": 0.0,
            }

        cancel_token.raise_if_cancelled()
        events = self._collect_events(
            threading_manager=threading_manager,
            cancel_token=cancel_token,
            timeout_sec=timeout_sec,
            priority=priority,
        )
        cancel_token.raise_if_cancelled()

        filtered_events = self._filter_high_impact(events)

        with self._lock:
            self._cache = filtered_events
            self._cache_time = now_utc
            self._last_refresh = now_utc
            self._last_latency_sec = monotonic() - start_time
            callback = self._update_callback
            cache_copy = list(self._cache)

        if callback:
            try:
                callback(cache_copy)
            except Exception:
                logger.exception("Lỗi khi thực thi callback cập nhật tin tức.")

        logger.info(
            "NewsService làm mới cache (%d sự kiện, priority=%s, source=network, latency=%.2fs)",
            len(cache_copy),
            priority,
            self._last_latency_sec,
        )

        return {
            "events": cache_copy,
            "source": "network",
            "priority": priority,
            "ttl": ttl,
            "latency_sec": self._last_latency_sec,
        }

    def _collect_events(
        self,
        *,
        threading_manager: ThreadingManager,
        cancel_token: CancelToken,
        timeout_sec: int,
        priority: str,
    ) -> list[dict[str, Any]]:
        """Thu thập dữ liệu thô từ các provider đã bật."""

        with self._lock:
            fmp_service = self.fmp_service
            te_service = self.te_service

        if not fmp_service and not te_service:
            logger.debug("Không có nhà cung cấp tin tức nào được kích hoạt.")
            return []

        tasks = []
        if fmp_service:
            tasks.append(("fmp", fmp_service.get_economic_calendar, self._transform_fmp_data))
        if te_service:
            tasks.append(("te", te_service.get_calendar_events, self._transform_te_data))

        provider_records: list[tuple[str, Callable[[list[dict]], list[dict]], Any]] = []
        self._dedup_ids.clear()

        for provider_name, fetch_fn, transform_fn in tasks:

            def provider_worker(cancel_token: CancelToken, fn=fetch_fn) -> list[dict]:
                cancel_token.raise_if_cancelled()
                return fn()

            record = threading_manager.submit(
                func=provider_worker,
                group="news.polling",
                name=f"news.provider.{provider_name}",
                cancel_token=cancel_token,
                timeout=timeout_sec,
                metadata={"component": "news", "provider": provider_name, "priority": priority},
            )
            provider_records.append((provider_name, transform_fn, record))

        aggregated: list[dict[str, Any]] = []
        for provider_name, transform_fn, record in provider_records:
            try:
                raw_data = record.future.result(timeout=timeout_sec)
                cancel_token.raise_if_cancelled()
                if raw_data:
                    aggregated.extend(transform_fn(raw_data))
            except CancelledError:
                logger.info("Provider %s bị hủy do cancel token.", provider_name)
            except TimeoutError:
                logger.warning("Provider %s vượt quá timeout %ss.", provider_name, timeout_sec)
            except Exception as exc:
                logger.warning("Provider %s gặp lỗi: %s", provider_name, exc)

        return aggregated

    def _transform_fmp_data(self, events: list[dict]) -> list[dict]:
        """Chuyển đổi dữ liệu từ FMP API (thực chất là investpy)."""
        transformed = []
        for event in events:
            try:
                date_str = event.get("date")
                time_str = event.get("time")
                event_title = event.get("event")

                if not all([date_str, time_str, event_title]): continue
                event_id = f"investpy_{date_str}_{time_str}_{event_title}"
                if event_id in self._dedup_ids: continue
                if time_str.lower() == "all day": continue
                
                time_str_cleaned = time_str.strip()
                datetime_str = f"{date_str} {time_str_cleaned}"
                dt_naive = datetime.strptime(datetime_str, "%d/%m/%Y %H:%M")
                dt_utc = pytz.utc.localize(dt_naive)

                transformed.append({
                    "id": event_id, "when_utc": dt_utc, "title": event_title,
                    "country": event.get("zone"), "impact": event.get("importance"),
                    "source": "investpy"
                })
                self._dedup_ids.add(event_id)
            except (ValueError, KeyError, TypeError) as e:
                logger.warning(f"Bỏ qua sự kiện investpy không hợp lệ: {event}. Lỗi: {e}")
        return transformed

    def _transform_te_data(self, events: list[dict]) -> list[dict]:
        """Chuyển đổi dữ liệu từ Trading Economics API."""
        transformed = []
        for event in events:
            try:
                event_id = f"te_{event.get('CalendarId', '')}"
                if not event.get('CalendarId') or event_id in self._dedup_ids: continue

                dt_utc = datetime.strptime(str(event["Date"]), "%Y-%m-%dT%H:%M:%S").replace(tzinfo=pytz.utc)
                transformed.append({
                    "id": event_id, "when_utc": dt_utc, "title": event.get("Event"),
                    "country": event.get("Country"), "impact": event.get("Importance"), "source": "TE"
                })
                self._dedup_ids.add(event_id)
            except (ValueError, KeyError, TypeError) as e:
                logger.warning(f"Bỏ qua sự kiện TE không hợp lệ: {event}. Lỗi: {e}")
        return transformed

    def _filter_high_impact(self, events: list[dict]) -> list[dict]:
        """Lọc các sự kiện có impact cao hoặc có trong danh sách ưu tiên."""
        high_impact_events = []
        for event in events:
            impact = str(event.get("impact", "")).lower()
            title = str(event.get("title", "")).lower()
            is_high = impact in {"high", "3"}
            is_priority = any(keyword in title for keyword in HIGH_IMPACT_KEYWORDS)
            if is_high or is_priority:
                high_impact_events.append(event)
        return high_impact_events

    def _symbol_to_currencies(self, sym: str) -> set[str]:
        """Phân tích symbol để tìm các tiền tệ liên quan."""
        s = (sym or "").upper()
        tokens = set(re.findall(r"[A-Z]{3}", s))
        if "XAU" in s or "GOLD" in s: tokens.add("USD")
        if any(k in s for k in ("US30", "SPX", "NDX")): tokens.add("USD")
        return tokens

    def _get_countries_for_symbol(self, symbol: str) -> set[str]:
        """Lấy danh sách các quốc gia/khu vực liên quan đến một symbol."""
        currencies = self._symbol_to_currencies(symbol)
        countries = set()
        for curr in currencies:
            countries.update(CURRENCY_COUNTRY_MAP.get(curr, set()))
        return countries

    def _format_timedelta(self, td: timedelta) -> str:
        """Định dạng timedelta thành chuỗi 'Xh Ym' dễ đọc."""
        total_seconds = int(td.total_seconds())
        hours, remainder = divmod(total_seconds, 3600)
        minutes, _ = divmod(remainder, 60)
        if hours > 0:
            return f"{hours}h {minutes}m"
        return f"{minutes}m"
