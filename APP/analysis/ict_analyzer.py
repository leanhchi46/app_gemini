from __future__ import annotations
from typing import Sequence
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

def find_fvgs(rates: Sequence[dict], current_price: float) -> list:
    """
    Quét các thanh giá để tìm các Fair Value Gaps (FVGs) chưa được lấp đầy gần nhất.
    """
    if not rates or len(rates) < 3:
        return []

    fvgs = []
    for i in range(2, len(rates)):
        if rates[i]["low"] > rates[i-2]["high"]:
            fvgs.append({
                "type": "Bullish", "top": rates[i]["low"], "bottom": rates[i-2]["high"],
                "created_at_bar": i,
            })
        if rates[i]["high"] < rates[i-2]["low"]:
            fvgs.append({
                "type": "Bearish", "top": rates[i-2]["low"], "bottom": rates[i]["high"],
                "created_at_bar": i,
            })

    unfilled_fvgs = []
    for fvg in fvgs:
        is_filled = False
        for j in range(fvg["created_at_bar"] + 1, len(rates)):
            if (fvg["type"] == "Bullish" and rates[j]["low"] <= fvg["bottom"]) or \
               (fvg["type"] == "Bearish" and rates[j]["high"] >= fvg["top"]):
                is_filled = True
                break
        if not is_filled:
            unfilled_fvgs.append(fvg)
    
    nearest_bullish, nearest_bearish = None, None
    min_dist_bullish, min_dist_bearish = float('inf'), float('inf')

    for fvg in unfilled_fvgs:
        if fvg["type"] == "Bullish":
            dist = current_price - fvg["top"]
            if 0 < dist < min_dist_bullish:
                min_dist_bullish, nearest_bullish = dist, fvg
        elif fvg["type"] == "Bearish":
            dist = fvg["bottom"] - current_price
            if 0 < dist < min_dist_bearish:
                min_dist_bearish, nearest_bearish = dist, fvg

    results = []
    if nearest_bullish:
        results.append({"type": "bull", "lo": nearest_bullish["bottom"], "hi": nearest_bullish["top"]})
    if nearest_bearish:
        results.append({"type": "bear", "lo": nearest_bearish["bottom"], "hi": nearest_bearish["top"]})
    return results


def find_liquidity_levels(rates: Sequence[dict], lookback: int = 200) -> dict:
    """
    Tìm các mức swing high (BSL) và swing low (SSL) quan trọng.
    """
    if not rates or len(rates) < 3:
        return {}
    
    limited_rates = rates[-lookback:]
    swing_highs, swing_lows = [], []

    for i in range(1, len(limited_rates) - 1):
        if limited_rates[i]["high"] > limited_rates[i-1]["high"] and limited_rates[i]["high"] > limited_rates[i+1]["high"]:
            swing_highs.append({"price": limited_rates[i]["high"], "bar_index": len(rates) - lookback + i})
        if limited_rates[i]["low"] < limited_rates[i-1]["low"] and limited_rates[i]["low"] < limited_rates[i+1]["low"]:
            swing_lows.append({"price": limited_rates[i]["low"], "bar_index": len(rates) - lookback + i})

    return {
        "swing_highs_BSL": sorted(swing_highs, key=lambda x: x['price'], reverse=True)[:5],
        "swing_lows_SSL": sorted(swing_lows, key=lambda x: x['price'])[:5],
    }


def find_order_blocks(rates: Sequence[dict], lookback: int = 100) -> list:
    """
    Tìm các khối lệnh (Order Blocks - OB) bullish và bearish gần nhất chưa được giảm thiểu.
    """
    if not rates or len(rates) < 5:
        return []

    limited_rates = rates[-lookback:]
    bullish_obs, bearish_obs = [], []

    for i in range(len(limited_rates) - 3, 1, -1):
        candle_ob = limited_rates[i]
        candle_move = limited_rates[i+1]
        
        is_mitigated = False
        for j in range(i + 2, len(limited_rates)):
            if (candle_ob["close"] > candle_ob["open"] and candle_move["close"] < candle_ob["low"] and limited_rates[j]["high"] > candle_ob["high"]) or \
               (candle_ob["close"] < candle_ob["open"] and candle_move["close"] > candle_ob["high"] and limited_rates[j]["low"] < candle_ob["low"]):
                is_mitigated = True
                break
        
        if not is_mitigated:
            if candle_ob["close"] > candle_ob["open"] and candle_move["close"] < candle_ob["low"]:
                bearish_obs.append({"top": candle_ob["high"], "bottom": candle_ob["low"]})
            elif candle_ob["close"] < candle_ob["open"] and candle_move["close"] > candle_ob["high"]:
                bullish_obs.append({"top": candle_ob["high"], "bottom": candle_ob["low"]})

    results = []
    if bullish_obs:
        results.append({"type": "bull", "lo": bullish_obs[0]["bottom"], "hi": bullish_obs[0]["top"]})
    if bearish_obs:
        results.append({"type": "bear", "lo": bearish_obs[0]["bottom"], "hi": bearish_obs[0]["top"]})
    return results


def analyze_premium_discount(rates: Sequence[dict], current_price: float, lookback: int = 200) -> dict | None:
    """
    Phân tích vị trí của giá hiện tại trong vùng Premium hay Discount.
    """
    if not rates or len(rates) < 20:
        return None

    limited_rates = rates[-lookback:]
    highest_high = max(r["high"] for r in limited_rates)
    lowest_low = min(r["low"] for r in limited_rates)

    if highest_high == lowest_low:
        return None

    equilibrium = (highest_high + lowest_low) / 2
    status = "Premium" if current_price > equilibrium else "Discount"

    return {
        "range_high": highest_high, "range_low": lowest_low,
        "equilibrium": equilibrium, "status": status,
    }

# Các hàm khác như find_market_structure_shift, get_session_liquidity, v.v.
# có thể được thêm vào đây với logic tương tự.
