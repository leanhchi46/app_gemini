from __future__ import annotations

import json
import re
import time
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple, List, Dict, Any, TYPE_CHECKING  # Thêm TYPE_CHECKING
import urllib.request
import threading  # Thêm threading

if TYPE_CHECKING:  # Thêm TYPE_CHECKING
    from scripts.tool import TradingToolApp
    from src.config.config import RunConfig

from src.config.config import RunConfig
from src.services.telegram_client import build_ssl_context


FF_THISWEEK = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
FF_NEXTWEEK = "https://nfs.faireconomy.media/ff_calendar_nextweek.json"


def _http_get(
    url: str, *, cafile: Optional[str], skip_verify: bool, timeout: int = 20
) -> str:
    ctx = build_ssl_context(cafile, skip_verify)
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx))
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (AI-ICT)"})
    with opener.open(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def event_currency(ev: dict) -> Optional[str]:
    for k in ("currency", "country", "countryCode", "country_code"):
        c = ev.get(k)
        if isinstance(c, str):
            c = c.strip().upper()
            if len(c) == 3 and c.isalpha():
                return c
    return None


def symbol_currencies(sym: str) -> set[str]:
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
            impact = (
                (
                    ev.get("impact")
                    or ev.get("impactLabel")
                    or ev.get("impact_text")
                    or ""
                )
                .strip()
                .lower()
            )
            if not (("high" in impact) or ("red" in impact) or ("độ cao" in impact)):
                continue
            title = (ev.get("title") or ev.get("event") or ev.get("name") or "").strip()
            tlow = title.lower()
            if any(
                k in tlow
                for k in (
                    "bank holiday",
                    "holiday",
                    "tentative",
                    "all day",
                    "daylight",
                    "speaks",
                    "speech",
                )
            ):
                continue
            ts = (
                ev.get("timestamp")
                or ev.get("dateEventUnix")
                or ev.get("unixTime")
                or ev.get("timeUnix")
            )
            dt_local = None
            if isinstance(ts, (int, float)) and ts > 0:
                dt_local = datetime.fromtimestamp(int(ts), tz=timezone.utc).astimezone()
            if not dt_local:
                continue
            cur = event_currency(ev)
            out.append(
                {"when": dt_local, "title": title or "High-impact event", "curr": cur}
            )
        except Exception:
            continue
    return out


def _dedup_and_trim_week(
    events: List[Dict[str, Any]], now: Optional[datetime] = None
) -> List[Dict[str, Any]]:
    now_local = (now or datetime.now()).astimezone()
    keep = [
        x
        for x in events
        if abs((x["when"] - now_local).total_seconds()) <= 7 * 24 * 3600
    ]
    keep.sort(key=lambda x: x["when"])
    seen, dedup = set(), []
    for x in keep:
        key = (x["title"], int(x["when"].timestamp()) // 60)
        if key in seen:
            continue
        seen.add(key)
        dedup.append(x)
    return dedup


def fetch_high_impact_events(
    *, cafile: Optional[str], skip_verify: bool, timeout: int = 20
) -> List[Dict[str, Any]]:
    datasets: List[Any] = []
    for url in (FF_THISWEEK, FF_NEXTWEEK):
        try:
            body = _http_get(
                url, cafile=cafile, skip_verify=skip_verify, timeout=timeout
            )
            datasets.append(json.loads(body))
        except Exception:
            continue
    all_events: List[Dict[str, Any]] = []
    for ds in datasets:
        all_events.extend(_parse_dataset(ds))
    return _dedup_and_trim_week(all_events)


def fetch_high_impact_events_for_cfg(
    cfg: RunConfig, timeout: int = 20
) -> List[Dict[str, Any]]:
    cafile = getattr(cfg, "telegram_ca_path", None) or None
    skip = bool(getattr(cfg, "telegram_skip_verify", False))
    return fetch_high_impact_events(cafile=cafile, skip_verify=skip, timeout=timeout)


def is_within_news_window(
    events: List[Dict[str, Any]],
    symbol: str,
    minutes_before: int,
    minutes_after: int,
    *,
    now: Optional[datetime] = None,
) -> Tuple[bool, Optional[str]]:
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
    """Check news window using cached events, refreshing if TTL expired.

    Returns (ok, why, events, fetch_time).
    """
    cur_ts = time.time()
    events: List[Dict[str, Any]]
    fetch_ts: float
    if not cache_events or (cur_ts - float(cache_fetch_time or 0.0)) > max(
        0, int(ttl_sec)
    ):
        events = fetch_high_impact_events(
            cafile=cafile, skip_verify=skip_verify, timeout=20
        )
        fetch_ts = cur_ts
    else:
        events = cache_events
        fetch_ts = float(cache_fetch_time or 0.0)
    ok, why = is_within_news_window(
        events, symbol, minutes_before, minutes_after, now=now
    )
    return ok, why, events, fetch_ts


def within_news_window_cfg_cached(
    cfg: RunConfig,
    minutes_before: int,
    minutes_after: int,
    *,
    cache_events: Optional[List[Dict[str, Any]]],
    cache_fetch_time: Optional[float],
    ttl_sec: int = 300,
    now: Optional[datetime] = None,
) -> Tuple[bool, Optional[str], List[Dict[str, Any]], float]:
    """Check news window using cfg-based fetch and cached events.

    Returns (ok, why, events, fetch_time).
    """
    cur_ts = time.time()
    events: List[Dict[str, Any]]
    fetch_ts: float
    if not cache_events or (cur_ts - float(cache_fetch_time or 0.0)) > max(
        0, int(ttl_sec)
    ):
        events = fetch_high_impact_events_for_cfg(cfg, timeout=20)
        fetch_ts = cur_ts
    else:
        events = cache_events
        fetch_ts = float(cache_fetch_time or 0.0)
    ok, why = is_within_news_window(
        events, cfg.mt5_symbol, minutes_before, minutes_after, now=now
    )
    return ok, why, events, fetch_ts


def next_events_for_symbol(
    events: List[Dict[str, Any]],
    symbol: str,
    *,
    now: Optional[datetime] = None,
    limit: int = 3,
) -> List[Dict[str, Any]]:
    """Return the next few high-impact events relevant to `symbol`.

    Filters by future time and symbol currencies, sorted ascending by time.
    """
    try:
        now_local = (now or datetime.now()).astimezone()
        allowed = symbol_currencies(symbol)
        fut = []
        for ev in events or []:
            t = ev.get("when")
            if not t:
                continue
            if t < now_local:
                continue
            cur = ev.get("curr")
            if allowed and cur and cur not in allowed:
                continue
            fut.append(ev)
        fut.sort(key=lambda x: x.get("when"))
        return fut[: max(0, int(limit))]
    except Exception:
        return []


def refresh_news_cache(
    app: "TradingToolApp",
    ttl: int = 300,
    *,
    async_fetch: bool = True,
    cfg: "RunConfig" | None = None,
) -> None:
    """
    Làm mới bộ đệm tin tức từ Forex Factory nếu dữ liệu đã cũ (quá thời gian `ttl`).
    Có thể chạy đồng bộ hoặc không đồng bộ.
    """
    try:
        now_ts = time.time()
        last_ts = float(app.ff_cache_fetch_time or 0.0)
        if (now_ts - last_ts) <= max(0, int(ttl or 0)):
            return

        # Tạo snapshot config ở luồng chính để đảm bảo an toàn thread
        final_cfg = cfg or app._snapshot_config(app)

        if async_fetch:
            with app._news_refresh_lock:
                if app._news_refresh_inflight:
                    return
                app._news_refresh_inflight = True

            def _do_async(config: RunConfig):
                try:
                    ev = fetch_high_impact_events_for_cfg(config, timeout=20)
                    app.ff_cache_events_local = ev or []
                    app.ff_cache_fetch_time = time.time()
                except Exception as e:
                    logging.warning(f"Lỗi khi làm mới tin tức (async): {e}")
                finally:
                    with app._news_refresh_lock:
                        app._news_refresh_inflight = False

            threading.Thread(target=_do_async, args=(final_cfg,), daemon=True).start()
            return

        # Logic chạy đồng bộ (synchronous)
        if not app._news_refresh_lock.acquire(blocking=False):
            return

        try:
            app._news_refresh_inflight = True
            ev = fetch_high_impact_events_for_cfg(final_cfg, timeout=20)
            app.ff_cache_events_local = ev or []
            app.ff_cache_fetch_time = time.time()
        except Exception as e:
            logging.warning(f"Lỗi khi làm mới tin tức (sync): {e}")
        finally:
            app._news_refresh_inflight = False
            app._news_refresh_lock.release()
    except Exception as e:
        logging.error(f"Lỗi không mong muốn trong refresh_news_cache: {e}")
