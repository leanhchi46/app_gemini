from __future__ import annotations

import json
import logging
import math
import time
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import TYPE_CHECKING, Any, Dict, Iterable, Optional, Sequence, cast
from zoneinfo import ZoneInfo

import MetaTrader5 as mt5_lib

# Assign mt5_lib to a new variable typed as Any to suppress pyright errors
mt5: Any = mt5_lib

from APP.analysis import ict_analyzer
from APP.analysis.ict_analyzer import LiquidityLevel
from APP.utils.safe_data import SafeData

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from APP.configs.app_config import MT5Config, RunConfig


# ------------------------------
# MT5 connection helpers
# ------------------------------


def connect(path: str | None = None) -> tuple[bool, str | None]:
    """
    Initialize connection to MetaTrader5 terminal.

    Returns (ok, error_message). On success, error_message is None.
    """
    logger.debug(f"Bắt đầu connect MT5. Path: {path}")
    if mt5 is None:
        logger.error("MetaTrader5 module not installed.")
        return False, "MetaTrader5 module not installed (pip install MetaTrader5)"
    try:
        ok = mt5.initialize(path=path) if path else mt5.initialize()
        if not ok:
            err_code = mt5.last_error()
            logger.error(f"mt5.initialize() failed with code {err_code}")
            return False, f"initialize() failed: {err_code}"
        logger.info("Kết nối MT5 thành công.")
        return True, None
    except Exception as e:
        logger.exception("MT5 connect generated an exception")
        return False, f"MT5 connect error: {e}"
    finally:
        logger.debug("Kết thúc connect MT5.")


def ensure_initialized(path: str | None = None) -> bool:
    """Ensure MT5 is ready. Returns True if ready."""
    logger.debug(f"Bắt đầu ensure_initialized. Path: {path}")
    ok, _ = connect(path)
    logger.debug(f"Kết thúc ensure_initialized. Kết quả: {ok}")
    return ok


def get_all_symbols() -> list[str]:
    """
    Lấy danh sách tên của tất cả các symbol có sẵn.
    """
    logger.debug("Bắt đầu get_all_symbols.")
    if not ensure_initialized():
        logger.warning("MT5 chưa được khởi tạo, không thể lấy danh sách symbol.")
        return []
    try:
        symbols = mt5.symbols_get()
        if symbols:
            names = sorted([s.name for s in symbols])
            logger.debug(f"Đã lấy được {len(names)} symbols.")
            return names
        logger.warning("Không lấy được symbol nào từ mt5.symbols_get().")
        return []
    except Exception as e:
        logger.exception(f"Lỗi khi lấy danh sách symbol: {e}")
        return []


# ------------------------------
# Price unit helpers
# ------------------------------


def points_per_pip_from_info(info: dict | Any) -> int:
    """
    Infer points-per-pip from symbol info.
    Accepts either a dict or an mt5.symbol_info(...) object.
    """
    logger.debug(f"Bắt đầu points_per_pip_from_info cho info: {info}")
    try:
        digits = (
            info.get("digits")
            if isinstance(info, dict)
            else getattr(info, "digits", None)
        ) or 0
        digits = int(digits)
    except Exception as e:
        digits = 0
        logger.warning(f"Lỗi khi lấy digits từ info: {e}, đặt mặc định là 0.")
    result = 10 if digits >= 3 else 1
    logger.debug(f"Kết thúc points_per_pip_from_info. Digits: {digits}, PPP: {result}")
    return result


def pip_size_from_info(info: dict | Any) -> float:
    logger.debug(f"Bắt đầu pip_size_from_info cho info: {info}")
    point = (
        info.get("point") if isinstance(info, dict) else getattr(info, "point", None)
    ) or 0.0
    try:
        point = float(point)
    except Exception as e:
        point = 0.0
        logger.warning(f"Lỗi khi lấy point từ info: {e}, đặt mặc định là 0.0.")
    ppp = points_per_pip_from_info(info)
    result = point * ppp if point else 0.0
    logger.debug(f"Kết thúc pip_size_from_info. Point: {point}, PPP: {ppp}, Pip Size: {result}")
    return result


def points_to_pips(points: float, info: dict | Any) -> float | None:
    """Chuyển đổi giá trị từ point sang pip."""
    ppp = points_per_pip_from_info(info)
    if ppp == 0:
        return None
    return points / ppp


def get_spread_pips(info: dict | Any, tick: dict | Any) -> float | None:
    """Lấy spread hiện tại và chuyển đổi sang pip."""
    spread_points = info_get(info, "spread_current")
    if spread_points is None:
        # Fallback for brokers that don't provide spread in symbol_info
        bid = info_get(tick, "bid", 0.0)
        ask = info_get(tick, "ask", 0.0)
        point = info_get(info, "point", 0.0)
        if bid > 0 and ask > 0 and point > 0:
            spread_points = (ask - bid) / point
        else:
            return None
    return points_to_pips(float(spread_points), info)


def info_get(info: dict | Any, key: str, default: Any = None) -> Any:
    """
    Safe accessor for MT5 info/account-like objects that may be dicts or
    MetaTrader5 structs. Handles a few common key name differences.

    Examples:
    - info_get(info, "digits")
    - info_get(info, "contract_size") -> maps to attr "trade_contract_size" on objects
    - info_get(info, "spread_current") -> maps to attr "spread" on objects
    """
    logger.debug(f"Bắt đầu info_get cho key: {key}, default: {default}")
    if info is None:
        logger.debug("Info object trống, trả về default.")
        return default
    if isinstance(info, dict):
        result = info.get(key, default)
        logger.debug(f"Tìm thấy key '{key}' trong dict. Giá trị: {result}")
        return result
    # Map commonly renamed fields from our JSON schema back to MT5 attributes
    attr_map = {
        "contract_size": "trade_contract_size",
        "spread_current": "spread",
        "stop_level_points": "trade_stops_level",
        "freeze_level_points": "trade_freeze_level",
    }
    attr = attr_map.get(key, key)
    result = getattr(info, attr, default)
    logger.debug(f"Tìm thấy attribute '{attr}' trong object. Giá trị: {result}")
    return result


def value_per_point(symbol: str, info_obj: Any | None = None) -> float | None:
    """
    Best-effort estimation of 1-point value per 1.00 lot for `symbol`.
    Tries broker-provided tick value/size, falls back to order_calc_profit, then contract size.
    """
    logger.debug(f"Bắt đầu value_per_point cho symbol: {symbol}")
    if mt5 is None:
        logger.warning("MetaTrader5 module not installed, cannot get value_per_point.")
        return None
    try:
        info_obj = info_obj or mt5.symbol_info(symbol)
        if not info_obj:
            logger.warning(f"Không tìm thấy thông tin symbol cho {symbol}.")
            return None

        point = float(getattr(info_obj, "point", 0.0) or 0.0)
        if point <= 0:
            logger.debug("Point size <= 0, không thể tính value_per_point.")
            return None

        tick_value = float(getattr(info_obj, "trade_tick_value", 0.0) or 0.0)
        tick_size = float(getattr(info_obj, "trade_tick_size", 0.0) or 0.0)
        if tick_value > 0 and tick_size > 0:
            result = tick_value * (point / tick_size)
            logger.debug(f"Tính value_per_point từ tick_value/tick_size: {result}")
            return result

        try:
            tick = mt5.symbol_info_tick(symbol)
            mid = None
            if tick:
                bid = float(getattr(tick, "bid", 0.0) or 0.0)
                ask = float(getattr(tick, "ask", 0.0) or 0.0)
                mid = (bid + ask) / 2.0 if (bid and ask) else (ask or bid)
            if mid and point > 0:
                pr = mt5.order_calc_profit(
                    mt5.ORDER_TYPE_BUY, symbol, 1.0, mid, mid + point
                )
                if isinstance(pr, (int, float)):
                    result = abs(float(pr))
                    logger.debug(f"Tính value_per_point từ order_calc_profit: {result}")
                    return result
        except Exception as e:
            logger.debug(f"Lỗi khi tính value_per_point từ order_calc_profit: {e}")
            pass

        csize = float(getattr(info_obj, "trade_contract_size", 0.0) or 0.0)
        if csize > 0:
            result = csize * point
            logger.debug(f"Tính value_per_point từ contract_size: {result}")
            return result
        logger.debug("Không thể tính value_per_point, trả về None.")
        return None
    except Exception as e:
        logger.error(f"Lỗi ngoại lệ trong value_per_point: {e}")
        return None


# ------------------------------
# Math/stat helpers
# ------------------------------


def quantiles(
    vals: Sequence[float] | None, q_list: Iterable[float]
) -> dict[float, float | None]:
    logger.debug(f"Bắt đầu quantiles cho {len(vals) if vals else 0} giá trị, q_list: {q_list}")
    if not vals:
        logger.debug("Vals trống, trả về quantiles None.")
        return {q: None for q in q_list}
    arr = sorted(vals)
    out: dict[float, float | None] = {}
    for q in q_list:
        if q <= 0:
            out[q] = arr[0]
            logger.debug(f"Quantile {q}: {arr[0]}")
            continue
        if q >= 1:
            out[q] = arr[-1]
            logger.debug(f"Quantile {q}: {arr[-1]}")
            continue
        pos = (len(arr) - 1) * q
        lo = int(math.floor(pos))
        hi = int(math.ceil(pos))
        if lo == hi:
            out[q] = arr[lo]
        else:
            out[q] = arr[lo] + (arr[hi] - arr[lo]) * (pos - lo)
        logger.debug(f"Quantile {q}: {out[q]}")
    logger.debug("Kết thúc quantiles.")
    return out


def ema(values: Sequence[float] | None, period: int) -> float | None:
    logger.debug(f"Bắt đầu ema cho {len(values) if values else 0} giá trị, period: {period}")
    if not values or period <= 1:
        logger.debug("Không đủ giá trị hoặc period <= 1, không thể tính EMA.")
        return None
    alpha = 2.0 / (period + 1.0)
    e = values[0]
    for v in values[1:]:
        e = alpha * v + (1 - alpha) * e
    try:
        result = float(e)
        logger.debug(f"Kết thúc ema. EMA: {result}")
        return result
    except Exception as e:
        logger.error(f"Lỗi khi tính EMA: {e}")
        return None


def atr_series(
    rates: Sequence[dict] | None, period: int = 14
) -> tuple[float | None, list[float]]:
    """
    rates: list of {high, low, close}
    Returns (atr_last, list_of_TRs)
    """
    logger.debug(f"Bắt đầu atr_series cho {len(rates) if rates else 0} rates, period: {period}")
    if not rates or len(rates) < period + 1:
        logger.debug("Không đủ rates để tính ATR.")
        return None, []
    trs: list[float] = []
    prev_close = float(rates[0]["close"])  # type: ignore[index]
    for r in rates[1:]:
        hi = float(r["high"])  # type: ignore[index]
        lo = float(r["low"])  # type: ignore[index]
        pc = float(prev_close)
        tr = max(hi - lo, abs(hi - pc), abs(lo - pc))
        trs.append(tr)
        prev_close = float(r["close"])  # type: ignore[index]
    if len(trs) < period:
        logger.debug("Không đủ TRs để tính ATR ban đầu.")
        return None, trs
    alpha = 1.0 / period
    atr = sum(trs[:period]) / period
    out = [atr]
    for tr in trs[period:]:
        atr = (1 - alpha) * atr + alpha * tr
        out.append(atr)
    result = (out[-1] if out else None), trs
    logger.debug(f"Kết thúc atr_series. Last ATR: {result[0]}, TRs count: {len(result[1])}")
    return result


def vwap_from_rates(rates: Sequence[dict] | None) -> float | None:
    logger.debug(f"Bắt đầu vwap_from_rates cho {len(rates) if rates else 0} rates.")
    if not rates:
        logger.debug("Rates trống, không thể tính VWAP.")
        return None
    s_pv = 0.0
    s_v = 0.0
    for r in rates:
        tp = (float(r["high"]) + float(r["low"]) + float(r["close"])) / 3.0  # type: ignore[index]
        v = max(1, int(r.get("vol", 0)))
        s_pv += tp * v
        s_v += v
    result = s_pv / s_v if s_v > 0 else None
    logger.debug(f"Kết thúc vwap_from_rates. VWAP: {result}")
    return result


def adr_stats(symbol: str, n: int = 20) -> dict[str, float | None] | None:
    """Average Daily Range stats for last n days (d5/d10/d20)."""
    logger.debug(f"Bắt đầu adr_stats cho symbol: {symbol}, n: {n}")
    if mt5 is None:
        logger.warning("MetaTrader5 module not installed, cannot get adr_stats.")
        return None
    bars = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_D1, 0, max(25, n + 2))
    if bars is None or len(bars) < 5:
        logger.warning(f"Không đủ dữ liệu D1 để tính adr_stats cho {symbol}.")
        return None
    ranges = [float(b["high"] - b["low"]) for b in bars[-(n + 1) : -1]]
    if not ranges:
        logger.debug("Không có ranges để tính adr_stats.")
        return None

    def _avg(m: int) -> float | None:
        return sum(ranges[-m:]) / max(1, m) if len(ranges) >= m else None

    result = {"d5": _avg(5), "d10": _avg(10), "d20": _avg(20)}
    logger.debug(f"Kết thúc adr_stats. Kết quả: {result}")
    return result


# ------------------------------
# Time/session helpers
# ------------------------------


def _is_us_dst(d: datetime) -> bool:
    """Checks if a given date is within US Daylight Saving Time."""
    logger.debug(f"Bắt đầu _is_us_dst cho ngày: {d}")
    if not isinstance(d, datetime):
        logger.debug("D không phải datetime object, trả về False.")
        return False
    # DST starts on the second Sunday in March at 2 AM
    march_first = datetime(d.year, 3, 1)
    # Day of week: Monday is 0 and Sunday is 6.
    march_second_sunday = march_first + timedelta(
        days=(6 - march_first.weekday() + 7) % 7 + 7
    )

    # DST ends on the first Sunday in November at 2 AM
    nov_first = datetime(d.year, 11, 1)
    nov_first_sunday = nov_first + timedelta(days=(6 - nov_first.weekday() + 7) % 7)

    # Create timezone-naive datetime objects for comparison
    check_date = datetime(d.year, d.month, d.day)
    result = march_second_sunday <= check_date < nov_first_sunday
    logger.debug(f"Kết thúc _is_us_dst. Ngày {d} trong DST: {result}")
    return result


def _killzone_ranges_vn(
    d: datetime | None = None, target_tz: str | None = None
) -> dict[str, dict[str, str]]:
    """
    Build London/NY killzones in Vietnam time based on US DST.
    """
    logger.debug(f"Bắt đầu _killzone_ranges_vn. Date: {d}, Target TZ: {target_tz}")
    if d is None:
        tz_vn = ZoneInfo(target_tz or "Asia/Ho_Chi_Minh")
        d = datetime.now(tz=tz_vn)
        logger.debug(f"Sử dụng thời gian hiện tại ở TZ: {tz_vn}, Date: {d}")

    is_summer = _is_us_dst(d)
    logger.debug(f"Is US DST (summer): {is_summer}")

    asia_session = {"start": "06:00", "end": "09:00"}
    if is_summer:
        # Mùa hè (Tháng 3 – Tháng 11, US DST)
        result = {
            "asia": asia_session,
            "london": {"start": "14:00", "end": "17:00"},
            "newyork_am": {"start": "19:30", "end": "22:00"},
            "newyork_pm": {"start": "00:00", "end": "03:00"},
        }
        logger.debug("Đã tạo killzone ranges cho mùa hè.")
        return result
    else:
        # Mùa đông (Tháng 11 – Tháng 3, US Standard Time)
        result = {
            "asia": asia_session,
            "london": {"start": "15:00", "end": "18:00"},
            "newyork_am": {"start": "20:30", "end": "23:00"},
            "newyork_pm": {"start": "01:00", "end": "04:00"},
        }
        logger.debug("Đã tạo killzone ranges cho mùa đông.")
        return result


def session_ranges_today(m1_rates: Sequence[dict] | None) -> dict[str, dict]:
    """
    Compute session ranges for Asia/London/NY (split NY into AM/PM) in local VN time.
    Input: M1 rates with keys {time:"YYYY-MM-DD HH:MM:SS", high, low, close, vol}.
    """
    logger.debug(f"Bắt đầu session_ranges_today. M1 rates count: {len(m1_rates) if m1_rates else 0}")
    # The m1_rates are not strictly needed anymore since we use system time,
    # but we keep the signature for compatibility. It can be used to check historical sessions.
    # For now, we pass `None` to `_killzone_ranges_vn` to use the current system time.
    result = _killzone_ranges_vn(d=None)
    logger.debug("Kết thúc session_ranges_today.")
    return result


def get_active_killzone(d: datetime, target_tz: str | None) -> tuple[bool, str | None]:
    """
    Kiểm tra xem thời gian đã cho có nằm trong bất kỳ killzone nào không.
    Trả về (is_in_zone, zone_name).
    """
    logger.debug(f"Bắt đầu get_active_killzone cho {d} với timezone {target_tz}")
    try:
        tz = ZoneInfo(target_tz or "Asia/Ho_Chi_Minh")
        # Nếu d không có timezone, gán timezone cho nó
        if d.tzinfo is None:
            d = d.replace(tzinfo=tz)
        else:
            d = d.astimezone(tz)
        
        now_hhmm = d.strftime("%H:%M")
        
        kills = _killzone_ranges_vn(d=d)
        
        order = ["asia", "london", "newyork_am", "newyork_pm"]
        for k in order:
            kz = kills.get(k)
            if not kz:
                continue
            st, ed = kz["start"], kz["end"]
            if st > ed:  # Xử lý các phiên qua đêm như NY PM
                if now_hhmm >= st or now_hhmm < ed:
                    logger.debug(f"Đang trong killzone {k}")
                    return True, k
            elif st <= now_hhmm < ed:
                logger.debug(f"Đang trong killzone {k}")
                return True, k
                
        logger.debug("Không trong killzone nào.")
        return False, None
    except Exception:
        logger.exception("Lỗi khi xác định killzone đang hoạt động.")
        return False, None


def _series_from_mt5(symbol: str, tf_code: int, bars: int) -> list[dict]:
    logger.debug(f"Bắt đầu _series_from_mt5 cho symbol: {symbol}, tf_code: {tf_code}, bars: {bars}")
    arr = (
        mt5.copy_rates_from_pos(symbol, tf_code, 0, max(50, int(bars))) if mt5 else None
    )
    rows: list[dict] = []
    if arr is not None:
        for r in arr:
            rows.append(
                {
                    "time": datetime.fromtimestamp(int(r["time"])).strftime(
                        "%Y-%m-%d %H:%M:%S"
                    ),
                    "open": float(r["open"]),
                    "high": float(r["high"]),
                    "low": float(r["low"]),
                    "close": float(r["close"]),
                    "vol": int(r["tick_volume"]),
                }
            )
        logger.debug(f"Đã lấy {len(rows)} bars cho {symbol} {tf_code}.")
    else:
        logger.warning(f"Không lấy được rates từ MT5 cho {symbol} {tf_code}.")
    logger.debug("Kết thúc _series_from_mt5.")
    return rows


def _hl_from(symbol: str, tf_code: int, bars: int) -> dict | None:
    logger.debug(f"Bắt đầu _hl_from cho symbol: {symbol}, tf_code: {tf_code}, bars: {bars}")
    data = mt5.copy_rates_from_pos(symbol, tf_code, 0, bars) if mt5 else None
    if data is None or len(data) == 0:
        logger.warning(f"Không lấy được dữ liệu HL từ MT5 cho {symbol} {tf_code}.")
        return None
    
    try:
        hi = max([float(x["high"]) for x in data])
        lo = min([float(x["low"]) for x in data])
        op = float(data[0]["open"])  # first bar open
        result = {"open": op, "high": hi, "low": lo}
        logger.debug(f"Đã lấy HL từ MT5 cho {symbol} {tf_code}. Kết quả: {result}")
        return result
    except Exception as e:
        logger.error(f"Lỗi khi xử lý dữ liệu HL từ MT5 cho {symbol} {tf_code}: {e}")
        return None


def _nearby_key_levels(
    cp: float, info: Any, daily: dict | None, prev_day: dict | None
) -> list[dict]:
    logger.debug(f"Bắt đầu _nearby_key_levels cho cp: {cp}, daily: {daily}, prev_day: {prev_day}")
    lv: list[dict] = []
    if prev_day:
        if "high" in prev_day:
            lv.append({"name": "PDH", "price": float(prev_day["high"])})
            logger.debug(f"Thêm PDH: {prev_day['high']}")
        if "low" in prev_day:
            lv.append({"name": "PDL", "price": float(prev_day["low"])})
            logger.debug(f"Thêm PDL: {prev_day['low']}")
    if daily:
        if daily.get("eq50") is not None:
            lv.append({"name": "EQ50_D", "price": float(daily["eq50"])})
            logger.debug(f"Thêm EQ50_D: {daily['eq50']}")
        if daily.get("open") is not None:
            lv.append({"name": "DO", "price": float(daily["open"])})
            logger.debug(f"Thêm DO: {daily['open']}")

    out = []
    point = float(getattr(info, "point", 0.0) or 0.0)
    for x in lv:
        rel = "ABOVE" if x["price"] > cp else ("BELOW" if x["price"] < cp else "INSIDE")
        dist = abs(x["price"] - cp) / (point or 0.01) if cp and point else None
        out.append(
            {
                "name": x["name"],
                "price": x["price"],
                "relation": rel,
                "distance_pips": dist,
            }
        )
        logger.debug(f"Key level: {x['name']}, Price: {x['price']}, Relation: {rel}, Distance: {dist}")
    logger.debug(f"Kết thúc _nearby_key_levels. Số key levels: {len(out)}")
    return out


def get_market_data(
    cfg: "MT5Config",
    *,
    return_json: bool = False,
    plan: dict | None = None,
) -> SafeData | str:
    symbol = cfg.symbol
    """
    Fetches MT5 data + computes helpers used by the app.
    Returns a JSON string (default) containing a single object with key MT5_DATA.
    """
    logger.debug(f"Bắt đầu build_context cho symbol: {symbol}")
    if mt5 is None:
        logger.warning("MetaTrader5 module not installed, cannot build MT5 context.")
        return SafeData(None)

    info = mt5.symbol_info(symbol)
    if not info:
        logger.warning(f"Không tìm thấy thông tin symbol cho {symbol}.")
        return SafeData(None)
    if not getattr(info, "visible", True):
        try:
            mt5.symbol_select(symbol, True)
            logger.debug(f"Đã chọn symbol '{symbol}' để hiển thị.")
        except Exception as e:
            logger.warning(f"Lỗi khi chọn symbol '{symbol}': {e}")
            pass
    acc = mt5.account_info()
    tick = mt5.symbol_info_tick(symbol)
    logger.debug("Đã lấy symbol info, account info, tick info.")

    # --- Broker Time ---
    broker_time = datetime.now(timezone.utc) # Fallback
    try:
        if tick and getattr(tick, "time", 0) > 0:
            broker_timestamp = int(getattr(tick, "time"))
            terminal_info = mt5.terminal_info()
            if terminal_info:
                broker_timezone = ZoneInfo(terminal_info.timezone)
                broker_time = datetime.fromtimestamp(broker_timestamp, tz=broker_timezone)
    except Exception as e:
        logger.warning(f"Không thể xác định thời gian broker chính xác, sử dụng UTC. Lỗi: {e}")


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
            logger.debug(f"Đã lấy {len(positions_list)} lệnh đang mở.")
    except Exception as e:
        logger.error(f"Lỗi khi lấy lệnh đang mở: {e}")
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
    logger.debug("Đã xây dựng info_obj, account_obj, rules_obj.")

    tick_obj: dict[str, Any] = {}
    if tick:
        tick_obj = {
            "bid": float(getattr(tick, "bid", 0.0)),
            "ask": float(getattr(tick, "ask", 0.0)),
            "last": float(getattr(tick, "last", 0.0)),
            "time": int(getattr(tick, "time", 0)),
        }
    cp = float(tick_obj.get("bid") or tick_obj.get("last") or 0.0)
    logger.debug(f"Current price (cp): {cp}")

    # Short and long horizon tick stats
    tick_stats_5m: dict[str, Any] = {}
    tick_stats_30m: dict[str, Any] = {}
    try:
        now_ts = int(time.time())
        for minutes in (5, 30):
            frm = now_ts - minutes * 60
            ticks = mt5.copy_ticks_range(symbol, frm, now_ts, mt5.COPY_TICKS_INFO)
            if ticks is None or len(ticks) < 5 or not info:
                logger.warning(f"Không đủ dữ liệu tick cho {minutes}m để tính tick stats.")
                if minutes == 5:
                    tick_stats_5m = {}
                else:
                    tick_stats_30m = {}
                continue
            spreads: list[int] = []
            for t in ticks:
                b, a = float(t["bid"]), float(t["ask"])  # type: ignore[index]
                if a > 0 and b > 0:
                    spreads.append(
                        int(round((a - b) / (getattr(info, "point", 0.01) or 0.01)))
                    )
            med = median(spreads) if spreads else None
            p90 = sorted(spreads)[int(len(spreads) * 0.9)] if spreads else None
            if minutes == 5:
                tick_stats_5m = {
                    "ticks_per_min": int(len(ticks) / 5),
                    "median_spread": med,
                    "p90_spread": p90,
                }
                logger.debug(f"Tick stats 5m: {tick_stats_5m}")
            else:
                tick_stats_30m = {
                    "ticks_per_min": int(len(ticks) / 30),
                    "median_spread": med,
                    "p90_spread": p90,
                }
                logger.debug(f"Tick stats 30m: {tick_stats_30m}")
    except Exception as e:
        logger.error(f"Lỗi khi tính tick stats: {e}")
        pass

    # OHLCV series
    series = {
        "M1": _series_from_mt5(symbol, mt5.TIMEFRAME_M1, cfg.n_M1),
        "M5": _series_from_mt5(symbol, mt5.TIMEFRAME_M5, cfg.n_M5),
        "M15": _series_from_mt5(symbol, mt5.TIMEFRAME_M15, cfg.n_M15),
        "H1": _series_from_mt5(symbol, mt5.TIMEFRAME_H1, cfg.n_H1),
    }
    logger.debug("Đã lấy OHLCV series cho các khung thời gian.")

    # Higher timeframe levels
    daily = _hl_from(symbol, mt5.TIMEFRAME_D1, 2) or {}
    prev_day: dict[str, float] | None = None
    try:
        d2 = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_D1, 1, 1)
        if d2 is not None and len(d2) == 1:
            prev_day = {"high": float(d2[0]["high"]), "low": float(d2[0]["low"])}
            logger.debug(f"Đã lấy prev_day HL: {prev_day}")
    except Exception as e:
        prev_day = None
        logger.warning(f"Lỗi khi lấy prev_day HL: {e}")
    weekly = _hl_from(symbol, mt5.TIMEFRAME_W1, 1) or {}
    prev_week: dict[str, float] | None = None
    try:
        w2 = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_W1, 1, 1)
        if w2 is not None and len(w2) == 1:
            prev_week = {"high": float(w2[0]["high"]), "low": float(w2[0]["low"])}
            logger.debug(f"Đã lấy prev_week HL: {prev_week}")
    except Exception as e:
        prev_week = None
        logger.warning(f"Lỗi khi lấy prev_week HL: {e}")
    monthly = _hl_from(symbol, mt5.TIMEFRAME_MN1, 1) or {}
    logger.debug("Đã lấy higher timeframe levels.")

    # Enrich daily
    midnight_open = None
    if series["M1"]:
        for r in series["M1"]:
            if str(r["time"]).endswith("00:00:00"):
                midnight_open = r["open"]
                logger.debug(f"Midnight open: {midnight_open}")
                break
    if daily:
        hi = daily.get("high")
        lo = daily.get("low")
        eq50_val: Optional[float] = None
        if hi is not None and lo is not None:
            eq50_val = (float(hi) + float(lo)) / 2.0
        daily.update({
            "eq50": eq50_val,
            "midnight_open": midnight_open
        })
        logger.debug(f"Đã enrich daily data: {daily}")

    # Sessions and VWAPs
    sessions_today = session_ranges_today(series["M1"]) if series["M1"] else {}
    session_liquidity = ict_analyzer.get_session_liquidity(
        series.get("M15", []), sessions_today, broker_time
    )
    vwap_day = vwap_from_rates(
        [
            r
            for r in series["M1"]
            if str(r["time"])[:10] == datetime.now().strftime("%Y-%m-%d")
        ]
    )
    vwaps: dict[str, float | None] = {"day": vwap_day}
    for sess in ["asia", "london", "newyork_am", "newyork_pm"]:
        rng = sessions_today.get(sess)
        sub: list[dict] = []
        if rng and rng.get("start") and rng.get("end"):
            for r in series["M1"]:
                hh = str(r["time"])[11:16]
                if (
                    str(r["time"])[:10] == datetime.now().strftime("%Y-%m-%d")
                    and rng["start"] <= hh < rng["end"]
                ):
                    sub.append(r)
        vwaps[sess] = vwap_from_rates(sub) if sub else None
    logger.debug(f"Đã tính toán sessions, session liquidity và VWAPs: {vwaps}")

    # Trend refs (EMA) and ATR
    ema_block: dict[str, dict[str, float | None]] = {}
    for k in ["M1", "M5", "M15", "H1"]:
        closes = [float(r["close"]) for r in series.get(k, [])]
        ema_block[k] = {
            "ema50": ema(closes, 50) if closes else None,
            "ema200": ema(closes, 200) if closes else None,
        }
    logger.debug(f"Đã tính toán EMA: {ema_block}")

    atr_block: dict[str, float | None] = {}
    atr_m5_now, tr_m5 = atr_series(series.get("M5", []), period=14)
    atr_block["M5"] = atr_m5_now
    atr_block["M1"] = atr_series(series.get("M1", []), period=14)[0]
    atr_block["M15"] = atr_series(series.get("M15", []), period=14)[0]
    atr_block["H1"] = atr_series(series.get("H1", []), period=14)[0]
    logger.debug(f"Đã tính toán ATR: {atr_block}")

    # Volatility regime: based on EMA M5 separation vs ATR
    vol_regime = None
    try:
        e50 = ema_block["M5"]["ema50"]
        e200 = ema_block["M5"]["ema200"]
        if e50 is not None and e200 is not None and atr_m5_now:
            vol_regime = (
                "trending" if abs(e50 - e200) > (atr_m5_now * 0.2) else "choppy"
            )
        logger.debug(f"Volatility regime: {vol_regime}")
    except Exception as e:
        logger.warning(f"Lỗi khi xác định volatility regime: {e}")
        pass

    # Key levels around cp
    key_near = _nearby_key_levels(cp, info, daily, prev_day)
    logger.debug(f"Key levels nearby: {key_near}")

    # ADR and day position
    adr = adr_stats(symbol, n=20)
    # day_open = daily.get("open") if daily else None
    prev_close = None
    try:
        d1_prev_close_arr = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_D1, 1, 1)
        if d1_prev_close_arr is not None and len(d1_prev_close_arr) == 1:
            prev_close = float(d1_prev_close_arr[0]["close"])  # type: ignore[index]
            logger.debug(f"Prev day close: {prev_close}")
    except Exception as e:
        prev_close = None
        logger.warning(f"Lỗi khi lấy prev_close: {e}")
        pass
    day_range = None
    day_range_pct = None
    if daily and adr and adr.get("d20"):
        if daily.get("high") and daily.get("low"):
            day_range = float(daily["high"]) - float(daily["low"])  # type: ignore[index]
            day_range_pct = (day_range / float(adr["d20"])) * 100.0  # type: ignore[index]
            logger.debug(f"Day range: {day_range}, Day range % of ADR20: {day_range_pct}")

    pos_in_day = None
    try:
        if daily and cp:
            lo = float(daily.get("low", 0.0))
            hi = float(daily.get("high", 0.0))
            if hi > lo:
                pos_in_day = (cp - lo) / (hi - lo)
        logger.debug(f"Position in day range: {pos_in_day}")
    except Exception as e:
        pos_in_day = None
        logger.warning(f"Lỗi khi tính position in day range: {e}")
        pass

    # Killzone detection using DST-aware VN schedule
    kills = _killzone_ranges_vn()
    is_silver_bullet = ict_analyzer.is_silver_bullet_window(broker_time, kills)
    now_hhmm = broker_time.strftime("%H:%M")
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
                [(k, v["start"]) for k, v in kills.items()], key=lambda item: item[1]
            )
            for name, start_time in sorted_sessions:
                if now_hhmm < start_time:
                    mins_to_next = _mins(now_hhmm, start_time)
                    break
        logger.debug(f"Killzone active: {kill_active}, Mins to next killzone: {mins_to_next}")
    except Exception as e:
        logger.error(f"Lỗi khi phát hiện killzone: {e}")
        pass

    # Round levels around current price (25/50/75 pip) – optional simple set
    round_levels = []
    try:
        ppp = points_per_pip_from_info(info_obj)
        point = float(info_obj.get("point") or 0.0)
        pip = point * ppp if point else 0.0
        if cp and pip:
            pivots = [
                int(math.floor((cp / pip))) * pip + (s * pip / 100.0)
                for s in (0, 25, 50, 75)
            ]
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
        logger.debug(f"Round levels: {round_levels}")
    except Exception as e:
        round_levels = []
        logger.error(f"Lỗi khi tính toán round levels: {e}")

    # Normalize spread relative to ATR M5
    spread_points = None
    if tick and info and getattr(info, "point", None):
        b = float(getattr(tick, "bid", 0.0))
        a = float(getattr(tick, "ask", 0.0))
        spread_points = (
            (a - b) / (getattr(info, "point", 0.01) or 0.01)
            if (a > 0 and b > 0)
            else None
        )
    atr_norm: dict[str, float | None] = {"spread_as_pct_of_atr_m5": None}
    if spread_points and atr_m5_now and atr_m5_now > 0 and getattr(info, "point", None):
        atr_norm["spread_as_pct_of_atr_m5"] = (
            spread_points / (atr_m5_now / (getattr(info, "point", 0.01) or 0.01))
        ) * 100.0
    logger.debug(f"ATR normalized spread: {atr_norm}")

    # Risk block from plan (optional, minimal)
    risk_model = None
    rr_projection = None
    ppp = points_per_pip_from_info(info_obj)
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
            logger.debug(f"Risk model: {risk_model}, RR projection: {rr_projection}")
        except Exception as e:
            logger.error(f"Lỗi khi xây dựng risk model/RR projection từ plan: {e}")
            pass

    # ICT Patterns
    ict_patterns = {}
    try:
        timeframes_to_analyze = {"h1": "H1", "m15": "M15", "m5": "M5", "m1": "M1"}
        for tf_key, tf_name in timeframes_to_analyze.items():
            tf_series = series.get(tf_name, [])
            if not tf_series:
                continue

            # 1. Liquidity Levels (nền tảng cho các phân tích khác)
            liquidity_data = ict_analyzer.find_liquidity_levels(tf_series)
            swing_highs: list[LiquidityLevel] = liquidity_data.get("swing_highs_BSL", [])
            swing_lows: list[LiquidityLevel] = liquidity_data.get("swing_lows_SSL", [])
            ict_patterns[f"liquidity_{tf_key}"] = {
                "swing_highs_BSL": [asdict(h) for h in swing_highs],
                "swing_lows_SSL": [asdict(l) for l in swing_lows],
            }

            # 2. Các mẫu hình ICT khác
            fvgs = ict_analyzer.find_fvgs(tf_series, cp)
            ict_patterns[f"fvgs_{tf_key}"] = [asdict(fvg) for fvg in fvgs]

            order_blocks = ict_analyzer.find_order_blocks(tf_series)
            ict_patterns[f"order_blocks_{tf_key}"] = [asdict(ob) for ob in order_blocks]
            
            liquidity_voids = ict_analyzer.find_liquidity_voids(tf_series)
            ict_patterns[f"liquidity_voids_{tf_key}"] = [asdict(v) for v in liquidity_voids]

            # 3. Các phân tích phụ thuộc (sử dụng kết quả từ bước 1)
            pd_range = ict_analyzer.analyze_premium_discount(cp, swing_highs, swing_lows)
            ict_patterns[f"premium_discount_{tf_key}"] = asdict(pd_range) if pd_range else None

            mss = ict_analyzer.find_market_structure_shift(tf_series, swing_highs, swing_lows)
            ict_patterns[f"mss_{tf_key}"] = asdict(mss) if mss else None
            
            logger.debug(f"Đã hoàn thành phân tích ICT cho timeframe {tf_name}.")

    except Exception as e:
        logger.exception("Lỗi nghiêm trọng trong quá trình phân tích ICT.")
        ict_patterns = {}

    payload = {
        "MT5_DATA": {
            "symbol": symbol,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "broker_time": broker_time.isoformat(timespec="seconds"),
            "account": account_obj or {},
            "positions": positions_list,
            "info": info_obj or {},
            "symbol_rules": rules_obj or {},
            "pip": {
                "points_per_pip": points_per_pip_from_info(info_obj),
                "value_per_point": value_per_point(symbol, info),
                "pip_value_per_lot": (
                    (value_per_point(symbol, info) or 0.0)
                    * points_per_pip_from_info(info_obj)
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
            "day_range_pct_of_adr20": (
                float(day_range_pct) if day_range_pct is not None else None
            ),
            "position_in_day_range": (
                float(pos_in_day) if pos_in_day is not None else None
            ),
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
    logger.debug("Đã xây dựng payload MT5_DATA.")

    # Always wrap in SafeData. The caller can decide to get the raw dict or json.
    safe_data_obj = SafeData(payload.get("MT5_DATA"))
    logger.debug("Đã tạo SafeData object.")

    if return_json:
        try:
            # This path is now less common, but supported for compatibility.
            result = json.dumps(payload, ensure_ascii=False)
            logger.debug("Trả về JSON string của payload.")
            return result
        except Exception as e:
            logger.error(f"Lỗi khi chuyển payload thành JSON string: {e}")
            return str(payload)

    logger.debug("Kết thúc build_context.")
    return safe_data_obj


def is_connected() -> bool:
    """Kiểm tra xem kết nối MT5 có đang hoạt động hay không."""
    if mt5 is None:
        return False
    try:
        # Lấy thông tin terminal để kiểm tra kết nối
        info = mt5.terminal_info()
        return info is not None
    except Exception:
        return False


# ------------------------------
# Trading action helpers
# ------------------------------

def calculate_lots(
    cfg: "RunConfig",
    symbol: str,
    entry_price: float,
    sl_price: float,
    info: dict[str, Any],
    account: dict[str, Any],
    risk_multiplier: float = 1.0
) -> float | None:
    """
    Tính toán khối lượng giao dịch dựa trên rủi ro.
    """
    logger.debug(f"Bắt đầu calculate_lots cho {symbol} với risk_multiplier={risk_multiplier}")
    if not all([entry_price, sl_price, info, account]):
        logger.error("Thiếu thông tin đầu vào để tính toán lots.")
        return None

    try:
        balance = float(account.get("balance", 0.0))
        risk_per_trade_pct = float(cfg.auto_trade.risk_per_trade)
        
        # Tính toán số tiền rủi ro
        risk_amount = balance * (risk_per_trade_pct / 100.0) * risk_multiplier
        
        # Tính khoảng cách stop loss bằng điểm
        sl_points = abs(entry_price - sl_price) / (info.get("point", 0.00001))
        
        # Lấy giá trị mỗi điểm cho 1 lot
        val_per_point = value_per_point(symbol, info)
        if not val_per_point or val_per_point <= 0:
            logger.error("Không thể lấy value_per_point.")
            return None
            
        # Tính giá trị rủi ro cho mỗi lot
        risk_per_lot = sl_points * val_per_point
        
        if risk_per_lot <= 0:
            logger.error("Rủi ro mỗi lot không hợp lệ.")
            return None
            
        # Tính toán khối lượng
        lots = risk_amount / risk_per_lot
        
        # Làm tròn khối lượng theo quy tắc của sàn
        volume_step = info.get("volume_step", 0.01)
        lots = round(lots / volume_step) * volume_step
        
        # Kiểm tra giới hạn khối lượng
        min_vol = info.get("volume_min", 0.01)
        max_vol = info.get("volume_max", 100.0)
        
        if lots < min_vol:
            logger.warning(f"Lots ({lots}) nhỏ hơn min_vol ({min_vol}). Đặt lại là min_vol.")
            lots = min_vol
        if lots > max_vol:
            logger.warning(f"Lots ({lots}) lớn hơn max_vol ({max_vol}). Đặt lại là max_vol.")
            lots = max_vol
            
        logger.info(f"Tính toán lots thành công: {lots:.2f}")
        return lots
        
    except Exception as e:
        logger.exception(f"Lỗi trong quá trình tính toán lots: {e}")
        return None


def build_trade_requests(
    symbol: str,
    direction: str,
    entry_price: float,
    sl_price: float,
    tp1_price: float | None,
    tp2_price: float | None,
    total_lots: float,
    current_price: float,
    config: "RunConfig",
    info: dict[str, Any]
) -> list[dict[str, Any]]:
    """
    Xây dựng danh sách các yêu cầu giao dịch (có thể chia lệnh).
    """
    logger.debug("Bắt đầu build_trade_requests.")
    requests = []
    
    trade_type = mt5.ORDER_TYPE_BUY if direction.upper() == "BUY" else mt5.ORDER_TYPE_SELL
    
    # Xác định filling type từ config
    filling_type_str = config.auto_trade.filling_type.upper()
    filling_map = {
        "FOK": mt5.ORDER_FILLING_FOK,
        "IOC": mt5.ORDER_FILLING_IOC,
        "RETURN": mt5.ORDER_FILLING_RETURN,
    }
    filling_type = filling_map.get(filling_type_str, mt5.ORDER_FILLING_IOC)
    logger.debug(f"Sử dụng filling type: {filling_type_str} ({filling_type})")

    # Logic chia lệnh
    split_tp = config.auto_trade.split_tp_enabled and tp1_price and tp2_price
    lots1 = round(total_lots * (config.auto_trade.split_tp_ratio / 100.0), 2) if split_tp else total_lots
    lots2 = round(total_lots - lots1, 2) if split_tp else 0
    
    # Tạo yêu cầu cho lệnh 1 (hoặc lệnh duy nhất)
    if lots1 > 0:
        req1 = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": lots1,
            "type": trade_type,
            "price": entry_price,
            "sl": sl_price,
            "tp": tp1_price if split_tp else (tp1_price or tp2_price or 0.0),
            "deviation": config.auto_trade.deviation,
            "magic": config.auto_trade.magic_number,
            "comment": "AI Trade TP1" if split_tp else "AI Trade",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": filling_type,
        }
        requests.append(req1)

    # Tạo yêu cầu cho lệnh 2
    if lots2 > 0:
        req2 = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": lots2,
            "type": trade_type,
            "price": entry_price,
            "sl": sl_price,
            "tp": tp2_price or 0.0,
            "deviation": config.auto_trade.deviation,
            "magic": config.auto_trade.magic_number,
            "comment": "AI Trade TP2",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": filling_type,
        }
        requests.append(req2)
        
    logger.info(f"Đã tạo {len(requests)} yêu cầu giao dịch.")
    return requests


def order_send_smart(request: dict[str, Any], retries: int = 3, delay: float = 0.5):
    """
    Gửi yêu cầu giao dịch một cách thông minh với cơ chế thử lại.
    """
    logger.debug(f"Bắt đầu order_send_smart với request: {request}")
    
    # Các mã lỗi có thể thử lại
    RETRYABLE_RETCODES = {
        mt5.TRADE_RETCODE_REQUOTE,
        mt5.TRADE_RETCODE_PRICE_OFF,
        mt5.TRADE_RETCODE_CONNECTION,
        mt5.TRADE_RETCODE_SERVER_BUSY,
    }

    for attempt in range(retries):
        try:
            result = mt5.order_send(request)
            
            if result is None:
                logger.error(f"(Attempt {attempt+1}/{retries}) Gửi lệnh thất bại, không có kết quả. Lỗi MT5: {mt5.last_error()}")
                time.sleep(delay * (attempt + 1))
                continue

            if result.retcode == mt5.TRADE_RETCODE_DONE:
                logger.info(f"Gửi lệnh thành công. Ticket: {result.order}")
                return result
            
            if result.retcode in RETRYABLE_RETCODES:
                logger.warning(f"(Attempt {attempt+1}/{retries}) Gửi lệnh không thành công, sẽ thử lại. Retcode: {result.retcode}, Comment: {result.comment}")
                time.sleep(delay * (attempt + 1))
                continue
            else:
                logger.error(f"Gửi lệnh không thành công, lỗi không thể thử lại. Retcode: {result.retcode}, Comment: {result.comment}")
                return result # Trả về kết quả lỗi không thể thử lại

        except Exception as e:
            logger.exception(f"(Attempt {attempt+1}/{retries}) Lỗi nghiêm trọng khi gửi lệnh: {e}")
            if attempt + 1 == retries:
                return None # Trả về None sau khi hết số lần thử
            time.sleep(delay * (attempt + 1))
            
    logger.error("Gửi lệnh thất bại sau tất cả các lần thử.")
    return None


def close_position_partial(ticket: int, percentage: float) -> bool | None:
    """Đóng một phần vị thế."""
    logger.debug(f"Bắt đầu close_position_partial cho ticket {ticket}, percentage {percentage}")
    pos = mt5.positions_get(ticket=ticket)
    if not pos or len(pos) == 0:
        logger.error(f"Không tìm thấy vị thế với ticket {ticket}.")
        return False
        
    position = pos[0]
    volume_to_close = round(position.volume * (percentage / 100.0), 2)
    
    if volume_to_close <= 0:
        logger.warning("Khối lượng cần đóng quá nhỏ, bỏ qua.")
        return False

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "position": ticket,
        "symbol": position.symbol,
        "volume": volume_to_close,
        "type": mt5.ORDER_TYPE_SELL if position.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY,
        "price": mt5.symbol_info_tick(position.symbol).ask if position.type == mt5.ORDER_TYPE_BUY else mt5.symbol_info_tick(position.symbol).bid,
        "deviation": 10,
        "magic": position.magic,
        "comment": f"Partial Close {percentage}%",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    
    result = order_send_smart(request)
    if result:
        return result.retcode == mt5.TRADE_RETCODE_DONE
    return False


def get_last_swing_low_high(symbol: str, timeframe: int, bars: int, pivot_strength: int = 2) -> tuple[float | None, float | None]:
    """
    Lấy giá trị đáy/đỉnh cấu trúc (swing low/high) gần nhất.
    Sử dụng thuật toán xác định điểm xoay (pivot point).
    """
    logger.debug(f"Bắt đầu get_last_swing_low_high cho {symbol}, timeframe {timeframe}, {bars} bars.")
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, bars)
    if rates is None or len(rates) < (2 * pivot_strength + 1):
        logger.warning("Không đủ dữ liệu nến để xác định swing low/high.")
        return None, None
        
    last_swing_high = None
    last_swing_low = None

    # Duyệt ngược từ nến gần nhất để tìm điểm xoay
    for i in range(len(rates) - 1 - pivot_strength, pivot_strength - 1, -1):
        # Kiểm tra Swing High
        is_swing_high = True
        for j in range(1, pivot_strength + 1):
            if rates[i]['high'] < rates[i-j]['high'] or rates[i]['high'] < rates[i+j]['high']:
                is_swing_high = False
                break
        if is_swing_high:
            last_swing_high = rates[i]['high']
            logger.debug(f"Tìm thấy Swing High gần nhất tại giá {last_swing_high}")
            break # Tìm thấy cái gần nhất thì dừng

    for i in range(len(rates) - 1 - pivot_strength, pivot_strength - 1, -1):
        # Kiểm tra Swing Low
        is_swing_low = True
        for j in range(1, pivot_strength + 1):
            if rates[i]['low'] > rates[i-j]['low'] or rates[i]['low'] > rates[i+j]['low']:
                is_swing_low = False
                break
        if is_swing_low:
            last_swing_low = rates[i]['low']
            logger.debug(f"Tìm thấy Swing Low gần nhất tại giá {last_swing_low}")
            break # Tìm thấy cái gần nhất thì dừng
            
    return last_swing_low, last_swing_high


def modify_position(ticket: int, sl: float | None = None, tp: float | None = None) -> bool | None:
    """Sửa đổi Stop Loss và/hoặc Take Profit cho một vị thế."""
    logger.debug(f"Bắt đầu modify_position cho ticket {ticket} với SL={sl}, TP={tp}")
    pos = mt5.positions_get(ticket=ticket)
    if not pos or len(pos) == 0:
        logger.error(f"Không tìm thấy vị thế với ticket {ticket}.")
        return False
        
    position = pos[0]
    
    request = {
        "action": mt5.TRADE_ACTION_SLTP,
        "position": ticket,
        "symbol": position.symbol,
        "sl": sl if sl is not None else position.sl,
        "tp": tp if tp is not None else position.tp,
    }
    
    result = order_send_smart(request)
    if result:
        return result.retcode == mt5.TRADE_RETCODE_DONE
    return False
