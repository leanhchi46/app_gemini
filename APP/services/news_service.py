# -*- coding: utf-8 -*-
"""
Module để lấy và xử lý các tin tức kinh tế có tác động mạnh từ Forex Factory.
Sử dụng Playwright để trích xuất dữ liệu JSON từ biến JavaScript của trang web.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from playwright.async_api import async_playwright

if TYPE_CHECKING:
    from APP.configs.app_config import RunConfig

logger = logging.getLogger(__name__)


# --- Constants ---
BASE_URL = "https://www.forexfactory.com"
# URL mới dựa trên phương pháp scraping
FF_THISWEEK_URL = f"{BASE_URL}/calendar?week=this"
FF_NEXTWEEK_URL = f"{BASE_URL}/calendar?week=next"

EXCLUDED_EVENT_KEYWORDS = (
    "bank holiday", "holiday", "tentative", "all day",
    "daylight", "speaks", "speech",
)


# --- Core Scraping Logic ---

async def _scrape_calendar_data(url: str) -> List[Dict[str, Any]]:
    """
    Sử dụng Playwright để truy cập URL và trích xuất dữ liệu lịch từ biến JS.
    """
    logger.info(f"🌐 Đang scrape dữ liệu từ: {url}")
    days_array: List[Dict[str, Any]] = []
    
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            )
            page = await context.new_page()
            
            await page.goto(url, wait_until="domcontentloaded", timeout=15000)
            
            # Trích xuất dữ liệu từ biến JavaScript `calendarComponentStates`
            data = await page.evaluate(
                """() => {
                    if (typeof window.calendarComponentStates === 'undefined') { return []; }
                    return (window.calendarComponentStates[1]?.days || window.calendarComponentStates[0]?.days || []);
                }"""
            )
            days_array = data or []
            
            await browser.close()
            logger.info(f"✅ Trích xuất thành công {len(days_array)} ngày dữ liệu.")
            return days_array
    except Exception:
        logger.error(f"⚠️ Lỗi nghiêm trọng khi scraping {url}", exc_info=True)
        return []


# --- Data Parsing and Normalization ---

def _parse_scraped_data(days_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Phân tích dữ liệu thô từ scraping và chuyển đổi thành định dạng chuẩn.
    """
    all_events: List[Dict[str, Any]] = []
    for day in days_data:
        for event in day.get("events", []):
            try:
                impact = event.get("impact", "").lower()
                if "high" not in impact and "red" not in impact:
                    continue

                title = event.get("title", "").strip()
                if not title or any(k in title.lower() for k in EXCLUDED_EVENT_KEYWORDS):
                    continue

                timestamp = event.get("datetime")
                if not isinstance(timestamp, int) or timestamp <= 0:
                    continue
                
                # Chuyển đổi timestamp sang datetime object có múi giờ
                dt_utc = datetime.fromtimestamp(timestamp, tz=timezone.utc)

                all_events.append({
                    "when": dt_utc.astimezone(), # Chuyển sang múi giờ địa phương
                    "title": title,
                    "curr": event.get("currency", "").strip().upper() or None,
                })
            except Exception:
                logger.warning(f"Lỗi khi parse event: {event}", exc_info=True)
                continue
    return all_events


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

async def get_forex_factory_news_async() -> List[Dict[str, Any]]:
    """
    Hàm bất đồng bộ chính để lấy, phân tích và xử lý tin tức.
    """
    logger.debug("Bắt đầu quy trình lấy tin tức (async).")
    
    # Chạy song song 2 tác vụ scraping
    tasks = [
        _scrape_calendar_data(FF_THISWEEK_URL),
        _scrape_calendar_data(FF_NEXTWEEK_URL),
    ]
    results = await asyncio.gather(*tasks)
    
    raw_data = results[0] + results[1]
    parsed_events = _parse_scraped_data(raw_data)
    final_events = _dedup_and_sort_events(parsed_events)
    
    logger.info(f"Hoàn tất lấy tin tức, tìm thấy {len(final_events)} sự kiện có tác động mạnh.")
    return final_events

def get_forex_factory_news() -> List[Dict[str, Any]]:
    """
    Hàm đồng bộ (wrapper) để tương thích với code hiện tại.
    """
    try:
        # Chạy vòng lặp sự kiện asyncio nếu nó chưa chạy
        loop = asyncio.get_running_loop()
        return loop.run_until_complete(get_forex_factory_news_async())
    except RuntimeError:
        # Nếu không có vòng lặp nào đang chạy, tạo một cái mới
        return asyncio.run(get_forex_factory_news_async())


# --- Utility and Logic Functions (Largely Unchanged) ---

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
