from __future__ import annotations
from typing import Any, Iterable, Sequence
from datetime import datetime
import logging # Thêm import logging

logger = logging.getLogger(__name__) # Khởi tạo logger

def find_fvgs(rates: Sequence[dict], current_price: float) -> list:
    """
    Quét các thanh giá để tìm các Fair Value Gaps (FVGs) chưa được lấp đầy gần nhất
    so với giá hiện tại.

    Args:
        rates: Danh sách các từ điển chứa dữ liệu nến (open, high, low, close).
        current_price: Giá hiện tại của thị trường.

    Returns:
        Một danh sách các từ điển FVG.
    """
    logger.debug(f"Bắt đầu find_fvgs với {len(rates)} rates, current_price: {current_price}")
    if not rates or len(rates) < 3:
        logger.debug("Không đủ rates để tìm FVG.")
        return []

    fvgs = []
    for i in range(2, len(rates)):
        # Bullish FVG: low của nến hiện tại cao hơn high của nến i-2
        if rates[i]["low"] > rates[i-2]["high"]:
            fvg = {
                "type": "Bullish",
                "top": rates[i]["low"],
                "bottom": rates[i-2]["high"],
                "created_at_bar": i,
            }
            fvgs.append(fvg)
            logger.debug(f"Tìm thấy Bullish FVG: {fvg}")
        
        # Bearish FVG: high của nến hiện tại thấp hơn low của nến i-2
        if rates[i]["high"] < rates[i-2]["low"]:
            fvg = {
                "type": "Bearish",
                "top": rates[i-2]["low"],
                "bottom": rates[i]["high"],
                "created_at_bar": i,
            }
            fvgs.append(fvg)
            logger.debug(f"Tìm thấy Bearish FVG: {fvg}")

    if not fvgs:
        logger.debug("Không tìm thấy FVG nào.")
        return []

    # Kiểm tra xem các FVG đã được lấp đầy chưa
    unfilled_fvgs = []
    for fvg in fvgs:
        is_filled = False
        # Kiểm tra các thanh sau khi FVG được tạo
        for j in range(fvg["created_at_bar"] + 1, len(rates)):
            wick_low = rates[j]["low"]
            wick_high = rates[j]["high"]
            if fvg["type"] == "Bullish" and wick_low <= fvg["bottom"]:
                is_filled = True
                logger.debug(f"Bullish FVG {fvg} đã được fill.")
                break
            if fvg["type"] == "Bearish" and wick_high >= fvg["top"]:
                is_filled = True
                logger.debug(f"Bearish FVG {fvg} đã được fill.")
                break
        if not is_filled:
            unfilled_fvgs.append(fvg)
            logger.debug(f"FVG chưa được fill: {fvg}")
    
    if not unfilled_fvgs:
        logger.debug("Không có FVG nào chưa được fill.")
        return []

    # Tìm FVG bullish và bearish gần nhất với giá hiện tại
    nearest_bullish = None
    nearest_bearish = None
    min_dist_bullish = float('inf')
    min_dist_bearish = float('inf')

    for fvg in unfilled_fvgs:
        if fvg["type"] == "Bullish":
            # FVG bullish gần nhất thường nằm dưới giá hiện tại
            dist = current_price - fvg["top"]
            if 0 < dist < min_dist_bullish:
                min_dist_bullish = dist
                nearest_bullish = fvg
        elif fvg["type"] == "Bearish":
            # FVG bearish gần nhất thường nằm trên giá hiện tại
            dist = fvg["bottom"] - current_price
            if 0 < dist < min_dist_bearish:
                min_dist_bearish = dist
                nearest_bearish = fvg

    results = []
    if nearest_bullish:
        nearest_bullish['lo'] = nearest_bullish['bottom']
        nearest_bullish['hi'] = nearest_bullish['top']
        results.append(nearest_bullish)
        logger.debug(f"Nearest Bullish FVG: {nearest_bullish}")
    if nearest_bearish:
        nearest_bearish['lo'] = nearest_bearish['bottom']
        nearest_bearish['hi'] = nearest_bearish['top']
        nearest_bearish['type'] = 'bear'
        results.append(nearest_bearish)
        logger.debug(f"Nearest Bearish FVG: {nearest_bearish}")
    logger.debug(f"Kết thúc find_fvgs. Kết quả: {results}")
    return results


def find_liquidity_levels(rates: Sequence[dict], lookback: int = 200) -> dict:
    """
    Tìm các mức swing high (BSL - Buy Side Liquidity) và swing low (SSL - Sell Side Liquidity)
    quan trọng trong khoảng thời gian lookback.

    Args:
        rates: Danh sách các từ điển chứa dữ liệu nến (open, high, low, close).
        lookback: Số lượng nến gần nhất để xem xét.

    Returns:
        Một từ điển chứa danh sách các swing highs và swing lows.
    """
    logger.debug(f"Bắt đầu find_liquidity_levels với {len(rates)} rates, lookback: {lookback}")
    if not rates or len(rates) < 3:
        logger.debug("Không đủ rates để tìm liquidity levels.")
        return {}
    
    limited_rates = rates[-lookback:]
    swing_highs = []
    swing_lows = []

    for i in range(1, len(limited_rates) - 1):
        # Swing High: Nến hiện tại có high cao hơn nến trước và nến sau
        if limited_rates[i]["high"] > limited_rates[i-1]["high"] and limited_rates[i]["high"] > limited_rates[i+1]["high"]:
            swing_highs.append({"price": limited_rates[i]["high"], "bar_index": len(rates) - lookback + i})
            logger.debug(f"Tìm thấy Swing High: {limited_rates[i]['high']}")
        
        # Swing Low: Nến hiện tại có low thấp hơn nến trước và nến sau
        if limited_rates[i]["low"] < limited_rates[i-1]["low"] and limited_rates[i]["low"] < limited_rates[i+1]["low"]:
            swing_lows.append({"price": limited_rates[i]["low"], "bar_index": len(rates) - lookback + i})
            logger.debug(f"Tìm thấy Swing Low: {limited_rates[i]['low']}")

    results = {
        "swing_highs_BSL": sorted(swing_highs, key=lambda x: x['price'], reverse=True)[:5], # Top 5 cao nhất
        "swing_lows_SSL": sorted(swing_lows, key=lambda x: x['price'])[:5], # Top 5 thấp nhất
    }
    logger.debug(f"Kết thúc find_liquidity_levels. Kết quả: {results}")
    return results


def find_order_blocks(rates: Sequence[dict], lookback: int = 100) -> list:
    """
    Tìm các khối lệnh (Order Blocks - OB) bullish và bearish gần nhất chưa được giảm thiểu.
    Một định nghĩa đơn giản được sử dụng: một nến có phạm vi bị nuốt chửng bởi nến tiếp theo,
    dẫn đến sự phá vỡ cấu trúc.

    Args:
        rates: Danh sách các từ điển chứa dữ liệu nến (open, high, low, close).
        lookback: Số lượng nến gần nhất để xem xét.

    Returns:
        Một danh sách các từ điển OB.
    """
    logger.debug(f"Bắt đầu find_order_blocks với {len(rates)} rates, lookback: {lookback}")
    if not rates or len(rates) < 5: # Cần đủ nến cho ngữ cảnh
        logger.debug("Không đủ rates để tìm order blocks.")
        return []

    limited_rates = rates[-lookback:]
    bullish_obs = []
    bearish_obs = []

    # Lặp ngược để tìm các OB gần nhất trước
    for i in range(len(limited_rates) - 3, 1, -1):
        candle_ob = limited_rates[i]
        candle_move = limited_rates[i+1]
        
        # OB Bearish tiềm năng (nến tăng theo sau bởi một động thái giảm mạnh)
        if candle_ob["close"] > candle_ob["open"]: # Nến tăng
            if candle_move["close"] < candle_ob["low"]: # Động thái giảm mạnh phá vỡ mức thấp
                is_mitigated = False
                for j in range(i + 2, len(limited_rates)):
                    if limited_rates[j]["high"] > (candle_ob["low"] + (candle_ob["high"] - candle_ob["low"]) * 0.5): # Giá đã quay trở lại ngưỡng 50%
                        is_mitigated = True
                        break
                if not is_mitigated:
                    bearish_obs.append({
                        "top": candle_ob["high"],
                        "bottom": candle_ob["low"],
                        "bar_index": len(rates) - lookback + i,
                    })
                    logger.debug(f"Tìm thấy Bearish OB: {bearish_obs[-1]}")

        # OB Bullish tiềm năng (nến giảm theo sau bởi một động thái tăng mạnh)
        if candle_ob["close"] < candle_ob["open"]: # Nến giảm
            if candle_move["close"] > candle_ob["high"]: # Động thái tăng mạnh phá vỡ mức cao
                is_mitigated = False
                for j in range(i + 2, len(limited_rates)):
                    if limited_rates[j]["low"] < (candle_ob["low"] + (candle_ob["high"] - candle_ob["low"]) * 0.5): # Giá đã quay trở lại ngưỡng 50%
                        is_mitigated = True
                        break
                if not is_mitigated:
                    bullish_obs.append({
                        "top": candle_ob["high"],
                        "bottom": candle_ob["low"],
                        "bar_index": len(rates) - lookback + i,
                    })
                    logger.debug(f"Tìm thấy Bullish OB: {bullish_obs[-1]}")

    results = []
    if bullish_obs:
        nearest_bullish = bullish_obs[0]
        nearest_bullish['lo'] = nearest_bullish['bottom']
        nearest_bullish['hi'] = nearest_bullish['top']
        nearest_bullish['type'] = 'bull'
        results.append(nearest_bullish)
        logger.debug(f"Nearest Bullish OB: {nearest_bullish}")
    if bearish_obs:
        nearest_bearish = bearish_obs[0]
        nearest_bearish['lo'] = nearest_bearish['bottom']
        nearest_bearish['hi'] = nearest_bearish['top']
        nearest_bearish['type'] = 'bear'
        results.append(nearest_bearish)
        logger.debug(f"Nearest Bearish OB: {nearest_bearish}")
    logger.debug(f"Kết thúc find_order_blocks. Kết quả: {results}")
    return results


def analyze_premium_discount(rates: Sequence[dict], current_price: float, lookback: int = 200) -> dict | None:
    """
    Phân tích vị trí của giá hiện tại trong phạm vi giao dịch chính gần đây nhất
    để xác định xem nó đang ở vùng Premium hay Discount.

    Args:
        rates: Danh sách các từ điển chứa dữ liệu nến (open, high, low, close).
        current_price: Giá hiện tại của thị trường.
        lookback: Số lượng nến gần nhất để xem xét.

    Returns:
        Một từ điển chứa thông tin về phạm vi, điểm cân bằng và trạng thái (Premium/Discount),
        hoặc None nếu không thể phân tích.
    """
    logger.debug(f"Bắt đầu analyze_premium_discount với {len(rates)} rates, current_price: {current_price}, lookback: {lookback}")
    if not rates or len(rates) < 20: # Cần một số lượng nến hợp lý
        logger.debug("Không đủ rates để phân tích premium/discount.")
        return None

    limited_rates = rates[-lookback:]
    
    # Tìm mức cao nhất và thấp nhất trong khoảng thời gian lookback để xác định phạm vi
    highest_high = 0.0
    lowest_low = float('inf')
    
    for r in limited_rates:
        if r["high"] > highest_high:
            highest_high = r["high"]
        if r["low"] < lowest_low:
            lowest_low = r["low"]

    if highest_high == 0.0 or lowest_low == float('inf') or highest_high == lowest_low:
        logger.warning("Không thể xác định range cho premium/discount.")
        return None

    equilibrium = lowest_low + (highest_high - lowest_low) * 0.5
    status = "Premium" if current_price > equilibrium else "Discount"

    result = {
        "range_high": highest_high,
        "range_low": lowest_low,
        "equilibrium": equilibrium,
        "status": status,
    }
    logger.debug(f"Kết thúc analyze_premium_discount. Kết quả: {result}")
    return result


def find_market_structure_shift(rates: Sequence[dict], swing_highs: list, swing_lows: list) -> dict | None:
    """
    Phát hiện MSS nâng cao, xác định một chuỗi các swing chính để xác định xu hướng
    và phân biệt giữa BOS (Break of Structure) và CHoCH (Change of Character).

    Args:
        rates: Danh sách các từ điển chứa dữ liệu nến (open, high, low, close).
        swing_highs: Danh sách các swing highs đã tìm thấy.
        swing_lows: Danh sách các swing lows đã tìm thấy.

    Returns:
        Một từ điển chứa thông tin về MSS (loại, sự kiện, mức giá, chỉ mục nến phá vỡ),
        hoặc None nếu không tìm thấy.
    """
    logger.debug(f"Bắt đầu find_market_structure_shift với {len(rates)} rates, {len(swing_highs)} swing_highs, {len(swing_lows)} swing_lows.")
    if not rates or len(rates) < 20:
        logger.debug("Không đủ rates để tìm market structure shift.")
        return None

    # Kết hợp và sắp xếp tất cả các swing theo chỉ mục
    all_swings = sorted(swing_highs + swing_lows, key=lambda x: x['bar_index'])
    
    if len(all_swings) < 4: # Cần ít nhất hai đỉnh và hai đáy để xác định xu hướng
        logger.debug("Không đủ swings để xác định trend.")
        return None # Không đủ swings để xác định xu hướng một cách đáng tin cậy

    # 1. Xác định chuỗi 4 swing chính gần nhất để xác định xu hướng
    last_four_swings = all_swings[-4:]
    
    # Xác định hai đỉnh và hai đáy gần nhất từ bốn swing cuối cùng
    last_highs = [s for s in last_four_swings if s['price'] in [h['price'] for h in swing_highs]]
    last_lows = [s for s in last_four_swings if s['price'] in [l['price'] for l in swing_lows]]

    if len(last_highs) < 2 or len(last_lows) < 2:
        logger.debug("Không đủ highs hoặc lows để xác định trend.")
        return None # Không đủ swings để xác định xu hướng một cách đáng tin cậy

    recent_high = max(last_highs, key=lambda x: x['bar_index'])
    p_high = min(last_highs, key=lambda x: x['bar_index'])
    recent_low = max(last_lows, key=lambda x: x['bar_index'])
    p_low = min(last_lows, key=lambda x: x['bar_index'])
    logger.debug(f"Recent High: {recent_high}, Previous High: {p_high}, Recent Low: {recent_low}, Previous Low: {p_low}")

    # 2. Xác định xu hướng dựa trên hai đỉnh và hai đáy gần nhất
    trend = "Undetermined"
    # Bullish: Đỉnh cao hơn và Đáy cao hơn
    if recent_high['price'] > p_high['price'] and recent_low['price'] > p_low['price']:
        trend = "Bullish"
    # Bearish: Đỉnh thấp hơn và Đáy thấp hơn
    elif recent_high['price'] < p_high['price'] and recent_low['price'] < p_low['price']:
        trend = "Bearish"
    logger.debug(f"Xác định trend: {trend}")

    mss = None
    
    # 3. Quét từ swing chính gần nhất trở đi để tìm sự phá vỡ
    scan_start_index = min(recent_high['bar_index'], recent_low['bar_index']) + 1
    if scan_start_index >= len(rates):
        logger.debug("Scan start index vượt quá số lượng rates.")
        return None

    for i in range(scan_start_index, len(rates)):
        current_close = rates[i]['close']
        
        # Trong xu hướng bullish, phá vỡ recent_high là BOS
        # Phá vỡ recent_low là CHoCH
        if trend == "Bullish":
            if current_close > recent_high['price']:
                mss = {"type": "Bullish", "event": "BOS", "price_level": recent_high['price'], "break_bar_index": i}
                logger.debug(f"Tìm thấy Bullish BOS: {mss}")
                break
            if current_close < recent_low['price']:
                mss = {"type": "Bearish", "event": "CHoCH", "price_level": recent_low['price'], "break_bar_index": i}
                logger.debug(f"Tìm thấy Bearish CHoCH: {mss}")
                break # CHoCH có ưu tiên

        # Trong xu hướng bearish, phá vỡ recent_low là BOS
        # Phá vỡ recent_high là CHoCH
        elif trend == "Bearish":
            if current_close < recent_low['price']:
                mss = {"type": "Bearish", "event": "BOS", "price_level": recent_low['price'], "break_bar_index": i}
                logger.debug(f"Tìm thấy Bearish BOS: {mss}")
                break
            if current_close > recent_high['price']:
                mss = {"type": "Bullish", "event": "CHoCH", "price_level": recent_high['price'], "break_bar_index": i}
                logger.debug(f"Tìm thấy Bullish CHoCH: {mss}")
                break # CHoCH có ưu tiên
        
        # Nếu xu hướng không xác định, chỉ tìm kiếm sự phá vỡ của swing gần nhất
        elif i == scan_start_index: # Chỉ kiểm tra một lần
            latest_swing = max(recent_high, recent_low, key=lambda x: x['bar_index'])
            if latest_swing['price'] == recent_high['price'] and current_close > latest_swing['price']:
                 mss = {"type": "Bullish", "event": "BOS", "price_level": latest_swing['price'], "break_bar_index": i}
                 logger.debug(f"Tìm thấy Bullish BOS (undetermined trend): {mss}")
                 break
            elif latest_swing['price'] == recent_low['price'] and current_close < latest_swing['price']:
                 mss = {"type": "Bearish", "event": "BOS", "price_level": latest_swing['price'], "break_bar_index": i}
                 logger.debug(f"Tìm thấy Bearish BOS (undetermined trend): {mss}")
                 break

    logger.debug(f"Kết thúc find_market_structure_shift. Kết quả: {mss}")
    return mss


def get_session_liquidity(rates: Sequence[dict], sessions: dict, now_hhmm: str) -> dict:
    """
    Tìm mức cao nhất và thấp nhất của phiên chính trước đó (ví dụ: Asia High/Low trong phiên London).
    Sử dụng dữ liệu nến M15 để tăng tính mạnh mẽ.

    Args:
        rates: Danh sách các từ điển chứa dữ liệu nến (open, high, low, close).
        sessions: Từ điển chứa thông tin về thời gian bắt đầu/kết thúc của các phiên giao dịch.
        now_hhmm: Thời gian hiện tại dưới dạng chuỗi "HH:MM".

    Returns:
        Một từ điển chứa mức cao nhất và thấp nhất của các phiên trước đó.
    """
    logger.debug(f"Bắt đầu get_session_liquidity với {len(rates)} rates, sessions: {sessions}, now_hhmm: {now_hhmm}")
    if not rates:
        logger.debug("Không có rates để tìm session liquidity.")
        return {}

    session_liquidity = {}
    today_str = datetime.now().strftime("%Y-%m-%d")

    # Trong phiên London hoặc NY, tìm High/Low của phiên Asia
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
                logger.debug(f"Tìm thấy Asia High/Low: {session_liquidity['asia_high']}/{session_liquidity['asia_low']}")

    # Trong phiên NY, tìm High/Low của phiên London
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
                logger.debug(f"Tìm thấy London High/Low: {session_liquidity['london_high']}/{session_liquidity['london_low']}")
                
    logger.debug(f"Kết thúc get_session_liquidity. Kết quả: {session_liquidity}")
    return session_liquidity


def find_liquidity_voids(rates: Sequence[dict], lookback: int = 150) -> list:
    """
    Xác định các Liquidity Voids gần đây, là những biến động giá lớn, nhanh.
    Tìm kiếm các nến có thân lớn không được lấp đầy ngay lập tức.

    Args:
        rates: Danh sách các từ điển chứa dữ liệu nến (open, high, low, close).
        lookback: Số lượng nến gần nhất để xem xét.

    Returns:
        Một danh sách các từ điển Liquidity Void.
    """
    logger.debug(f"Bắt đầu find_liquidity_voids với {len(rates)} rates, lookback: {lookback}")
    if not rates or len(rates) < 3:
        logger.debug("Không đủ rates để tìm liquidity voids.")
        return []

    voids = []
    limited_rates = rates[-lookback:]

    for i in range(1, len(limited_rates)):
        candle = limited_rates[i]
        body_size = abs(candle["close"] - candle["open"])
        total_range = candle["high"] - candle["low"]

        if total_range > 0 and (body_size / total_range) > 0.7: # Đây là một nến có thân lớn
            is_unfilled = True
            # Kiểm tra xem vài nến tiếp theo có hồi lại đáng kể vào khoảng trống không
            for j in range(i + 1, min(i + 4, len(limited_rates))):
                # Khoảng trống bullish (nến tăng), kiểm tra xem giá có quay trở lại vào thân nến không
                if candle["close"] > candle["open"]:
                    if limited_rates[j]["low"] < candle["open"]:
                        is_unfilled = False
                        break
                # Khoảng trống bearish (nến giảm), kiểm tra xem giá có quay trở lại vào thân nến không
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
                logger.debug(f"Tìm thấy Liquidity Void: {voids[-1]}")

    # Trả về 3 khoảng trống gần nhất
    results = sorted(voids, key=lambda x: x['bar_index'], reverse=True)[:3]
    logger.debug(f"Kết thúc find_liquidity_voids. Kết quả: {results}")
    return results


def is_silver_bullet_window(now_hhmm: str, kills: dict) -> bool:
    """
    Kiểm tra xem thời gian hiện tại có nằm trong cửa sổ Silver Bullet của ICT (10-11 AM giờ New York) hay không.

    Args:
        now_hhmm: Thời gian hiện tại dưới dạng chuỗi "HH:MM".
        kills: Từ điển chứa thông tin về thời gian bắt đầu/kết thúc của các killzone.

    Returns:
        True nếu thời gian hiện tại nằm trong cửa sổ Silver Bullet, ngược lại là False.
    """
    logger.debug(f"Bắt đầu is_silver_bullet_window với now_hhmm: {now_hhmm}, kills: {kills}")
    # Silver Bullet của NY (10:00-11:00 AM giờ NY)
    # Killzone `newyork_am` được định nghĩa là 8:30-11:00 AM giờ NY.
    # Vì vậy, cửa sổ Silver Bullet bắt đầu 1.5 giờ sau khi KZ bắt đầu và kéo dài trong 1 giờ.
    ny_am_start = kills.get("newyork_am", {}).get("start")
    if not ny_am_start:
        logger.debug("Không tìm thấy thời gian bắt đầu killzone NY AM.")
        return False
    
    try:
        h_start, m_start = map(int, ny_am_start.split(':'))
        
        # Thêm 1h 30m để đến 10:00 AM giờ NY từ 8:30 AM
        sb_h_start = h_start + 1
        sb_m_start = m_start + 30
        if sb_m_start >= 60:
            sb_h_start += 1
            sb_m_start -= 60
            
        sb_start_str = f"{sb_h_start:02d}:{sb_m_start:02d}"
        
        # Cửa sổ kéo dài 1 giờ
        sb_h_end = sb_h_start + 1
        sb_end_str = f"{sb_h_end:02d}:{sb_m_start:02d}"

        if sb_start_str <= now_hhmm < sb_end_str:
            logger.debug(f"Hiện tại đang trong cửa sổ Silver Bullet: {sb_start_str} - {sb_end_str}.")
            return True
            
    except Exception as e:
        logger.error(f"Lỗi khi tính toán cửa sổ Silver Bullet: {e}")
        return False

    logger.debug("Không nằm trong cửa sổ Silver Bullet.")
    return False
