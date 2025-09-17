from __future__ import annotations

import json
import math
import time
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from statistics import median
from typing import Any, Iterable, Sequence

from . import ict_analysis
from .safe_data import SafeMT5Data


try:
    import MetaTrader5 as mt5  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    mt5 = None  # type: ignore


# ------------------------------
# MT5 connection helpers
# ------------------------------

def connect(path: str | None = None) -> tuple[bool, str | None]:
    """
    Initialize connection to MetaTrader5 terminal.

    Returns (ok, error_message). On success, error_message is None.
    """
    if mt5 is None:
        return False, "MetaTrader5 module not installed (pip install MetaTrader5)"
    try:
        ok = mt5.initialize(path=path) if path else mt5.initialize()
        if not ok:
            return False, f"initialize() failed: {mt5.last_error()}"
        return True, None
    except Exception as e:
        return False, f"MT5 connect error: {e}"


def ensure_initialized(path: str | None = None) -> bool:
    """Ensure MT5 is initialized. Returns True if ready."""
    ok, _ = connect(path)
    return ok


# ------------------------------
# Price unit helpers
# ------------------------------

def points_per_pip_from_info(info: dict | Any) -> int:
    """
    Infer points-per-pip from symbol info.
    Accepts either a dict or an mt5.symbol_info(...) object.
    """
    try:
        digits = (info.get("digits") if isinstance(info, dict) else getattr(info, "digits", None)) or 0
        digits = int(digits)
    except Exception:
        digits = 0
    return 10 if digits >= 3 else 1


def pip_size_from_info(info: dict | Any) -> float:
    point = (info.get("point") if isinstance(info, dict) else getattr(info, "point", None)) or 0.0
    try:
        point = float(point)
    except Exception:
        point = 0.0
    ppp = points_per_pip_from_info(info)
    return point * ppp if point else 0.0


def info_get(info: dict | Any, key: str, default: Any = None) -> Any:
    """
    Safe accessor for MT5 info/account-like objects that may be dicts or
    MetaTrader5 structs. Handles a few common key name differences.

    Examples:
    - info_get(info, "digits")
    - info_get(info, "contract_size") -> maps to attr "trade_contract_size" on objects
    - info_get(info, "spread_current") -> maps to attr "spread" on objects
    """
    if info is None:
        return default
    if isinstance(info, dict):
        return info.get(key, default)
    # Map commonly renamed fields from our JSON schema back to MT5 attributes
    attr_map = {
        "contract_size": "trade_contract_size",
        "spread_current": "spread",
        "stop_level_points": "trade_stops_level",
        "freeze_level_points": "trade_freeze_level",
    }
    attr = attr_map.get(key, key)
    return getattr(info, attr, default)


def value_per_point(symbol: str, info_obj: Any | None = None) -> float | None:
    """
    Best-effort estimation of 1-point value per 1.00 lot for `symbol`.
    Tries broker-provided tick value/size, falls back to order_calc_profit, then contract size.
    """
    if mt5 is None:
        return None
    try:
        info_obj = info_obj or mt5.symbol_info(symbol)
        if not info_obj:
            return None

        point = float(getattr(info_obj, "point", 0.0) or 0.0)
        if point <= 0:
            return None

        tick_value = float(getattr(info_obj, "trade_tick_value", 0.0) or 0.0)
        tick_size = float(getattr(info_obj, "trade_tick_size", 0.0) or 0.0)
        if tick_value > 0 and tick_size > 0:
            return tick_value * (point / tick_size)

        try:
            tick = mt5.symbol_info_tick(symbol)
            mid = None
            if tick:
                bid = float(getattr(tick, "bid", 0.0) or 0.0)
                ask = float(getattr(tick, "ask", 0.0) or 0.0)
                mid = (bid + ask) / 2.0 if (bid and ask) else (ask or bid)
            if mid and point > 0:
                pr = mt5.order_calc_profit(mt5.ORDER_TYPE_BUY, symbol, 1.0, mid, mid + point)
                if isinstance(pr, (int, float)):
                    return abs(float(pr))
        except Exception:
            pass

        csize = float(getattr(info_obj, "trade_contract_size", 0.0) or 0.0)
        if csize > 0:
            return csize * point
        return None
    except Exception:
        return None


# ------------------------------
# Math/stat helpers
# ------------------------------

def quantiles(vals: Sequence[float] | None, q_list: Iterable[float]) -> dict[float, float | None]:
    if not vals:
        return {q: None for q in q_list}
    arr = sorted(vals)
    out: dict[float, float | None] = {}
    for q in q_list:
        if q <= 0:
            out[q] = arr[0]
            continue
        if q >= 1:
            out[q] = arr[-1]
            continue
        pos = (len(arr) - 1) * q
        lo = int(math.floor(pos))
        hi = int(math.ceil(pos))
        if lo == hi:
            out[q] = arr[lo]
        else:
            out[q] = arr[lo] + (arr[hi] - arr[lo]) * (pos - lo)
    return out


def ema(values: Sequence[float] | None, period: int) -> float | None:
    if not values or period <= 1:
        return None
    alpha = 2.0 / (period + 1.0)
    e = values[0]
    for v in values[1:]:
        e = alpha * v + (1 - alpha) * e
    try:
        return float(e)
    except Exception:
        return None


def atr_series(rates: Sequence[dict] | None, period: int = 14) -> tuple[float | None, list[float]]:
    """
    rates: list of {high, low, close}
    Returns (atr_last, list_of_TRs)
    """
    if not rates or len(rates) < period + 1:
        return None, []
    trs: list[float] = []
    prev_close = float(rates[0]["close"])  # type: ignore[index]
    for r in rates[1:]:
        hi = float(r["high"])  # type: ignore[index]
        lo = float(r["low"])   # type: ignore[index]
        pc = float(prev_close)
        tr = max(hi - lo, abs(hi - pc), abs(lo - pc))
        trs.append(tr)
        prev_close = float(r["close"])  # type: ignore[index]
    if len(trs) < period:
        return None, trs
    alpha = 1.0 / period
    atr = sum(trs[:period]) / period
    out = [atr]
    for tr in trs[period:]:
        atr = (1 - alpha) * atr + alpha * tr
        out.append(atr)
    return (out[-1] if out else None), trs


def vwap_from_rates(rates: Sequence[dict] | None) -> float | None:
    if not rates:
        return None
    s_pv = 0.0
    s_v = 0.0
    for r in rates:
        tp = (float(r["high"]) + float(r["low"]) + float(r["close"])) / 3.0  # type: ignore[index]
        v = max(1, int(r.get("vol", 0)))
        s_pv += tp * v
        s_v += v
    return s_pv / s_v if s_v > 0 else None


def adr_stats(symbol: str, n: int = 20) -> dict[str, float] | None:
    """Average Daily Range stats for last n days (d5/d10/d20)."""
    if mt5 is None:
        return None
    bars = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_D1, 0, max(25, n + 2))
    if bars is None or len(bars) < 5:
        return None
    ranges = [float(b["high"] - b["low"]) for b in bars[-(n + 1) : -1]]
    if not ranges:
        return None

    def _avg(m: int) -> float | None:
        return sum(ranges[-m:]) / max(1, m) if len(ranges) >= m else None

    return {"d5": _avg(5), "d10": _avg(10), "d20": _avg(20)}  # type: ignore[return-value]


# ------------------------------
# Time/session helpers
# ------------------------------

def _is_us_dst(d: datetime) -> bool:
    """Checks if a given date is within US Daylight Saving Time."""
    if not isinstance(d, datetime):
        return False
    # DST starts on the second Sunday in March at 2 AM
    march_first = datetime(d.year, 3, 1)
    # Day of week: Monday is 0 and Sunday is 6.
    march_second_sunday = march_first + timedelta(days=(6 - march_first.weekday() + 7) % 7 + 7)

    # DST ends on the first Sunday in November at 2 AM
    nov_first = datetime(d.year, 11, 1)
    nov_first_sunday = nov_first + timedelta(days=(6 - nov_first.weekday() + 7) % 7)

    # Create timezone-naive datetime objects for comparison
    check_date = datetime(d.year, d.month, d.day)
    return march_second_sunday <= check_date < nov_first_sunday


def _killzone_ranges_vn(d: datetime | None = None, target_tz: str | None = None) -> dict[str, dict[str, str]]:
    """
    Build London/NY killzones in Vietnam time based on US DST.
    """
    if d is None:
        tz_vn = ZoneInfo(target_tz or "Asia/Ho_Chi_Minh")
        d = datetime.now(tz=tz_vn)

    is_summer = _is_us_dst(d)

    asia_session = {"start": "06:00", "end": "09:00"}
    if is_summer:
        # Mùa hè (Tháng 3 – Tháng 11, US DST)
        return {
            "asia": asia_session,
            "london": {"start": "14:00", "end": "17:00"},
            "newyork_am": {"start": "19:30", "end": "22:00"},
            "newyork_pm": {"start": "00:00", "end": "03:00"},
        }
    else:
        # Mùa đông (Tháng 11 – Tháng 3, US Standard Time)
        return {
            "asia": asia_session,
            "london": {"start": "15:00", "end": "18:00"},
            "newyork_am": {"start": "20:30", "end": "23:00"},
            "newyork_pm": {"start": "01:00", "end": "04:00"},
        }


def session_ranges_today(m1_rates: Sequence[dict] | None) -> dict[str, dict]:
    """
    Compute session ranges for Asia/London/NY (split NY into AM/PM) in local VN time.
    Input: M1 rates with keys {time:"YYYY-MM-DD HH:MM:SS", high, low, close, vol}.
    """
    # The m1_rates are not strictly needed anymore since we use system time,
    # but we keep the signature for compatibility. It can be used to check historical sessions.
    # For now, we pass `None` to `_killzone_ranges_vn` to use the current system time.
    return _killzone_ranges_vn(d=None)


def _series_from_mt5(symbol: str, tf_code: int, bars: int) -> list[dict]:
    arr = mt5.copy_rates_from_pos(symbol, tf_code, 0, max(50, int(bars))) if mt5 else None
    rows: list[dict] = []
    if arr is not None:
        for r in arr:
            rows.append(
                {
                    "time": datetime.fromtimestamp(int(r["time"])).strftime("%Y-%m-%d %H:%M:%S"),
                    "open": float(r["open"]),
                    "high": float(r["high"]),
                    "low": float(r["low"]),
                    "close": float(r["close"]),
                    "vol": int(r["tick_volume"]),
                }
            )
    return rows


def _hl_from(symbol: str, tf_code: int, bars: int) -> dict | None:
    data = mt5.copy_rates_from_pos(symbol, tf_code, 0, bars) if mt5 else None
    if data is None or len(data) == 0:
        return None
    hi = max([float(x["high"]) for x in data])
    lo = min([float(x["low"]) for x in data])
    op = float(data[0]["open"])  # first bar open
    return {"open": op, "high": hi, "low": lo}


def _nearby_key_levels(cp: float, info: Any, daily: dict | None, prev_day: dict | None) -> list[dict]:
    lv: list[dict] = []
    if prev_day:
        if "high" in prev_day:
            lv.append({"name": "PDH", "price": float(prev_day["high"])})
        if "low" in prev_day:
            lv.append({"name": "PDL", "price": float(prev_day["low"])})
    if daily:
        if daily.get("eq50") is not None:
            lv.append({"name": "EQ50_D", "price": float(daily["eq50"])})
        if daily.get("open") is not None:
            lv.append({"name": "DO", "price": float(daily["open"])})

    out = []
    point = float(getattr(info, "point", 0.0) or 0.0)
    for x in lv:
        rel = "ABOVE" if x["price"] > cp else ("BELOW" if x["price"] < cp else "INSIDE")
        dist = abs(x["price"] - cp) / (point or 0.01) if cp and point else None
        out.append({"name": x["name"], "price": x["price"], "relation": rel, "distance_pips": dist})
    return out




def build_context(
    symbol: str,
    *,
    n_m1: int = 120,
    n_m5: int = 180,
    n_m15: int = 96,
    n_h1: int = 120,
    return_json: bool = False, # Default changed to return the object
    plan: dict | None = None,
) -> SafeMT5Data:
    """
    Fetches MT5 data + computes helpers used by the app.
    Returns a JSON string (default) containing a single object with key MT5_DATA.
    """
    if mt5 is None:
        return SafeMT5Data(None)

    info = mt5.symbol_info(symbol)
    if not info:
        return SafeMT5Data(None)
    if not getattr(info, "visible", True):
        try:
            mt5.symbol_select(symbol, True)
        except Exception:
            pass
    acc = mt5.account_info()
    tick = mt5.symbol_info_tick(symbol)

    # --- Fetch Open Positions ---
    positions_list = []
    try:
        positions = mt5.positions_get(symbol=symbol)
        if positions:
            for pos in positions:
                pos_dict = {
                    "ticket": pos.ticket,
                    "symbol": pos.symbol,
                    "type": "BUY" if pos.type == 0 else "SELL",
                    "volume": pos.volume,
                    "price_open": pos.price_open,
                    "sl": pos.sl,
                    "tp": pos.tp,
                    "price_current": pos.price_current,
                    "profit": pos.profit,
                    "comment": pos.comment,
                }
                positions_list.append(pos_dict)
    except Exception:
        # In case of any error, ensure the list is empty
        positions_list = []

    info_obj = {
        "digits": getattr(info, "digits", None),
        "point": getattr(info, "point", None),
        "contract_size": getattr(info, "trade_contract_size", None),
        "spread_current": getattr(info, "spread", None),
        "swap_long": getattr(info, "swap_long", None),
        "swap_short": getattr(info, "swap_short", None),
    }
    account_obj = None
    if acc:
        account_obj = {
            "balance": float(getattr(acc, "balance", 0.0)),
            "equity": float(getattr(acc, "equity", 0.0)),
            "free_margin": float(getattr(acc, "margin_free", 0.0)),
            "currency": getattr(acc, "currency", None),
            "leverage": int(getattr(acc, "leverage", 0)) or None,
        }
    rules_obj = {
        "volume_min": getattr(info, "volume_min", None),
        "volume_max": getattr(info, "volume_max", None),
        "volume_step": getattr(info, "volume_step", None),
        "trade_tick_value": getattr(info, "trade_tick_value", None),
        "trade_tick_size": getattr(info, "trade_tick_size", None),
        "stop_level_points": getattr(info, "trade_stops_level", None),
        "freeze_level_points": getattr(info, "trade_freeze_level", None),
        "margin_initial": getattr(info, "margin_initial", None),
        "margin_maintenance": getattr(info, "margin_maintenance", None),
    }

    tick_obj: dict[str, Any] = {}
    if tick:
        tick_obj = {
            "bid": float(getattr(tick, "bid", 0.0)),
            "ask": float(getattr(tick, "ask", 0.0)),
            "last": float(getattr(tick, "last", 0.0)),
            "time": int(getattr(tick, "time", 0)),
        }
    cp = float(tick_obj.get("bid") or tick_obj.get("last") or 0.0)

    # Short and long horizon tick stats
    tick_stats_5m: dict[str, Any] = {}
    tick_stats_30m: dict[str, Any] = {}
    try:
        now_ts = int(time.time())
        for minutes in (5, 30):
            frm = now_ts - minutes * 60
            ticks = mt5.copy_ticks_range(symbol, frm, now_ts, mt5.COPY_TICKS_INFO)
            if ticks is None or len(ticks) < 5 or not info:
                if minutes == 5:
                    tick_stats_5m = {}
                else:
                    tick_stats_30m = {}
                continue
            spreads: list[int] = []
            for t in ticks:
                b, a = float(t["bid"]), float(t["ask"])  # type: ignore[index]
                if a > 0 and b > 0:
                    spreads.append(int(round((a - b) / (getattr(info, "point", 0.01) or 0.01))))
            med = median(spreads) if spreads else None
            p90 = sorted(spreads)[int(len(spreads) * 0.9)] if spreads else None
            if minutes == 5:
                tick_stats_5m = {"ticks_per_min": int(len(ticks) / 5), "median_spread": med, "p90_spread": p90}
            else:
                tick_stats_30m = {"ticks_per_min": int(len(ticks) / 30), "median_spread": med, "p90_spread": p90}
    except Exception:
        pass

    # OHLCV series
    series = {
        "M1": _series_from_mt5(symbol, mt5.TIMEFRAME_M1, n_m1),
        "M5": _series_from_mt5(symbol, mt5.TIMEFRAME_M5, n_m5),
        "M15": _series_from_mt5(symbol, mt5.TIMEFRAME_M15, n_m15),
        "H1": _series_from_mt5(symbol, mt5.TIMEFRAME_H1, n_h1),
    }

    # Higher timeframe levels
    daily = _hl_from(symbol, mt5.TIMEFRAME_D1, 2) or {}
    prev_day: dict[str, float] | None = None
    try:
        d2 = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_D1, 1, 1)
        if d2 is not None and len(d2) == 1:
            prev_day = {"high": float(d2[0]["high"]), "low": float(d2[0]["low"])}
    except Exception:
        prev_day = None
    weekly = _hl_from(symbol, mt5.TIMEFRAME_W1, 1) or {}
    prev_week: dict[str, float] | None = None
    try:
        w2 = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_W1, 1, 1)
        if w2 is not None and len(w2) == 1:
            prev_week = {"high": float(w2[0]["high"]), "low": float(w2[0]["low"])}
    except Exception:
        prev_week = None
    monthly = _hl_from(symbol, mt5.TIMEFRAME_MN1, 1) or {}

    # Enrich daily
    midnight_open = None
    if series["M1"]:
        for r in series["M1"]:
            if str(r["time"]).endswith("00:00:00"):
                midnight_open = r["open"]
                break
    if daily:
        hi = daily.get("high")
        lo = daily.get("low")
        eq50 = (hi + lo) / 2.0 if (hi and lo) else None
        daily["eq50"] = eq50
        daily["midnight_open"] = midnight_open

    # Sessions and VWAPs
    sessions_today = session_ranges_today(series["M1"]) if series["M1"] else {}
    now_hhmm_for_sessions = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).strftime("%H:%M")
    session_liquidity = ict_analysis.get_session_liquidity(series.get("M15", []), sessions_today, now_hhmm_for_sessions)
    vwap_day = vwap_from_rates([r for r in series["M1"] if str(r["time"])[:10] == datetime.now().strftime("%Y-%m-%d")])
    vwaps: dict[str, float | None] = {"day": vwap_day}
    for sess in ["asia", "london", "newyork_am", "newyork_pm"]:
        rng = sessions_today.get(sess, {})
        sub: list[dict] = []
        if rng and rng.get("start") and rng.get("end"):
            for r in series["M1"]:
                hh = str(r["time"])[11:16]
                if str(r["time"])[:10] == datetime.now().strftime("%Y-%m-%d") and rng["start"] <= hh < rng["end"]:
                    sub.append(r)
        vwaps[sess] = vwap_from_rates(sub) if sub else None

    # Trend refs (EMA) and ATR
    ema_block: dict[str, dict[str, float | None]] = {}
    for k in ["M1", "M5", "M15", "H1"]:
        closes = [float(r["close"]) for r in series.get(k, [])]
        ema_block[k] = {"ema50": ema(closes, 50) if closes else None, "ema200": ema(closes, 200) if closes else None}

    atr_block: dict[str, float | None] = {}
    atr_m5_now, tr_m5 = atr_series(series.get("M5", []), period=14)
    atr_block["M5"] = atr_m5_now
    atr_block["M1"] = atr_series(series.get("M1", []), period=14)[0]
    atr_block["M15"] = atr_series(series.get("M15", []), period=14)[0]
    atr_block["H1"] = atr_series(series.get("H1", []), period=14)[0]

    # Volatility regime: based on EMA M5 separation vs ATR
    vol_regime = None
    try:
        e50 = ema_block["M5"]["ema50"]
        e200 = ema_block["M5"]["ema200"]
        if e50 is not None and e200 is not None and atr_m5_now:
            vol_regime = "trending" if abs(e50 - e200) > (atr_m5_now * 0.2) else "choppy"
    except Exception:
        pass

    # Key levels around cp
    key_near = _nearby_key_levels(cp, info, daily, prev_day)

    # ADR and day position
    adr = adr_stats(symbol, n=20)
    day_open = daily.get("open") if daily else None
    prev_close = None
    try:
        d1_prev_close_arr = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_D1, 1, 1)
        if d1_prev_close_arr is not None and len(d1_prev_close_arr) == 1:
            prev_close = float(d1_prev_close_arr[0]["close"])  # type: ignore[index]
    except Exception:
        pass
    day_range = None
    day_range_pct = None
    if daily and adr and adr.get("d20"):
        if daily.get("high") and daily.get("low"):
            day_range = float(daily["high"]) - float(daily["low"])  # type: ignore[index]
            day_range_pct = (day_range / float(adr["d20"])) * 100.0  # type: ignore[index]

    pos_in_day = None
    try:
        if daily and cp:
            lo = float(daily.get("low", 0.0))
            hi = float(daily.get("high", 0.0))
            if hi > lo:
                pos_in_day = (cp - lo) / (hi - lo)
    except Exception:
        pos_in_day = None

    # Killzone detection using DST-aware VN schedule
    kills = _killzone_ranges_vn()
    now_hhmm = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).strftime("%H:%M")
    is_silver_bullet = ict_analysis.is_silver_bullet_window(now_hhmm, kills)
    kill_active = None
    mins_to_next = None
    try:
        def _mins(t1: str, t2: str) -> int:
            h1, m1 = map(int, t1.split(":"))
            h2, m2 = map(int, t2.split(":"))
            return (h2 - h1) * 60 + (m2 - m1)

        order = ["asia", "london", "newyork_am", "newyork_pm"]
        for k in order:
            kz = kills.get(k)
            if not kz:
                continue
            st, ed = kz["start"], kz["end"]
            if st > ed:  # Handles overnight sessions like NY PM
                if now_hhmm >= st or now_hhmm < ed:
                    kill_active = k
                    break
            elif st <= now_hhmm < ed:
                kill_active = k
                break
        if kill_active is None:
            # Sort session start times to find the next one accurately
            sorted_sessions = sorted(
                [(k, v["start"]) for k, v in kills.items()],
                key=lambda item: item[1]
            )
            for name, start_time in sorted_sessions:
                if now_hhmm < start_time:
                    mins_to_next = _mins(now_hhmm, start_time)
                    break
    except Exception:
        pass

    # Round levels around current price (25/50/75 pip) – optional simple set
    round_levels = []
    try:
        ppp = points_per_pip_from_info(info_obj)
        point = float(info_obj.get("point") or 0.0)
        pip = point * ppp if point else 0.0
        if cp and pip:
            pivots = [int(math.floor((cp / pip))) * pip + (s * pip / 100.0) for s in (0, 25, 50, 75)]
            seen: set[float] = set()
            for price in pivots:
                if price in seen:
                    continue
                seen.add(price)
                dist_pips = abs(cp - price) / (point * ppp)
                round_levels.append(
                    {
                        "level": f"{int(round((price % 1) / pip * 100)) if pip > 0 else 0:02d}",
                        "price": round(price, int(info_obj.get("digits") or 5)),
                        "distance_pips": round(dist_pips, 2),
                    }
                )
    except Exception:
        round_levels = []

    # Normalize spread relative to ATR M5
    spread_points = None
    if tick and info and getattr(info, "point", None):
        b = float(getattr(tick, "bid", 0.0))
        a = float(getattr(tick, "ask", 0.0))
        spread_points = (a - b) / (getattr(info, "point", 0.01) or 0.01) if (a > 0 and b > 0) else None
    atr_norm = {"spread_as_pct_of_atr_m5": None}
    if spread_points and atr_m5_now and atr_m5_now > 0 and getattr(info, "point", None):
        atr_norm["spread_as_pct_of_atr_m5"] = (spread_points / (atr_m5_now / (getattr(info, "point", 0.01) or 0.01))) * 100.0

    # Risk block from plan (optional, minimal)
    risk_model = None
    rr_projection = None
    if plan and info and ppp and (val := value_per_point(symbol, info)):
        try:
            entry = plan.get("entry")
            sl = plan.get("sl")
            tp1 = plan.get("tp1")
            tp2 = plan.get("tp2")
            if entry and sl and tp1 and tp2:
                rr1 = abs(tp1 - entry) / abs(entry - sl) if entry != sl else None
                rr2 = abs(tp2 - entry) / abs(entry - sl) if entry != sl else None
                rr_projection = {"tp1_rr": rr1, "tp2_rr": rr2}
            risk_model = {"value_per_point": val, "points_per_pip": ppp}
        except Exception:
            pass

    # ICT Patterns
    ict_patterns = {}
    try:
        ict_patterns["fvgs_m15"] = ict_analysis.find_fvgs(series.get("M15", []), cp) or {}
        ict_patterns["fvgs_h1"] = ict_analysis.find_fvgs(series.get("H1", []), cp) or {}
        
        liquidity_h1 = ict_analysis.find_liquidity_levels(series.get("H1", [])) or {}
        liquidity_m15 = ict_analysis.find_liquidity_levels(series.get("M15", [])) or {}
        ict_patterns["liquidity_h1"] = liquidity_h1
        ict_patterns["liquidity_m15"] = liquidity_m15
        
        ict_patterns["order_blocks_h1"] = ict_analysis.find_order_blocks(series.get("H1", [])) or {}
        ict_patterns["order_blocks_m15"] = ict_analysis.find_order_blocks(series.get("M15", [])) or {}
        ict_patterns["premium_discount_h1"] = ict_analysis.analyze_premium_discount(series.get("H1", []), cp) or {}
        ict_patterns["premium_discount_m15"] = ict_analysis.analyze_premium_discount(series.get("M15", []), cp) or {}
        
        # MSS/BOS needs liquidity levels as input
        ict_patterns["mss_h1"] = ict_analysis.find_market_structure_shift(series.get("H1", []), liquidity_h1.get("swing_highs_BSL", []), liquidity_h1.get("swing_lows_SSL", []))
        ict_patterns["mss_m15"] = ict_analysis.find_market_structure_shift(series.get("M15", []), liquidity_m15.get("swing_highs_BSL", []), liquidity_m15.get("swing_lows_SSL", []))
        ict_patterns["liquidity_voids_h1"] = ict_analysis.find_liquidity_voids(series.get("H1", [])) or []
        ict_patterns["liquidity_voids_m15"] = ict_analysis.find_liquidity_voids(series.get("M15", [])) or []
    except Exception:
        # If any ICT analysis fails, ensure ict_patterns is an empty dict
        ict_patterns = {}

    payload = {
        "MT5_DATA": {
            "symbol": symbol,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "broker_time": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "account": account_obj or {},
            "positions": positions_list,
            "info": info_obj or {},
            "symbol_rules": rules_obj or {},
            "pip": {
                "points_per_pip": points_per_pip_from_info(info_obj),
                "value_per_point": value_per_point(symbol, info),
                "pip_value_per_lot": (
                    (value_per_point(symbol, info) or 0.0) * points_per_pip_from_info(info_obj)
                ),
            },
            "tick": tick_obj or {},
            "tick_stats_5m": tick_stats_5m or {},
            "tick_stats_30m": tick_stats_30m or {},
            "levels": {
                "daily": daily or {},
                "prev_day": prev_day or {},
                "weekly": weekly or {},
                "prev_week": prev_week or {},
                "monthly": monthly or {},
            },
            "day_open": daily.get("open") if daily else None,
            "prev_day_close": prev_close,
            "adr": adr or {},
            "day_range": day_range,
            "day_range_pct_of_adr20": (float(day_range_pct) if day_range_pct is not None else None),
            "position_in_day_range": (float(pos_in_day) if pos_in_day is not None else None),
            "sessions_today": sessions_today or {},
            "session_liquidity": session_liquidity or {},
            "volatility": {"ATR": atr_block or {}},
            "volatility_regime": vol_regime,
            "trend_refs": {"EMA": ema_block or {}},
            "vwap": vwaps or {},
            "kills": kills or {},
            "is_silver_bullet_window": is_silver_bullet,
            "killzone_active": kill_active,
            "mins_to_next_killzone": mins_to_next,
            "key_levels_nearby": key_near or [],
            "round_levels": round_levels or [],
            "atr_norm": atr_norm or {},
            "ict_patterns": ict_patterns or {},
            "risk_model": risk_model or {},
            "rr_projection": rr_projection or {},
        }
    }

    # Always wrap in SafeMT5Data. The caller can decide to get the raw dict or json.
    safe_data_obj = SafeMT5Data(payload.get("MT5_DATA"))
    
    if return_json:
        try:
            # This path is now less common, but supported for compatibility.
            return json.dumps(payload, ensure_ascii=False)
        except Exception:
            return str(payload)
            
    return safe_data_obj


__all__ = [
    "connect",
    "ensure_initialized",
    "info_get",
    "points_per_pip_from_info",
    "pip_size_from_info",
    "value_per_point",
    "quantiles",
    "ema",
    "atr_series",
    "vwap_from_rates",
    "adr_stats",
    "session_ranges_today",
    "build_context",
]
