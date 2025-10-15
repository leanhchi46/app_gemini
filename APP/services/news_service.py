from __future__ import annotations

import logging
import re
from concurrent.futures import CancelledError, TimeoutError
from dataclasses import dataclass
from datetime import datetime, timedelta
from threading import Lock
from time import monotonic
from typing import Any, Callable, Final, Iterable, List, Optional

import pytz

from APP.configs.app_config import FMPConfig, NewsConfig, RunConfig, TEConfig
from APP.services.fmp_service import FMPService
from APP.services.te_service import TEService
from APP.utils.threading_utils import CancelToken, ThreadingManager

logger = logging.getLogger(__name__)

# Ánh xạ tiền tệ và quốc gia/khu vực mặc định
DEFAULT_CURRENCY_COUNTRY_MAP: Final[dict[str, set[str]]] = {
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
DEFAULT_HIGH_IMPACT_KEYWORDS: Final[set[str]] = {
    "interest rate", "cpi", "consumer price index", "nfp", "non-farm payroll",
    "pmi", "purchasing managers", "retail sales", "gdp", "gross domestic product",
    "unemployment rate", "inflation rate", "trade balance", "industrial production",
    "business confidence", "consumer confidence", "ism", "ifo", "zew"
}


@dataclass
class ProviderHealthState:
    """Theo dõi số lần lỗi liên tiếp và thời điểm lỗi gần nhất của provider."""

    failures: int = 0
    last_failure: float = 0.0


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

        self._priority_keywords: set[str] = {kw.lower() for kw in DEFAULT_HIGH_IMPACT_KEYWORDS}
        self._surprise_threshold: float = 0.5
        self._provider_health: dict[str, ProviderHealthState] = {}
        self._provider_error_threshold: int = 2
        self._provider_backoff_sec: int = 300
        self._currency_country_map: dict[str, set[str]] = {
            currency: {self._normalize_country_name(alias) for alias in aliases}
            for currency, aliases in DEFAULT_CURRENCY_COUNTRY_MAP.items()
        }
        self._symbol_country_overrides: dict[str, set[str]] = {}
        
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

            self._priority_keywords = self._build_priority_keywords(
                config.news.priority_keywords if config.news else None
            )
            self._surprise_threshold = (
                config.news.surprise_score_threshold if config.news else 0.5
            )
            self._provider_error_threshold = (
                config.news.provider_error_threshold if config.news else 2
            )
            self._provider_backoff_sec = (
                config.news.provider_error_backoff_sec if config.news else 300
            )
            self._currency_country_map = self._build_currency_country_map(
                config.news.currency_country_overrides if config.news else None
            )
            self._symbol_country_overrides = self._build_symbol_overrides(
                config.news.symbol_country_overrides if config.news else None
            )
            
            # Khởi tạo lại các service con nếu cần
            self.fmp_service = None
            if config.fmp and config.fmp.enabled:
                try:
                    self.fmp_service = FMPService(config.fmp)
                except Exception as exc:
                    logger.error("Không thể khởi tạo FMPService: %s", exc, exc_info=True)

            self.te_service = None
            if config.te and config.te.enabled:
                try:
                    self.te_service = TEService(config.te)
                except Exception as exc:
                    logger.error("Không thể khởi tạo TEService: %s", exc, exc_info=True)

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
            if allowed_countries:
                normalized_country = self._normalize_country_name(event_country)
                if not normalized_country or normalized_country not in allowed_countries:
                    continue

            # Tạo một bản sao của event để thêm các trường tính toán
            processed_event = event.copy()
            processed_event["when_local"] = event_time_utc.astimezone(ho_chi_minh_tz)
            time_diff = event_time_utc - now_utc
            processed_event["time_remaining"] = self._format_timedelta(time_diff)
            upcoming_events.append(processed_event)

        return sorted(upcoming_events, key=lambda x: x["when_utc"])

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
        """
        Thu thập dữ liệu thô từ các provider đã bật.
        Logic được thiết kế để vẫn thành công ngay cả khi chỉ một provider hoạt động.
        """

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

        now_monotonic = monotonic()
        for provider_name, fetch_fn, transform_fn in tasks:
            if self._should_skip_provider(provider_name, now_monotonic):
                logger.info("Bỏ qua provider %s do đang trong thời gian backoff.", provider_name)
                continue

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
        successful_providers = 0
        for provider_name, transform_fn, record in provider_records:
            try:
                raw_data = record.future.result(timeout=timeout_sec)
                cancel_token.raise_if_cancelled()

                # Một lệnh gọi thành công, ngay cả khi không có dữ liệu, vẫn được tính là thành công.
                self._record_provider_success(provider_name)
                successful_providers += 1

                if raw_data:
                    aggregated.extend(transform_fn(raw_data))
            except CancelledError:
                logger.info("Provider %s bị hủy do cancel token.", provider_name)
            except TimeoutError:
                logger.warning("Provider %s vượt quá timeout %ss.", provider_name, timeout_sec)
                self._record_provider_failure(provider_name)
            except Exception as exc:
                logger.warning("Provider %s gặp lỗi: %s", provider_name, exc)
                self._record_provider_failure(provider_name)

        if not successful_providers and provider_records:
            logger.warning(
                "Tất cả các nhà cung cấp tin tức (%d) đều thất bại. "
                "Phân tích sẽ tiếp tục với dữ liệu tin tức trống.",
                len(provider_records)
            )

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

                transformed.append(
                    self._enrich_event_metrics(
                        {
                            "id": event_id,
                            "when_utc": dt_utc,
                            "title": event_title,
                            "country": event.get("zone"),
                            "impact": event.get("importance"),
                            "source": "investpy",
                            "actual": event.get("actual"),
                            "forecast": event.get("forecast"),
                            "previous": event.get("previous"),
                            "unit": event.get("unit") or event.get("unit_text"),
                        }
                    )
                )
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
                transformed.append(
                    self._enrich_event_metrics(
                        {
                            "id": event_id,
                            "when_utc": dt_utc,
                            "title": event.get("Event"),
                            "country": event.get("Country"),
                            "impact": event.get("Importance"),
                            "source": "TE",
                            "actual": event.get("Actual"),
                            "forecast": event.get("Forecast"),
                            "previous": event.get("Previous"),
                            "unit": event.get("Unit"),
                        }
                    )
                )
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
            is_priority = any(keyword in title for keyword in self._priority_keywords)
            surprise = event.get("surprise_score")
            surprise_triggered = (
                self._surprise_threshold > 0
                and surprise is not None
                and abs(surprise) >= self._surprise_threshold
            )
            if is_high or is_priority or surprise_triggered:
                high_impact_events.append(event)

        high_impact_events.sort(
            key=lambda e: (
                e.get("when_utc") or datetime.max.replace(tzinfo=pytz.utc),
                -(abs(e.get("surprise_score")) if e.get("surprise_score") is not None else 0.0),
            )
        )
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
        symbol_key = (symbol or "").upper()
        if symbol_key in self._symbol_country_overrides:
            return set(self._symbol_country_overrides[symbol_key])

        currencies = self._symbol_to_currencies(symbol)
        countries = set()
        for curr in currencies:
            countries.update(self._currency_country_map.get(curr, set()))
        return countries

    def _format_timedelta(self, td: timedelta) -> str:
        """Định dạng timedelta thành chuỗi 'Xh Ym' dễ đọc."""
        total_seconds = int(td.total_seconds())
        hours, remainder = divmod(total_seconds, 3600)
        minutes, _ = divmod(remainder, 60)
        if hours > 0:
            return f"{hours}h {minutes}m"
        return f"{minutes}m"

    def _build_priority_keywords(self, keywords: Iterable[str] | None) -> set[str]:
        raw_keywords = keywords or DEFAULT_HIGH_IMPACT_KEYWORDS
        normalized = {
            str(keyword).strip().lower()
            for keyword in raw_keywords
            if str(keyword).strip()
        }
        return normalized or {kw.lower() for kw in DEFAULT_HIGH_IMPACT_KEYWORDS}

    def _build_currency_country_map(
        self, overrides: dict[str, list[str]] | None
    ) -> dict[str, set[str]]:
        base_map = {
            currency: {self._normalize_country_name(alias) for alias in aliases}
            for currency, aliases in DEFAULT_CURRENCY_COUNTRY_MAP.items()
        }
        if not overrides:
            return base_map

        for currency, alias_list in overrides.items():
            if not currency:
                continue
            currency_key = currency.strip().upper()
            base_aliases = base_map.setdefault(currency_key, set())
            for alias in alias_list or []:
                normalized = self._normalize_country_name(alias)
                if normalized:
                    base_aliases.add(normalized)
        return base_map

    def _build_symbol_overrides(
        self, overrides: dict[str, list[str]] | None
    ) -> dict[str, set[str]]:
        if not overrides:
            return {}
        mapped: dict[str, set[str]] = {}
        for symbol, alias_list in overrides.items():
            if not symbol or not alias_list:
                continue
            symbol_key = symbol.strip().upper()
            normalized_aliases = {
                self._normalize_country_name(alias)
                for alias in alias_list
                if self._normalize_country_name(alias)
            }
            if normalized_aliases:
                mapped[symbol_key] = normalized_aliases
        return mapped

    def _normalize_country_name(self, name: Any) -> str:
        if name is None:
            return ""
        text = str(name).strip()
        return text.casefold() if text else ""

    def _parse_numeric(self, value: Any) -> Optional[float]:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        text = str(value).strip()
        if not text or text.lower() in {"n/a", "na", "null", "--"}:
            return None
        sanitized = text.replace("%", "").replace(",", "")
        try:
            return float(sanitized)
        except ValueError:
            return None

    def _enrich_event_metrics(self, event: dict[str, Any]) -> dict[str, Any]:
        actual = self._parse_numeric(event.get("actual"))
        forecast = self._parse_numeric(event.get("forecast"))
        previous = self._parse_numeric(event.get("previous"))
        event["actual"] = actual
        event["forecast"] = forecast
        event["previous"] = previous

        surprise, direction = self._calculate_surprise(actual, forecast, previous)
        event["surprise_score"] = surprise
        if direction:
            event["surprise_direction"] = direction
        return event

    def _calculate_surprise(
        self,
        actual: Optional[float],
        forecast: Optional[float],
        previous: Optional[float],
    ) -> tuple[Optional[float], Optional[str]]:
        if actual is None:
            return None, None

        baseline = forecast if forecast is not None else previous
        if baseline is None:
            return None, None

        denominator = abs(baseline) if abs(baseline) > 1e-9 else 1.0
        surprise = (actual - baseline) / denominator
        direction = "positive" if surprise > 0 else "negative" if surprise < 0 else "neutral"
        return surprise, direction

    def _record_provider_failure(self, provider: str) -> None:
        with self._lock:
            state = self._provider_health.setdefault(provider, ProviderHealthState())
            state.failures += 1
            state.last_failure = monotonic()

    def _record_provider_success(self, provider: str) -> None:
        with self._lock:
            if provider in self._provider_health:
                self._provider_health[provider] = ProviderHealthState()

    def _should_skip_provider(self, provider: str, now_monotonic: float) -> bool:
        with self._lock:
            state = self._provider_health.get(provider)
            threshold = max(0, self._provider_error_threshold)
            if not state or state.failures < threshold:
                return False

            failures_over_threshold = max(0, state.failures - threshold)
            backoff = self._provider_backoff_sec * max(1, 2 ** failures_over_threshold)
            if now_monotonic - state.last_failure < backoff:
                logger.warning(
                    "Bỏ qua provider %s do đang backoff (failures=%s, chờ %.0fs)",
                    provider,
                    state.failures,
                    backoff - (now_monotonic - state.last_failure),
                )
                return True
            return False
