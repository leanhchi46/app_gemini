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
    logger.debug(f"Bắt đầu hàm _http_get cho URL: {url}")
    ctx = build_ssl_context(cafile, skip_verify)
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx))
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (AI-ICT)"})

    for attempt in range(3):
        try:
            with opener.open(req, timeout=timeout) as resp:
                body = resp.read().decode("utf-8", errors="ignore")
                logger.debug(f"Đã fetch thành công URL: {url}, độ dài body: {len(body)}.")
                return body
        except Exception as e:
            logger.warning(f"Lần thử {attempt + 1} thất bại khi fetch URL '{url}': {e}")
            if attempt < 2:
                time.sleep(1)
            else:
                logger.error(f"Lỗi khi fetch URL '{url}' sau 3 lần thử: {e}")
                raise
    raise RuntimeError("Không thể fetch URL sau nhiều lần thử.")


def event_currency(ev: dict) -> Optional[str]:
    logger.debug(f"Bắt đầu hàm event_currency cho event: {ev.get('title')}")
    for k in ("currency", "country", "countryCode", "country_code"):
        c = ev.get(k)
        if isinstance(c, str):
            c = c.strip().upper()
            if len(c) == 3 and c.isalpha():
                logger.debug(f"Tìm thấy currency: {c}")
                return c
    logger.debug("Không tìm thấy currency hợp lệ.")
    return None


def symbol_currencies(sym: str) -> set[str]:
    logger.debug(f"Bắt đầu hàm symbol_currencies cho symbol: {sym}")
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


def _parse_dataset(data: Any) -> List[Dict[str, Any]]:
    logger.debug("Bắt đầu hàm _parse_dataset.")
    items: List[dict] = []
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        for key in ("events", "thisWeek", "week", "items", "result"):
            if isinstance(data.get(key), list):
                items = data[key]
                break
        if not items:
            for v in data.values():
                if isinstance(v, list) and v and isinstance(v[0], dict):
                    items = v
                    break

    out: List[Dict[str, Any]] = []
    for ev in items or []:
        try:
            impact = (ev.get("impact") or ev.get("impactLabel") or ev.get("impact_text") or "").strip().lower()
            if not (("high" in impact) or ("red" in impact) or ("độ cao" in impact)):
                continue
            title = (ev.get("title") or ev.get("event") or ev.get("name") or "").strip()
            tlow = title.lower()
            if any(k in tlow for k in ("bank holiday", "holiday", "tentative", "all day", "daylight", "speaks", "speech")):
                continue
            ts = (ev.get("timestamp") or ev.get("dateEventUnix") or ev.get("unixTime") or ev.get("timeUnix"))
            dt_local = None
            if isinstance(ts, (int, float)) and ts > 0:
                dt_local = datetime.fromtimestamp(int(ts), tz=timezone.utc).astimezone()
            if not dt_local:
                continue
            cur = event_currency(ev)
            out.append({"when": dt_local, "title": title or "High-impact event", "curr": cur})
        except Exception as e:
            logger.warning(f"Lỗi khi parse event: {ev}. Chi tiết: {e}")
            continue
    return out


def _dedup_and_trim_week(events: List[Dict[str, Any]], now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    logger.debug(f"Bắt đầu hàm _dedup_and_trim_week với {len(events)} events.")
    now_local = (now or datetime.now()).astimezone()
    keep = [x for x in events if abs((x["when"] - now_local).total_seconds()) <= 7 * 24 * 3600]
    keep.sort(key=lambda x: x["when"])
    seen, dedup = set(), []
    for x in keep:
        key = (x["title"], int(x["when"].timestamp()) // 60)
        if key in seen:
            continue
        seen.add(key)
        dedup.append(x)
    return dedup


def fetch_high_impact_events(*, cafile: Optional[str], skip_verify: bool, timeout: int = 20) -> List[Dict[str, Any]]:
    logger.debug("Bắt đầu hàm fetch_high_impact_events.")
    datasets: List[Any] = []
    for url in (FF_THISWEEK, FF_NEXTWEEK):
        try:
            body = _http_get(url, cafile=cafile, skip_verify=skip_verify, timeout=timeout)
            datasets.append(json.loads(body))
        except Exception as e:
            logger.warning(f"Lỗi khi fetch hoặc parse dataset từ URL '{url}': {e}")
            continue
    all_events: List[Dict[str, Any]] = []
    for ds in datasets:
        all_events.extend(_parse_dataset(ds))
    return _dedup_and_trim_week(all_events)


def fetch_high_impact_events_for_cfg(cfg: "RunConfig", timeout: int = 20) -> List[Dict[str, Any]]:
    logger.debug("Bắt đầu hàm fetch_high_impact_events_for_cfg.")
    cafile = getattr(cfg.telegram, "ca_path", None) or None
    skip = bool(getattr(cfg.telegram, "skip_verify", False))
    return fetch_high_impact_events(cafile=cafile, skip_verify=skip, timeout=timeout)


def is_within_news_window(
    events: List[Dict[str, Any]],
    symbol: str,
    minutes_before: int,
    minutes_after: int,
    *,
    now: Optional[datetime] = None,
) -> Tuple[bool, Optional[str]]:
    logger.debug(f"Bắt đầu hàm is_within_news_window cho symbol: {symbol}, before: {minutes_before}, after: {minutes_after}.")
    now_local = (now or datetime.now()).astimezone()
    allowed = symbol_currencies(symbol)
    bef = max(0, int(minutes_before))
    aft = max(0, int(minutes_after))
    for ev in events:
        if allowed and ev.get("curr") and ev["curr"] not in allowed:
            continue
        t = ev["when"]
        if (t - timedelta(minutes=bef)) <= now_local <= (t + timedelta(minutes=aft)):
            why = f"{ev['title']}" + (f" [{ev['curr']}]" if ev.get("curr") else "")
            logger.info(f"Trong cửa sổ tin tức: {why} @ {t.strftime('%Y-%m-%d %H:%M')}")
            return True, f"{why} @ {t.strftime('%Y-%m-%d %H:%M')}"
    return False, None


def within_news_window_ui_cached(
    cafile: Optional[str],
    skip_verify: bool,
    symbol: str,
    minutes_before: int,
    minutes_after: int,
    *,
    cache_events: Optional[List[Dict[str, Any]]],
    cache_fetch_time: Optional[float],
    ttl_sec: int = 300,
    now: Optional[datetime] = None,
) -> Tuple[bool, Optional[str], List[Dict[str, Any]], float]:
    logger.debug(f"Bắt đầu hàm within_news_window_ui_cached cho symbol: {symbol}, TTL: {ttl_sec}.")
    cur_ts = time.time()
    events: List[Dict[str, Any]]
    fetch_ts: float
    if not cache_events or (cur_ts - float(cache_fetch_time or 0.0)) > max(0, int(ttl_sec)):
        events = fetch_high_impact_events(cafile=cafile, skip_verify=skip_verify, timeout=20)
        fetch_ts = cur_ts
    else:
        events = cache_events
        fetch_ts = float(cache_fetch_time or 0.0)
    ok, why = is_within_news_window(events, symbol, minutes_before, minutes_after, now=now)
    return ok, why, events, fetch_ts


def within_news_window_cfg_cached(
    cfg: "RunConfig",
    minutes_before: int,
    minutes_after: int,
    *,
    cache_events: Optional[List[Dict[str, Any]]],
    cache_fetch_time: Optional[float],
    ttl_sec: int = 300,
    now: Optional[datetime] = None,
) -> Tuple[bool, Optional[str], List[Dict[str, Any]], float]:
    logger.debug(f"Bắt đầu hàm within_news_window_cfg_cached cho symbol: {cfg.mt5.symbol}, TTL: {ttl_sec}.")
    cur_ts = time.time()
    events: List[Dict[str, Any]]
    fetch_ts: float
    if not cache_events or (cur_ts - float(cache_fetch_time or 0.0)) > max(0, int(ttl_sec)):
        events = fetch_high_impact_events_for_cfg(cfg, timeout=20)
        fetch_ts = cur_ts
    else:
        events = cache_events
        fetch_ts = float(cache_fetch_time or 0.0)
    ok, why = is_within_news_window(events, cfg.mt5.symbol, minutes_before, minutes_after, now=now)
    return ok, why, events, fetch_ts


def next_events_for_symbol(
    events: List[Dict[str, Any]],
    symbol: str,
    *,
    now: Optional[datetime] = None,
    limit: int = 3,
) -> List[Dict[str, Any]]:
    logger.debug(f"Bắt đầu hàm next_events_for_symbol cho symbol: {symbol}, limit: {limit}.")
    try:
        now_local = (now or datetime.now()).astimezone()
        allowed = symbol_currencies(symbol)
        fut = []
        for ev in events or []:
            t = ev.get("when")
            if not t or t < now_local:
                continue
            cur = ev.get("curr")
            if allowed and cur and cur not in allowed:
                continue
            fut.append(ev)
        fut.sort(key=lambda x: x.get("when"))
        return fut[: max(0, int(limit))]
    except Exception as e:
        logger.error(f"Lỗi trong next_events_for_symbol: {e}")
        return []

__all__ = [
    "fetch_high_impact_events",
    "fetch_high_impact_events_for_cfg",
    "is_within_news_window",
    "within_news_window_ui_cached",
    "within_news_window_cfg_cached",
    "next_events_for_symbol",
    "symbol_currencies",
]
