# -*- coding: utf-8 -*-
"""
Module phân tích các khái niệm của phương pháp ICT (Inner Circle Trader).

Cung cấp các hàm để xác định các cấu trúc thị trường quan trọng như:
- Fair Value Gaps (FVG)
- Mức thanh khoản (Liquidity Levels - BSL/SSL)
- Khối lệnh (Order Blocks)
- Vùng Premium/Discount
- Sự thay đổi trong cấu trúc thị trường (Market Structure Shift - MSS)
- Thanh khoản của các phiên giao dịch (Session Liquidity)
- Khoảng trống thanh khoản (Liquidity Voids)
- Cửa sổ thời gian "Silver Bullet"

**Cải tiến**:
- Sử dụng dataclasses để có cấu trúc dữ liệu trả về rõ ràng.
- Nâng cấp logic xác định swing (5-bar fractal) để tăng độ tin cậy.
- Tham số hóa các giá trị magic number (ngưỡng mitigation).
- Cải thiện logic xác định trading range.
- Chuẩn hóa xử lý thời gian bằng cách nhận đối tượng datetime.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Sequence

logger = logging.getLogger(__name__)

# region Dataclasses for ICT Concepts
@dataclass(frozen=True)
class ICTObject:
    """Lớp cơ sở cho các đối tượng ICT."""
    pass

@dataclass(frozen=True)
class FVG(ICTObject):
    """Đại diện cho một Fair Value Gap."""
    type: Literal["Bullish", "Bearish"]
    top: float
    bottom: float

@dataclass(frozen=True)
class LiquidityLevel(ICTObject):
    """Đại diện cho một mức thanh khoản (Swing High/Low)."""
    price: float
    bar_index: int

@dataclass(frozen=True)
class OrderBlock(ICTObject):
    """Đại diện cho một Khối lệnh."""
    type: Literal["Bullish", "Bearish"]
    top: float
    bottom: float
    bar_index: int

@dataclass(frozen=True)
class TradingRange(ICTObject):
    """Đại diện cho một phạm vi giao dịch Premium/Discount."""
    high: float
    low: float
    equilibrium: float
    status: Literal["Premium", "Discount"]

@dataclass(frozen=True)
class MarketStructureShift(ICTObject):
    """Đại diện cho một sự kiện phá vỡ cấu trúc thị trường."""
    type: Literal["Bullish", "Bearish"]
    event: Literal["BOS", "CHoCH"]
    price_level: float
    break_bar_index: int

@dataclass(frozen=True)
class LiquidityVoid(ICTObject):
    """Đại diện cho một khoảng trống thanh khoản."""
    type: Literal["Bullish", "Bearish"]
    top: float
    bottom: float
    bar_index: int
# endregion

def find_fvgs(rates: Sequence[dict], current_price: float, fill_check_limit: int = 10) -> list[FVG]:
    """
    Quét các thanh giá để tìm các FVG chưa được lấp đầy gần nhất.
    """
    logger.debug(f"Bắt đầu find_fvgs với {len(rates)} rates, current_price: {current_price}")
    if not rates or len(rates) < 3:
        return []

    # Tìm tất cả FVG tiềm năng
    all_fvgs = []
    for i in range(2, len(rates)):
        if rates[i]["low"] > rates[i-2]["high"]:
            all_fvgs.append({"type": "Bullish", "top": rates[i]["low"], "bottom": rates[i-2]["high"], "created_at_bar": i})
        elif rates[i]["high"] < rates[i-2]["low"]:
            all_fvgs.append({"type": "Bearish", "top": rates[i-2]["low"], "bottom": rates[i]["high"], "created_at_bar": i})

    # Lọc các FVG chưa được lấp đầy
    unfilled_fvgs = []
    for fvg in all_fvgs:
        is_filled = False
        check_end = min(len(rates), fvg["created_at_bar"] + 1 + fill_check_limit)
        for j in range(fvg["created_at_bar"] + 1, check_end):
            if (fvg["type"] == "Bullish" and rates[j]["low"] <= fvg["bottom"]) or \
               (fvg["type"] == "Bearish" and rates[j]["high"] >= fvg["top"]):
                is_filled = True
                break
        if not is_filled:
            unfilled_fvgs.append(fvg)

    # Tìm FVG gần nhất với giá hiện tại
    nearest_bullish, nearest_bearish = None, None
    min_dist_bullish, min_dist_bearish = float('inf'), float('inf')

    for fvg in unfilled_fvgs:
        if fvg["type"] == "Bullish" and current_price > fvg["top"]:
            dist = current_price - fvg["top"]
            if dist < min_dist_bullish:
                min_dist_bullish, nearest_bullish = dist, fvg
        elif fvg["type"] == "Bearish" and current_price < fvg["bottom"]:
            dist = fvg["bottom"] - current_price
            if dist < min_dist_bearish:
                min_dist_bearish, nearest_bearish = dist, fvg

    results = []
    if nearest_bullish:
        results.append(FVG(type="Bullish", top=nearest_bullish["top"], bottom=nearest_bullish["bottom"]))
    if nearest_bearish:
        results.append(FVG(type="Bearish", top=nearest_bearish["top"], bottom=nearest_bearish["bottom"]))
    
    logger.debug(f"Kết thúc find_fvgs. Tìm thấy {len(results)} FVG.")
    return results

def find_liquidity_levels(rates: Sequence[dict], lookback: int = 200) -> dict[str, list[LiquidityLevel]]:
    """
    Tìm các mức swing high (BSL) và swing low (SSL) sử dụng 5-bar fractal.
    """
    logger.debug(f"Bắt đầu find_liquidity_levels với {len(rates)} rates, lookback: {lookback}")
    if not rates or len(rates) < 5:
        return {"swing_highs_BSL": [], "swing_lows_SSL": []}
    
    limited_rates = rates[-lookback:]
    swing_highs, swing_lows = [], []

    for i in range(2, len(limited_rates) - 2):
        is_swing_high = limited_rates[i]["high"] > limited_rates[i-1]["high"] and \
                        limited_rates[i]["high"] > limited_rates[i-2]["high"] and \
                        limited_rates[i]["high"] > limited_rates[i+1]["high"] and \
                        limited_rates[i]["high"] > limited_rates[i+2]["high"]

        is_swing_low = limited_rates[i]["low"] < limited_rates[i-1]["low"] and \
                       limited_rates[i]["low"] < limited_rates[i-2]["low"] and \
                       limited_rates[i]["low"] < limited_rates[i+1]["low"] and \
                       limited_rates[i]["low"] < limited_rates[i+2]["low"]

        bar_index = len(rates) - lookback + i
        if is_swing_high:
            swing_highs.append(LiquidityLevel(price=limited_rates[i]["high"], bar_index=bar_index))
        if is_swing_low:
            swing_lows.append(LiquidityLevel(price=limited_rates[i]["low"], bar_index=bar_index))

    return {
        "swing_highs_BSL": sorted(swing_highs, key=lambda x: x.price, reverse=True)[:5],
        "swing_lows_SSL": sorted(swing_lows, key=lambda x: x.price)[:5],
    }

def find_order_blocks(rates: Sequence[dict], lookback: int = 100, mitigation_threshold: float = 0.5) -> list[OrderBlock]:
    """
    Tìm các khối lệnh (Order Blocks - OB) gần nhất chưa được giảm thiểu.
    """
    logger.debug(f"Bắt đầu find_order_blocks với {len(rates)} rates, lookback: {lookback}")
    if not rates or len(rates) < 5:
        return []

    limited_rates = rates[-lookback:]
    unmitigated_obs = []

    for i in range(len(limited_rates) - 3, 1, -1):
        ob_candle = limited_rates[i]
        move_candle = limited_rates[i+1]
        ob_type = None

        if ob_candle["close"] > ob_candle["open"] and move_candle["close"] < ob_candle["low"]:
            ob_type = "Bearish"
        elif ob_candle["close"] < ob_candle["open"] and move_candle["close"] > ob_candle["high"]:
            ob_type = "Bullish"

        if ob_type:
            is_mitigated = False
            mitigation_point = ob_candle["low"] + (ob_candle["high"] - ob_candle["low"]) * mitigation_threshold
            for j in range(i + 2, len(limited_rates)):
                if (ob_type == "Bearish" and limited_rates[j]["high"] > mitigation_point) or \
                   (ob_type == "Bullish" and limited_rates[j]["low"] < mitigation_point):
                    is_mitigated = True
                    break
            
            if not is_mitigated:
                bar_index = len(rates) - lookback + i
                unmitigated_obs.append(OrderBlock(
                    type=ob_type, top=ob_candle["high"], bottom=ob_candle["low"], bar_index=bar_index
                ))

    # Chỉ trả về OB Bullish và Bearish gần nhất
    nearest_bullish = next((ob for ob in unmitigated_obs if ob.type == "Bullish"), None)
    nearest_bearish = next((ob for ob in unmitigated_obs if ob.type == "Bearish"), None)
    
    results = []
    if nearest_bullish:
        results.append(nearest_bullish)
    if nearest_bearish:
        results.append(nearest_bearish)

    return results

def analyze_premium_discount(current_price: float, swing_highs: list[LiquidityLevel], swing_lows: list[LiquidityLevel]) -> TradingRange | None:
    """
    Phân tích Premium/Discount dựa trên các swing high/low quan trọng gần nhất.
    """
    if not swing_highs or not swing_lows:
        return None

    # Sắp xếp các swing theo chỉ mục để tìm các swing gần nhất
    sorted_highs = sorted(swing_highs, key=lambda x: x.bar_index, reverse=True)
    sorted_lows = sorted(swing_lows, key=lambda x: x.bar_index, reverse=True)

    # Xác định phạm vi dựa trên swing high và low gần nhất
    range_high = sorted_highs[0].price
    range_low = sorted_lows[0].price

    if range_high <= range_low:
        return None

    equilibrium = range_low + (range_high - range_low) * 0.5
    status = "Premium" if current_price > equilibrium else "Discount"

    return TradingRange(high=range_high, low=range_low, equilibrium=equilibrium, status=status)

def find_market_structure_shift(rates: Sequence[dict], swing_highs: list[LiquidityLevel], swing_lows: list[LiquidityLevel]) -> MarketStructureShift | None:
    """
    Phát hiện MSS (BOS/CHoCH) dựa trên các swing đã được xác định.
    """
    logger.debug(f"Bắt đầu find_market_structure_shift với {len(swing_highs)} highs, {len(swing_lows)} lows.")
    all_swings = sorted(swing_highs + swing_lows, key=lambda x: x.bar_index)
    
    if len(all_swings) < 4:
        return None

    last_highs = sorted([s for s in all_swings if isinstance(s, LiquidityLevel) and any(s.price == high.price for high in swing_highs)], key=lambda x: x.bar_index, reverse=True)
    last_lows = sorted([s for s in all_swings if isinstance(s, LiquidityLevel) and any(s.price == low.price for low in swing_lows)], key=lambda x: x.bar_index, reverse=True)

    if len(last_highs) < 2 or len(last_lows) < 2:
        return None

    recent_high, p_high = last_highs[0], last_highs[1]
    recent_low, p_low = last_lows[0], last_lows[1]

    trend = "Undetermined"
    if recent_high.price > p_high.price and recent_low.price > p_low.price:
        trend = "Bullish"
    elif recent_high.price < p_high.price and recent_low.price < p_low.price:
        trend = "Bearish"

    scan_start_index = min(recent_high.bar_index, recent_low.bar_index) + 1
    for i in range(scan_start_index, len(rates)):
        current_close = rates[i]['close']
        if trend == "Bullish":
            if current_close > recent_high.price:
                return MarketStructureShift("Bullish", "BOS", recent_high.price, i)
            if current_close < recent_low.price:
                return MarketStructureShift("Bearish", "CHoCH", recent_low.price, i)
        elif trend == "Bearish":
            if current_close < recent_low.price:
                return MarketStructureShift("Bearish", "BOS", recent_low.price, i)
            if current_close > recent_high.price:
                return MarketStructureShift("Bullish", "CHoCH", recent_high.price, i)
    return None

def get_session_liquidity(rates: Sequence[dict], sessions: dict, broker_time: datetime) -> dict:
    """
    Tìm mức cao/thấp của phiên trước đó dựa trên thời gian của broker.
    """
    session_liquidity = {}
    today_str = broker_time.strftime("%Y-%m-%d")
    now_hhmm = broker_time.strftime("%H:%M")

    london_start = sessions.get("london", {}).get("start", "23:59")
    if london_start <= now_hhmm:
        asia_range = sessions.get("asia", {})
        if asia_range:
            asia_candles = [r for r in rates if r["time"].startswith(today_str) and asia_range["start"] <= r["time"][11:16] < asia_range["end"]]
            if asia_candles:
                session_liquidity["asia_high"] = max(r["high"] for r in asia_candles)
                session_liquidity["asia_low"] = min(r["low"] for r in asia_candles)

    ny_start = sessions.get("newyork_am", {}).get("start", "23:59")
    if ny_start <= now_hhmm:
        london_range = sessions.get("london", {})
        if london_range:
            london_candles = [r for r in rates if r["time"].startswith(today_str) and london_range["start"] <= r["time"][11:16] < london_range["end"]]
            if london_candles:
                session_liquidity["london_high"] = max(r["high"] for r in london_candles)
                session_liquidity["london_low"] = min(r["low"] for r in london_candles)
                
    return session_liquidity

def find_liquidity_voids(rates: Sequence[dict], lookback: int = 150) -> list[LiquidityVoid]:
    """
    Xác định các Liquidity Voids gần đây.
    """
    if not rates or len(rates) < 3:
        return []

    voids = []
    limited_rates = rates[-lookback:]
    for i in range(1, len(limited_rates)):
        candle = limited_rates[i]
        body_size = abs(candle["close"] - candle["open"])
        total_range = candle["high"] - candle["low"]

        if total_range > 0 and (body_size / total_range) > 0.7:
            is_unfilled = True
            for j in range(i + 1, min(i + 4, len(limited_rates))):
                if (candle["close"] > candle["open"] and limited_rates[j]["low"] < candle["open"]) or \
                   (candle["close"] < candle["open"] and limited_rates[j]["high"] > candle["open"]):
                    is_unfilled = False
                    break
            if is_unfilled:
                bar_index = len(rates) - lookback + i
                voids.append(LiquidityVoid(
                    type="Bullish" if candle["close"] > candle["open"] else "Bearish",
                    top=candle["high"], bottom=candle["low"], bar_index=bar_index
                ))
    return sorted(voids, key=lambda x: x.bar_index, reverse=True)[:3]

def is_silver_bullet_window(broker_time: datetime, kills: dict) -> bool:
    """
    Kiểm tra có nằm trong cửa sổ Silver Bullet (10-11 AM NY time) hay không.
    """
    ny_am_start_str = kills.get("newyork_am", {}).get("start")
    if not ny_am_start_str:
        return False
    
    try:
        h_start, m_start = map(int, ny_am_start_str.split(':'))
        sb_h_start = h_start + 1
        sb_m_start = m_start + 30
        if sb_m_start >= 60:
            sb_h_start += 1
            sb_m_start -= 60
            
        sb_start_time = broker_time.replace(hour=sb_h_start, minute=sb_m_start, second=0, microsecond=0)
        sb_end_time = broker_time.replace(hour=sb_h_start + 1, minute=sb_m_start, second=0, microsecond=0)

        return sb_start_time <= broker_time < sb_end_time
    except Exception as e:
        logger.error(f"Lỗi khi tính toán cửa sổ Silver Bullet: {e}")
        return False
