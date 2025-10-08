from __future__ import annotations

import logging
import re
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Callable, Final, List, Optional

import pytz

from APP.configs.app_config import FMPConfig, NewsConfig, RunConfig, TEConfig
from APP.services.fmp_service import FMPService
from APP.services.te_service import TEService

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
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._worker_thread: Optional[threading.Thread] = None
        self._update_callback: Optional[Callable[[List[dict[str, Any]]], None]] = None

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

    def start(self):
        """Khởi động luồng nền để làm mới tin tức tự động."""
        if self._worker_thread and self._worker_thread.is_alive():
            logger.warning("Luồng nền của NewsService đã chạy rồi.")
            return
        
        self._stop_event.clear()
        self._worker_thread = threading.Thread(target=self._background_worker, daemon=True)
        self._worker_thread.start()
        logger.info("Dịch vụ nền NewsService đã được khởi động.")

    def stop(self):
        """Dừng luồng nền một cách an toàn."""
        if self._worker_thread and self._worker_thread.is_alive():
            logger.info("Đang yêu cầu dừng dịch vụ nền NewsService...")
            self._stop_event.set()
            self._worker_thread.join(timeout=5.0)
            if self._worker_thread.is_alive():
                logger.error("Luồng nền NewsService không dừng kịp thời.")
            else:
                logger.info("Dịch vụ nền NewsService đã dừng thành công.")
        self._worker_thread = None

    def _background_worker(self):
        """Vòng lặp chính của luồng nền, chịu trách nhiệm làm mới cache định kỳ."""
        logger.debug("Luồng nền NewsService bắt đầu, chờ 2 giây để config được tải.")
        # Chờ một chút lúc khởi động để đảm bảo config ban đầu đã được áp dụng.
        if self._stop_event.wait(timeout=2.0):
            return  # Thoát nếu có tín hiệu dừng ngay lúc khởi động

        while not self._stop_event.is_set():
            try:
                with self._lock:
                    is_enabled = self.fmp_service is not None or self.te_service is not None
                
                if is_enabled:
                    logger.info("Luồng nền: Bắt đầu làm mới cache tin tức...")
                    self._fetch_and_process_events()
                else:
                    logger.debug("Luồng nền: Không có nhà cung cấp tin tức nào được bật, bỏ qua lần làm mới.")

            except Exception:
                logger.exception("Lỗi không mong muốn trong luồng nền của NewsService.")
            
            with self._lock:
                refresh_interval = self.news_config.cache_ttl_sec if self.news_config else 300
            
            # Đợi cho đến lần làm mới tiếp theo hoặc cho đến khi có tín hiệu dừng
            if self._stop_event.wait(timeout=refresh_interval):
                break # Thoát vòng lặp nếu có tín hiệu dừng
        logger.debug("Luồng nền NewsService đã thoát khỏi vòng lặp.")

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

    def get_news_analysis(self, symbol: str) -> dict[str, Any]:
        """
        Lấy phân tích tin tức tức thì từ cache.
        """
        try:
            now_utc = datetime.now(pytz.utc)
            is_in_blackout, reason = self.is_in_news_blackout(symbol=symbol, now=now_utc)
            upcoming_events = self.get_upcoming_events(symbol=symbol, now=now_utc)

            return {
                "is_in_news_window": is_in_blackout,
                "reason": reason,
                "upcoming_events": upcoming_events[:3],  # Chỉ lấy 3 sự kiện gần nhất
            }
        except Exception as e:
            logger.error(f"Lỗi khi phân tích tin tức từ cache cho '{symbol}': {e}", exc_info=True)
            return {"error": "failed to analyze news from cache"}

    def _fetch_and_process_events(self):
        """
        Lấy và xử lý sự kiện từ TẤT CẢ các nhà cung cấp được kích hoạt.
        Phương thức này giờ đây được gọi bởi luồng nền.
        """
        from concurrent.futures import ThreadPoolExecutor

        all_processed_events = []
        
        with self._lock:
            # Lấy một bản sao của các service để sử dụng trong phương thức này
            fmp_service = self.fmp_service
            te_service = self.te_service

        if not fmp_service and not te_service:
            logger.debug("Không có nhà cung cấp tin tức nào được kích hoạt.")
            return

        self._dedup_ids.clear()
        logger.debug("Đã xóa cache ID chống trùng lặp của tin tức.")

        raw_fmp_data = None
        raw_te_data = None

        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="NewsFetcher") as executor:
            future_fmp = executor.submit(fmp_service.get_economic_calendar) if fmp_service else None
            future_te = executor.submit(te_service.get_calendar_events) if te_service else None

            if future_fmp:
                try:
                    raw_fmp_data = future_fmp.result(timeout=15)
                except Exception as e:
                    logger.error(f"Lỗi khi lấy tin tức từ FMP: {e}", exc_info=True)

            if future_te:
                try:
                    raw_te_data = future_te.result(timeout=15)
                except Exception as e:
                    logger.warning(f"Không thể lấy tin tức từ Trading Economics: {e}")

        if raw_fmp_data:
            all_processed_events.extend(self._transform_fmp_data(raw_fmp_data))
        if raw_te_data:
            all_processed_events.extend(self._transform_te_data(raw_te_data))

        new_cache = self._filter_high_impact(all_processed_events)
        
        with self._lock:
            self._cache = new_cache
            self._cache_time = datetime.now(pytz.utc)
            logger.info(f"Cache được cập nhật với {len(self._cache)} sự kiện quan trọng.")
            
            # Lấy callback ra để gọi bên ngoài lock
            callback = self._update_callback
            # Tạo bản sao của cache để gửi đi, đảm bảo an toàn
            cache_copy = list(self._cache)

        # Gọi callback sau khi đã giải phóng lock
        if callback:
            try:
                callback(cache_copy)
                logger.debug("Callback cập nhật tin tức đã được gọi.")
            except Exception:
                logger.exception("Lỗi khi thực thi callback cập nhật tin tức.")

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
