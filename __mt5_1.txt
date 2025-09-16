from __future__ import annotations

import json
import math
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from statistics import median
from typing import Any, Iterable, Sequence


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

def _killzone_ranges_vn(d: datetime | None = None, target_tz: str | None = None) -> dict[str, dict[str, str]]:
    """
    Build London/NY killzones in Vietnam time (Asia/Ho_Chi_Minh),
    converting from local market times with DST handled via zoneinfo.
    - London: 08:00–11:00 Europe/London (local)
    - New York (pre): 08:30–11:00 America/New_York (local)
    - New York (post): 13:30–16:00 America/New_York (local)
    Returns dict of {name: {start: HH:MM, end: HH:MM}}
    """
    tz_vn = ZoneInfo(target_tz or "Asia/Ho_Chi_Minh")
    tz_uk = ZoneInfo("Europe/London")
    tz_us = ZoneInfo("America/New_York")
    if d is None:
        d = datetime.now(tz=tz_vn)

    def _fmt(dt_local_tzaware: datetime) -> str:
        return dt_local_tzaware.astimezone(tz_vn).strftime("%H:%M")

    def _local_range(tz, h0, m0, h1, m1):
        s = datetime(d.year, d.month, d.day, h0, m0, tzinfo=tz)
        e = datetime(d.year, d.month, d.day, h1, m1, tzinfo=tz)
        return _fmt(s), _fmt(e)

    l_st, l_ed = _local_range(tz_uk, 8, 0, 11, 0)
    ny_pre_st, ny_pre_ed = _local_range(tz_us, 8, 30, 11, 0)
    ny_post_st, ny_post_ed = _local_range(tz_us, 13, 30, 16, 0)

    return {
        "london": {"start": l_st, "end": l_ed},
        "newyork_pre": {"start": ny_pre_st, "end": ny_pre_ed},
        "newyork_post": {"start": ny_post_st, "end": ny_post_ed},
    }


def session_ranges_today(m1_rates: Sequence[dict] | None) -> dict[str, dict]:
    """
