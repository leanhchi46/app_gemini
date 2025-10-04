from __future__ import annotations

import json
import logging
import re
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

from APP.services.telegram_service import build_ssl_context

if TYPE_CHECKING:
    from APP.configs.app_config import RunConfig

logger = logging.getLogger(__name__)

FF_THISWEEK = "https://cdn-nfs.faireconomy.media/ff_calendar_thisweek.json"
FF_NEXTWEEK = "https://cdn-nfs.faireconomy.media/ff_calendar_nextweek.json"


def _http_get(
    url: str, *, cafile: Optional[str], skip_verify: bool, timeout: int = 20
) -> str:
    """Thực hiện HTTP GET request với SSL context và cơ chế retry."""
    ctx = build_ssl_context(cafile, skip_verify)
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx))
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (AI-ICT)"})

    for attempt in range(3):
        try:
            with opener.open(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", errors="ignore")
        except Exception as e:
            logger.warning(f"Lần thử {attempt + 1} thất bại khi fetch URL '{url}': {e}")
            if attempt < 2:
                time.sleep(1)
            else:
                logger.error(f"Lỗi khi fetch URL '{url}' sau 3 lần thử.")
                raise
    raise RuntimeError("Không thể fetch URL sau nhiều lần thử.")


def _parse_dataset(data: Any) -> List[Dict[str, Any]]:
    """Phân tích dữ liệu JSON từ Forex Factory để trích xuất các sự kiện quan trọng."""
    items: List[dict] = []
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        for key in ("events", "thisWeek", "week", "items", "result"):
            if isinstance(data.get(key), list):
                items = data[key]
                break

    out: List[Dict[str, Any]] = []
    for ev in items or []:
        try:
            impact = (ev.get("impact") or "").strip().lower()
            if "high" not in impact and "red" not in impact:
                continue

            title = (ev.get("title") or "").strip()
            if any(k in title.lower() for k in ("bank holiday", "tentative", "speaks")):
                continue

            ts = ev.get("timestamp")
            if not isinstance(ts, (int, float)) or ts <= 0:
                continue

            dt_local = datetime.fromtimestamp(int(ts), tz=timezone.utc).astimezone()
            cur = (ev.get("currency") or ev.get("country") or "").strip().upper()
            out.append({"when": dt_local, "title": title, "curr": cur if len(cur) == 3 else None})
        except Exception:
            continue
    return out


def _dedup_and_trim_week(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Loại bỏ các sự kiện trùng lặp và chỉ giữ lại các sự kiện trong vòng 7 ngày."""
    now_local = datetime.now().astimezone()
    seven_days = timedelta(days=7)
    keep = [e for e in events if abs(e["when"] - now_local) <= seven_days]
    keep.sort(key=lambda x: x["when"])
    
    seen, dedup = set(), []
    for x in keep:
        key = (x["title"], int(x["when"].timestamp()) // 60)
        if key not in seen:
            seen.add(key)
            dedup.append(x)
    return dedup


def get_forex_factory_news(cfg: RunConfig, timeout: int = 20) -> List[Dict[str, Any]]:
    """
    Tải và phân tích dữ liệu tin tức có tác động mạnh từ Forex Factory cho tuần này và tuần tới.
    """
    logger.debug("Bắt đầu tải tin tức Forex Factory.")
    cafile = getattr(cfg, "telegram_ca_path", None)
    skip_verify = bool(getattr(cfg, "telegram_skip_verify", False))
    
    datasets: List[Any] = []
    for url in (FF_THISWEEK, FF_NEXTWEEK):
        try:
            body = _http_get(url, cafile=cafile, skip_verify=skip_verify, timeout=timeout)
            datasets.append(json.loads(body))
        except Exception as e:
            logger.warning(f"Lỗi khi tải hoặc phân tích dữ liệu từ '{url}': {e}")
            continue
            
    all_events = [event for ds in datasets for event in _parse_dataset(ds)]
    return _dedup_and_trim_week(all_events)


def symbol_currencies(sym: str) -> set[str]:
    """Trích xuất các mã tiền tệ từ một mã giao dịch."""
    if not sym:
        return set()
    s = sym.upper()
    tokens = set(re.findall(r"[A-Z]{3}", s))
    if "XAU" in s or "GOLD" in s:
        tokens.update({"XAU", "USD"})
    # Thêm các quy tắc cho các mã phổ biến khác nếu cần
    return {t for t in tokens if len(t) == 3 and t.isalpha()}


def is_within_news_window(
    events: List[Dict[str, Any]],
    symbol: str,
    minutes_before: int,
    minutes_after: int,
    now: Optional[datetime] = None,
) -> Tuple[bool, Optional[str]]:
    """
    Kiểm tra xem thời gian hiện tại có nằm trong cửa sổ tin tức của một symbol cụ thể hay không.
    """
    now_local = (now or datetime.now()).astimezone()
    affected_currencies = symbol_currencies(symbol)
    
    for event in events:
        event_time = event.get("when")
        event_curr = event.get("curr")
        
        if not event_time or (affected_currencies and event_curr not in affected_currencies):
            continue

        time_before = event_time - timedelta(minutes=minutes_before)
        time_after = event_time + timedelta(minutes=minutes_after)

        if time_before <= now_local <= time_after:
            reason = f"{event['title']} [{event_curr}] @ {event_time.strftime('%H:%M')}"
            logger.info(f"Trong cửa sổ tin tức: {reason}")
            return True, reason
            
    return False, None
