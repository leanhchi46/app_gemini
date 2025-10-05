# -*- coding: utf-8 -*-
"""
Module để lấy và xử lý các tin tức kinh tế có tác động mạnh từ Forex Factory.
Sử dụng cloudscraper để vượt qua Cloudflare và regex để trích xuất dữ liệu.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

import cloudscraper
from bs4 import BeautifulSoup

if TYPE_CHECKING:
    from APP.configs.app_config import RunConfig

logger = logging.getLogger(__name__)

# --- Constants ---
FOREX_FACTORY_URL = "https://www.forexfactory.com/calendar"
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
}
IMPACT_MAP = {"high": "Red", "medium": "Orange", "low": "Yellow"}
EXCLUDED_EVENT_KEYWORDS = (
    "bank holiday", "holiday", "tentative", "all day",
    "daylight", "speaks", "speech",
)

# --- Core Scraping Logic ---

def _fetch_forex_factory_html() -> Optional[str]:
    """
    Lấy nội dung HTML từ lịch của Forex Factory.
    Sử dụng cloudscraper để xử lý các biện pháp bảo vệ của Cloudflare.
    """
    logger.info("🌐 Đang lấy dữ liệu tin tức từ Forex Factory...")
    try:
        scraper = cloudscraper.create_scraper()
        response = scraper.get(FOREX_FACTORY_URL, headers=DEFAULT_HEADERS, timeout=20)
        response.raise_for_status()
        logger.info("✅ Lấy thành công HTML từ Forex Factory.")
        return response.text
    except Exception:
        logger.error("⚠️ Lỗi không xác định khi lấy dữ liệu từ Forex Factory", exc_info=True)
        return None

# --- Data Parsing and Normalization ---

def _parse_html_data(html: str) -> List[Dict[str, Any]]:
    """
    Phân tích HTML từ Forex Factory để trích xuất các sự kiện tin tức.
    """
    soup = BeautifulSoup(html, "html.parser")
    events: List[Dict[str, Any]] = []
    
    table = soup.find("table", class_="calendar__table")
    if not table:
        logger.error("Không tìm thấy bảng lịch trên trang Forex Factory.")
        return events

    rows = table.find_all("tr", class_="calendar__row")
    current_date = None

    for row in rows:
        # Cập nhật ngày hiện tại
        date_cell = row.find("td", class_="calendar__date")
        if date_cell and "date" in date_cell.text.lower():
            date_text = " ".join(date_cell.text.strip().split()[1:])
            try:
                current_date = datetime.strptime(f"{date_text} {datetime.now().year}", "%b %d %Y").date()
            except ValueError:
                logger.warning(f"Không thể phân tích ngày: {date_text}")
                continue
        
        if not current_date:
            continue

        # Bỏ qua các hàng không phải là sự kiện
        if not row.find("td", class_="calendar__impact"):
            continue

        try:
            impact_cell = row.find("td", class_="calendar__impact")
            impact_title = impact_cell.find("span").get("title", "").lower()
            if "high" not in impact_title:
                continue

            title = row.find("td", class_="calendar__event").text.strip()
            if not title or any(k in title.lower() for k in EXCLUDED_EVENT_KEYWORDS):
                continue

            time_str = row.find("td", class_="calendar__time").text.strip()
            if not time_str or "all-day" in time_str.lower():
                continue
            
            # Chuyển đổi thời gian
            event_time = datetime.strptime(time_str, "%I:%M%p").time()
            dt_local = datetime.combine(current_date, event_time)
            # Giả sử thời gian từ FF là giờ New York (ET), cần chuyển sang UTC rồi sang local
            # Đây là một giả định đơn giản, thực tế cần xử lý múi giờ phức tạp hơn
            dt_utc = dt_local.astimezone(timezone.utc)

            events.append({
                "when": dt_utc.astimezone(), # Chuyển sang múi giờ địa phương
                "title": title,
                "curr": row.find("td", class_="calendar__currency").text.strip().upper() or None,
            })
        except Exception:
            logger.warning(f"Lỗi khi parse một hàng sự kiện từ Forex Factory", exc_info=True)
            continue
            
    return events


def _dedup_and_sort_events(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Loại bỏ các sự kiện trùng lặp và sắp xếp theo thời gian."""
    events.sort(key=lambda x: x["when"])
    seen, dedup = set(), []
    for x in events:
        key = (x["title"], int(x["when"].timestamp()) // 60)
        if key not in seen:
            seen.add(key)
            dedup.append(x)
    return dedup


# --- Main Public Function ---

def get_forex_factory_news() -> List[Dict[str, Any]]:
    """
    Hàm chính để lấy, phân tích và xử lý tin tức từ Forex Factory.
    """
    logger.debug("Bắt đầu quy trình lấy tin tức bằng Forex Factory.")
    
    html_content = _fetch_forex_factory_html()
    if not html_content:
        return []
        
    parsed_events = _parse_html_data(html_content)
    final_events = _dedup_and_sort_events(parsed_events)
    
    logger.info(f"Hoàn tất lấy tin tức, tìm thấy {len(final_events)} sự kiện có tác động mạnh.")
    return final_events


# --- Utility and Logic Functions ---

def symbol_currencies(sym: str) -> set[str]:
    """Phân tích một symbol giao dịch để tìm các tiền tệ liên quan."""
    if not sym:
        return set()
    s = sym.upper()
    tokens = set(re.findall(r"[A-Z]{3}", s))
    if "XAU" in s or "GOLD" in s:
        tokens.update({"XAU", "USD"})
    if "XAG" in s or "SILVER" in s:
        tokens.update({"XAG", "USD"})
    if any(k in s for k in ("USOIL", "WTI", "BRENT", "UKOIL")):
        tokens.update({"USD"})
    if any(k in s for k in ("US30", "US500", "US100", "DJI", "SPX", "NAS100", "NDX")):
        tokens.update({"USD"})
    if any(k in s for k in ("DE40", "GER40", "DAX")):
        tokens.update({"EUR"})
    if any(k in s for k in ("UK100", "FTSE")):
        tokens.update({"GBP"})
    if any(k in s for k in ("JP225", "NIK", "NKY")):
        tokens.update({"JPY"})
    return {t for t in tokens if len(t) == 3 and t.isalpha()}


def is_within_news_window(
    events: List[Dict[str, Any]],
    symbol: str,
    minutes_before: int,
    minutes_after: int,
    *,
    now: Optional[datetime] = None,
) -> Tuple[bool, Optional[str]]:
    """Kiểm tra xem thời điểm hiện tại có nằm trong cửa sổ tin tức của một symbol không."""
    now_local = (now or datetime.now()).astimezone()
    allowed_currencies = symbol_currencies(symbol)
    
    for ev in events:
        if allowed_currencies and ev.get("curr") and ev["curr"] not in allowed_currencies:
            continue

        event_time = ev["when"]
        start_window = event_time - timedelta(minutes=max(0, minutes_before))
        end_window = event_time + timedelta(minutes=max(0, minutes_after))

        if start_window <= now_local <= end_window:
            why = f"{ev['title']}" + (f" [{ev['curr']}]" if ev.get("curr") else "")
            logger.info(f"Phát hiện trong cửa sổ tin tức: {why} @ {event_time.strftime('%H:%M')}")
            return True, f"{why} @ {event_time.strftime('%Y-%m-%d %H:%M')}"
            
    return False, None


def within_news_window_cached(
    symbol: str,
    minutes_before: int,
    minutes_after: int,
    *,
    cache_events: Optional[List[Dict[str, Any]]],
    cache_fetch_time: Optional[float],
    ttl_sec: int = 300,
    now: Optional[datetime] = None,
) -> Tuple[bool, Optional[str], List[Dict[str, Any]], float]:
    """
    Kiểm tra cửa sổ tin tức sử dụng cache, làm mới nếu cache hết hạn.
    """
    cur_ts = time.time()
    events: List[Dict[str, Any]]
    fetch_ts: float

    if not cache_events or (cur_ts - (cache_fetch_time or 0.0)) > ttl_sec:
        logger.debug("Cache tin tức hết hạn hoặc không tồn tại, đang fetch lại.")
        events = get_forex_factory_news()
        fetch_ts = cur_ts
    else:
        logger.debug("Sử dụng cache tin tức hiện có.")
        events = cache_events
        fetch_ts = cache_fetch_time or 0.0

    ok, why = is_within_news_window(
        events, symbol, minutes_before, minutes_after, now=now
    )
    return ok, why, events, fetch_ts


def next_events_for_symbol(
    events: List[Dict[str, Any]],
    symbol: str,
    *,
    now: Optional[datetime] = None,
    limit: int = 3,
) -> List[Dict[str, Any]]:
    """
    Trả về các sự kiện quan trọng sắp tới cho một symbol cụ thể.
    """
    try:
        now_local = (now or datetime.now()).astimezone()
        allowed_currencies = symbol_currencies(symbol)
        
        future_events = []
        for ev in events or []:
            if ev.get("when") and ev["when"] > now_local:
                if not allowed_currencies or (ev.get("curr") and ev["curr"] in allowed_currencies):
                    future_events.append(ev)
        
        future_events.sort(key=lambda x: x["when"])
        return future_events[:max(0, limit)]
    except Exception:
        logger.error("Lỗi trong next_events_for_symbol.", exc_info=True)
        return []
