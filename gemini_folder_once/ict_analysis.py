from __future__ import annotations
from typing import Any, Iterable, Sequence
from datetime import datetime

def find_fvgs(rates: Sequence[dict], current_price: float) -> list:
    """
    Scans rates to find the nearest unfilled Fair Value Gaps (FVGs) relative to the current price.
    Returns a list of FVG dictionaries.
    """
    if not rates or len(rates) < 3:
        return {}

    fvgs = []
    for i in range(2, len(rates)):
        # Bullish FVG: low of current candle is higher than high of candle i-2
        if rates[i]["low"] > rates[i-2]["high"]:
            fvg = {
                "type": "Bullish",
                "top": rates[i]["low"],
                "bottom": rates[i-2]["high"],
                "created_at_bar": i,
            }
            fvgs.append(fvg)
        
        # Bearish FVG: high of current candle is lower than low of candle i-2
        if rates[i]["high"] < rates[i-2]["low"]:
            fvg = {
                "type": "Bearish",
                "top": rates[i-2]["low"],
                "bottom": rates[i]["high"],
                "created_at_bar": i,
            }
            fvgs.append(fvg)

    if not fvgs:
        return {}

    # Check if FVGs have been filled
    unfilled_fvgs = []
    for fvg in fvgs:
        is_filled = False
        # Check bars after the FVG was created
        for j in range(fvg["created_at_bar"] + 1, len(rates)):
            wick_low = rates[j]["low"]
            wick_high = rates[j]["high"]
            if fvg["type"] == "Bullish" and wick_low <= fvg["bottom"]:
                is_filled = True
                break
            if fvg["type"] == "Bearish" and wick_high >= fvg["top"]:
                is_filled = True
                break
        if not is_filled:
            unfilled_fvgs.append(fvg)
    
    if not unfilled_fvgs:
        return []

    # Find the nearest bullish and bearish FVGs to the current price
    nearest_bullish = None
    nearest_bearish = None
    min_dist_bullish = float('inf')
    min_dist_bearish = float('inf')

    for fvg in unfilled_fvgs:
        if fvg["type"] == "Bullish":
            # Nearest bullish FVG is typically below the current price
            dist = current_price - fvg["top"]
            if 0 < dist < min_dist_bullish:
                min_dist_bullish = dist
                nearest_bullish = fvg
        elif fvg["type"] == "Bearish":
            # Nearest bearish FVG is typically above the current price
            dist = fvg["bottom"] - current_price
            if 0 < dist < min_dist_bearish:
                min_dist_bearish = dist
                nearest_bearish = fvg

    results = []
    if nearest_bullish:
        nearest_bullish['lo'] = nearest_bullish['bottom']
        nearest_bullish['hi'] = nearest_bullish['top']
        results.append(nearest_bullish)
    if nearest_bearish:
        nearest_bearish['lo'] = nearest_bearish['bottom']
        nearest_bearish['hi'] = nearest_bearish['top']
        results.append(nearest_bearish)
    return results


def find_liquidity_levels(rates: Sequence[dict], lookback: int = 200) -> dict:
    """
    Finds significant swing highs (BSL) and lows (SSL) within the lookback period.
    """
    if not rates or len(rates) < 3:
        return {}
    
    limited_rates = rates[-lookback:]
    swing_highs = []
    swing_lows = []

    for i in range(1, len(limited_rates) - 1):
        # Swing High
        if limited_rates[i]["high"] > limited_rates[i-1]["high"] and limited_rates[i]["high"] > limited_rates[i+1]["high"]:
            swing_highs.append({"price": limited_rates[i]["high"], "bar_index": len(rates) - lookback + i})
        
        # Swing Low
        if limited_rates[i]["low"] < limited_rates[i-1]["low"] and limited_rates[i]["low"] < limited_rates[i+1]["low"]:
            swing_lows.append({"price": limited_rates[i]["low"], "bar_index": len(rates) - lookback + i})

    return {
        "swing_highs_BSL": sorted(swing_highs, key=lambda x: x['price'], reverse=True)[:5], # Top 5 highest
        "swing_lows_SSL": sorted(swing_lows, key=lambda x: x['price'])[:5], # Top 5 lowest
    }


def find_order_blocks(rates: Sequence[dict], lookback: int = 100) -> list:
    """
    Finds the nearest unmitigated bullish and bearish order blocks.
    A simple definition is used: a candle whose range is engulfed by the next, leading to a break of structure.
    Returns a list of OB dictionaries.
    """
    if not rates or len(rates) < 5: # Need enough candles for context
        return {}

    limited_rates = rates[-lookback:]
    bullish_obs = []
    bearish_obs = []

    # Iterate backwards to find the most recent ones first
    for i in range(len(limited_rates) - 3, 1, -1):
        candle_ob = limited_rates[i]
        candle_move = limited_rates[i+1]
        
        # Potential Bearish OB (up candle followed by strong down move)
        if candle_ob["close"] > candle_ob["open"]: # Up candle
            if candle_move["close"] < candle_ob["low"]: # Strong down move breaking the low
                is_mitigated = False
                for j in range(i + 2, len(limited_rates)):
                    if limited_rates[j]["high"] > (candle_ob["low"] + (candle_ob["high"] - candle_ob["low"]) * 0.5): # Price returned to 50% mean threshold
                        is_mitigated = True
                        break
                if not is_mitigated:
                    bearish_obs.append({
                        "top": candle_ob["high"],
                        "bottom": candle_ob["low"],
                        "bar_index": len(rates) - lookback + i,
                    })

        # Potential Bullish OB (down candle followed by strong up move)
        if candle_ob["close"] < candle_ob["open"]: # Down candle
            if candle_move["close"] > candle_ob["high"]: # Strong up move breaking the high
                is_mitigated = False
                for j in range(i + 2, len(limited_rates)):
                    if limited_rates[j]["low"] < (candle_ob["low"] + (candle_ob["high"] - candle_ob["low"]) * 0.5): # Price returned to 50% mean threshold
                        is_mitigated = True
                        break
                if not is_mitigated:
                    bullish_obs.append({
                        "top": candle_ob["high"],
                        "bottom": candle_ob["low"],
                        "bar_index": len(rates) - lookback + i,
                    })

    results = []
    if bullish_obs:
        nearest_bullish = bullish_obs[0]
        nearest_bullish['lo'] = nearest_bullish['bottom']
        nearest_bullish['hi'] = nearest_bullish['top']
        nearest_bullish['type'] = 'bull'
        results.append(nearest_bullish)
    if bearish_obs:
        nearest_bearish = bearish_obs[0]
        nearest_bearish['lo'] = nearest_bearish['bottom']
        nearest_bearish['hi'] = nearest_bearish['top']
        nearest_bearish['type'] = 'bear'
        results.append(nearest_bearish)
    return results


def analyze_premium_discount(rates: Sequence[dict], current_price: float, lookback: int = 200) -> dict | None:
    """
    Analyzes the current price's position within the most recent major trading range.
    """
    if not rates or len(rates) < 20: # Need a decent number of bars
        return None

    limited_rates = rates[-lookback:]
    
    # Find the highest high and lowest low in the lookback period to define the range
    highest_high = 0.0
    lowest_low = float('inf')
    
    for r in limited_rates:
        if r["high"] > highest_high:
            highest_high = r["high"]
        if r["low"] < lowest_low:
            lowest_low = r["low"]

    if highest_high == 0.0 or lowest_low == float('inf') or highest_high == lowest_low:
        return None

    equilibrium = lowest_low + (highest_high - lowest_low) * 0.5
    status = "Premium" if current_price > equilibrium else "Discount"

    return {
        "range_high": highest_high,
        "range_low": lowest_low,
        "equilibrium": equilibrium,
        "status": status,
    }


def find_market_structure_shift(rates: Sequence[dict], swing_highs: list, swing_lows: list) -> dict | None:
    """
    Detects the most recent Market Structure Shift (MSS) or Break of Structure (BOS).
    Finds the most recent swing high/low and checks for a body close beyond it.
    """
    if not rates or len(rates) < 5 or (not swing_highs and not swing_lows):
        return None

    # The lists are sorted by price, so we re-sort by bar_index to find the most recent temporal swing point
    latest_swing_high = sorted(swing_highs, key=lambda x: x['bar_index'], reverse=True)[0] if swing_highs else None
    latest_swing_low = sorted(swing_lows, key=lambda x: x['bar_index'], reverse=True)[0] if swing_lows else None

    mss = None

    # Check for bearish MSS (breaking the latest swing low)
    if latest_swing_low:
        start_index = latest_swing_low['bar_index'] + 1
        # Ensure we don't look past the end of the main rates array
        if start_index < len(rates):
            for i in range(start_index, len(rates)):
                if rates[i]['close'] < latest_swing_low['price']:
                    mss = {
                        "type": "Bearish",
                        "price_level": latest_swing_low['price'],
                        "break_bar_index": i,
                    }
                    break # Found the first break

    # Check for bullish MSS (breaking the latest swing high)
    if latest_swing_high:
        start_index = latest_swing_high['bar_index'] + 1
        if start_index < len(rates):
            for i in range(start_index, len(rates)):
                if rates[i]['close'] > latest_swing_high['price']:
                    # If a bearish MSS was found, only overwrite if this one is more recent
                    if mss is None or i > mss.get('break_bar_index', -1):
                         mss = {
                            "type": "Bullish",
                            "price_level": latest_swing_high['price'],
                            "break_bar_index": i,
                        }
                    break # Found the first break
    
    return mss


def get_session_liquidity(rates: Sequence[dict], sessions: dict, now_hhmm: str) -> dict:
    """
    Finds the high and low of the preceding major session (e.g., Asia H/L during London).
    Uses M15 rates for robustness.
    """
    if not rates:
        return {}

    session_liquidity = {}
    today_str = datetime.now().strftime("%Y-%m-%d")

    # During London or NY, find Asia's High/Low
    london_start = sessions.get("london", {}).get("start", "23:59")
    
    if london_start <= now_hhmm:
        asia_range = sessions.get("asia", {})
        if asia_range:
            asia_candles = [
                r for r in rates 
                if r["time"].startswith(today_str) and asia_range.get("start", "23:59") <= r["time"][11:16] < asia_range.get("end", "00:00")
            ]
            if asia_candles:
                session_liquidity["asia_high"] = max(r["high"] for r in asia_candles)
                session_liquidity["asia_low"] = min(r["low"] for r in asia_candles)

    # During NY, find London's High/Low
    ny_start = sessions.get("newyork_am", {}).get("start", "23:59")
    if ny_start <= now_hhmm:
        london_range = sessions.get("london", {})
        if london_range:
            london_candles = [
                r for r in rates
                if r["time"].startswith(today_str) and london_range.get("start", "23:59") <= r["time"][11:16] < london_range.get("end", "00:00")
            ]
            if london_candles:
                session_liquidity["london_high"] = max(r["high"] for r in london_candles)
                session_liquidity["london_low"] = min(r["low"] for r in london_candles)
                
    return session_liquidity


def find_liquidity_voids(rates: Sequence[dict], lookback: int = 150) -> list:
    """
    Identifies recent Liquidity Voids, which are large, fast price movements.
    Looks for large-bodied candles that aren't immediately filled.
    """
    if not rates or len(rates) < 3:
        return []

    voids = []
    limited_rates = rates[-lookback:]

    for i in range(1, len(limited_rates)):
        candle = limited_rates[i]
        body_size = abs(candle["close"] - candle["open"])
        total_range = candle["high"] - candle["low"]

        if total_range > 0 and (body_size / total_range) > 0.7: # It's a large body candle
            is_unfilled = True
            # Check if the next few candles significantly retrace into the void
            for j in range(i + 1, min(i + 4, len(limited_rates))):
                # Bullish void (up candle), check if price comes back down into the body
                if candle["close"] > candle["open"]:
                    if limited_rates[j]["low"] < candle["open"]:
                        is_unfilled = False
                        break
                # Bearish void (down candle), check if price comes back up into the body
                else:
                    if limited_rates[j]["high"] > candle["open"]:
                        is_unfilled = False
                        break
            
            if is_unfilled:
                voids.append({
                    "type": "Bullish" if candle["close"] > candle["open"] else "Bearish",
                    "top": candle["high"],
                    "bottom": candle["low"],
                    "bar_index": len(rates) - lookback + i,
                })

    # Return the 3 most recent voids
    return sorted(voids, key=lambda x: x['bar_index'], reverse=True)[:3]


def is_silver_bullet_window(now_hhmm: str, kills: dict) -> bool:
    """
    Checks if the current time is within an ICT Silver Bullet window (10-11 AM NY time).
    """
    # NY Silver Bullet (10:00-11:00 AM NY time)
    # The `newyork_am` killzone is defined as 8:30-11:00 AM NY time.
    # So, the Silver Bullet window starts 1.5 hours after the KZ begins and lasts for 1 hour.
    ny_am_start = kills.get("newyork_am", {}).get("start")
    if not ny_am_start:
        return False
    
    try:
        h_start, m_start = map(int, ny_am_start.split(':'))
        
        # Add 1h 30m to get to 10:00 AM NY time from 8:30 AM
        sb_h_start = h_start + 1
        sb_m_start = m_start + 30
        if sb_m_start >= 60:
            sb_h_start += 1
            sb_m_start -= 60
            
        sb_start_str = f"{sb_h_start:02d}:{sb_m_start:02d}"
        
        # Window is 1 hour long
        sb_h_end = sb_h_start + 1
        sb_end_str = f"{sb_h_end:02d}:{sb_m_start:02d}"

        if sb_start_str <= now_hhmm < sb_end_str:
            return True
            
    except Exception:
        return False

    return False
