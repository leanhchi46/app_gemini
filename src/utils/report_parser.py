# -*- coding: utf-8 -*-
import re
import json
import math
import hashlib

def find_balanced_json_after(text: str, start_idx: int):
    depth, i = 0, start_idx
    if text[i] != '{':
        return None, None
        
    while i < len(text):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start_idx:i+1], i+1
        i += 1
    return None, None

def extract_json_block_prefer(text: str):
    fence = re.findall(r"```json\s*(\{[\s\S]*?\})\s*```", text, flags=re.IGNORECASE)
    for blob in fence:
        try:
            return json.loads(blob)
        except Exception:
            pass

    keywords = ["CHECKLIST_JSON", "EXTRACT_JSON", "setup", "trade", "signal"]
    lowered = text.lower()
    for kw in keywords:
        idx = lowered.find(kw.lower())
        if idx >= 0:
            brace = text.find("{", idx)
            if brace >= 0:
                js, _ = find_balanced_json_after(text, brace)
                if js:
                    try:
                        return json.loads(js)
                    except Exception:
                        pass

    first_brace = text.find("{")
    while first_brace >= 0:
        js, nxt = find_balanced_json_after(text, first_brace)
        if js:
            try:
                import json as _json
                return _json.loads(js)
            except Exception:
                pass
            first_brace = text.find("{", nxt if nxt else first_brace + 1)
        else:
            break
    return None

def coerce_setup_from_json(obj):
    if obj is None:
        return None

    candidates = []
    if isinstance(obj, dict):
        candidates.append(obj)
        for k in ("CHECKLIST_JSON", "EXTRACT_JSON", "setup", "trade", "signal"):
            v = obj.get(k)
            if isinstance(v, dict):
                candidates.append(v)

    def _num(x):
        if x is None:
            return None
        if isinstance(x, (int, float)) and math.isfinite(x):
            return float(x)
        if isinstance(x, str):
            xs = x.strip().replace(",", "")
            try:
                return float(xs)
            except Exception:
                return None
        return None

    def _dir(x):
        if not x:
            return None
        s = str(x).strip().lower()

        if s in ("long", "buy", "mua", "bull", "bullish"):
            return "long"
        if s in ("short", "sell", "bán", "ban", "bear", "bearish"):
            return "short"
        return None

    for c in candidates:
        d = {
            "direction": _dir(c.get("direction") or c.get("dir") or c.get("side")),
            "entry": _num(c.get("entry") or c.get("price") or c.get("ep")),
            "sl":    _num(c.get("sl")    or c.get("stop")  or c.get("stop_loss")),
            "tp1":   _num(c.get("tp1")   or c.get("tp_1")  or c.get("take_profit_1") or c.get("tp")),
            "tp2":   _num(c.get("tp2")   or c.get("tp_2")  or c.get("take_profit_2")),
        }

        if d["tp1"] is None and d["tp2"] is not None:
            d["tp1"] = d["tp2"]
        if d["tp1"] is not None and d["sl"] is not None and d["entry"] is not None and d["direction"] in ("long","short"):
            return d
    return None

def parse_float(s: str):
    try:
        return float(s.strip().replace(",", ""))
    except (ValueError, TypeError):
        return None

def parse_direction_from_line1(line1: str):
    s = line1.strip().lower()
    if "long" in s or "buy" in s or "bull" in s:
        return "long"
    if "short" in s or "sell" in s or "bear" in s:
        return "short"
    return None

def create_report_signature(text: str) -> str:
    """Creates a signature for a report to avoid duplicates."""
    if not text:
        return ""
    # Normalize whitespace and case to make it more robust
    normalized_text = " ".join(text.strip().lower().split())
    return hashlib.sha1(normalized_text.encode("utf-8")).hexdigest()

def extract_summary_lines(text: str) -> tuple[list[str], str, bool]:
    """Extracts summary lines, a signature, and high probability flag from report text."""
    lines = text.strip().split('\n')
    summary = []
    # A simple heuristic: find the first block of bullet points
    in_summary = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(("- ", "* ")):
            summary.append(stripped)
            in_summary = True
        elif in_summary and stripped: # block ended
            break
        elif in_summary and not stripped: # allow empty lines within summary
            pass

    if not summary:  # Fallback: take first 5 non-empty lines
        summary = [l.strip() for l in lines if l.strip()][:5]

    high_prob = "HIGH PROBABILITY" in text.upper()
    
    summary_text = "\n".join(summary)
    sig = create_report_signature(summary_text)

    return summary, sig, high_prob

def parse_setup_from_report(text: str):
    """Extracts a trade setup from a report by finding and parsing a JSON block."""
    json_block = extract_json_block_prefer(text)
    return coerce_setup_from_json(json_block)

def _generate_extract_json(mt5_data: dict) -> dict:
    """
    Tạo một dictionary chứa các thông tin trích xuất quan trọng từ dữ liệu MT5.
    """
    extract_dict = {
        "symbol": mt5_data.get("symbol"),
        "broker_time": mt5_data.get("broker_time"),
        "account_balance": mt5_data.get("account", {}).get("balance"),
        "account_equity": mt5_data.get("account", {}).get("equity"),
        "current_bid": mt5_data.get("tick", {}).get("bid"),
        "current_ask": mt5_data.get("tick", {}).get("ask"),
        "current_spread": mt5_data.get("info", {}).get("spread_current"),
        "day_open": mt5_data.get("day_open"),
        "day_high": mt5_data.get("levels", {}).get("daily", {}).get("high"),
        "day_low": mt5_data.get("levels", {}).get("daily", {}).get("low"),
        "day_range": mt5_data.get("day_range"),
        "position_in_day_range": mt5_data.get("position_in_day_range"),
        "killzone_active": mt5_data.get("killzone_active"),
        "is_silver_bullet_window": mt5_data.get("is_silver_bullet_window"),
        "volatility_regime": mt5_data.get("volatility_regime"),
        "premium_discount_h1_status": mt5_data.get("ict_patterns", {}).get("premium_discount_h1", {}).get("status"),
        "premium_discount_m15_status": mt5_data.get("ict_patterns", {}).get("premium_discount_m15", {}).get("status"),
        "news_in_window": mt5_data.get("news_analysis", {}).get("is_in_news_window"),
        "news_reason": mt5_data.get("news_analysis", {}).get("reason"),
    }

    # Thêm các mức ATR
    atr_data = mt5_data.get("volatility", {}).get("ATR", {})
    for tf, value in atr_data.items():
        extract_dict[f"atr_{tf.lower()}"] = value

    # Thêm các key levels
    key_levels = mt5_data.get("key_levels_nearby", [])
    for level in key_levels:
        name = level.get("name")
        price = level.get("price")
        relation = level.get("relation")
        if name and price:
            extract_dict[f"key_level_{name.lower()}_price"] = price
            extract_dict[f"key_level_{name.lower()}_relation"] = relation

    # Thêm các mẫu hình ICT
    ict_patterns = mt5_data.get("ict_patterns")
    if ict_patterns:
        for tf_key in ["m15", "h1"]:
            # FVG
            fvgs = ict_patterns.get(f"fvgs_{tf_key}")
            if isinstance(fvgs, dict): # Thêm kiểm tra kiểu dữ liệu
                if fvgs.get("nearest_bullish"):
                    extract_dict[f"fvg_{tf_key}_bullish_top"] = fvgs["nearest_bullish"].get("top")
                    extract_dict[f"fvg_{tf_key}_bullish_bottom"] = fvgs["nearest_bullish"].get("bottom")
                if fvgs.get("nearest_bearish"):
                    extract_dict[f"fvg_{tf_key}_bearish_top"] = fvgs["nearest_bearish"].get("top")
                    extract_dict[f"fvg_{tf_key}_bearish_bottom"] = fvgs["nearest_bearish"].get("bottom")

            # Liquidity
            liquidity_data = ict_patterns.get(f"liquidity_{tf_key}")
            if isinstance(liquidity_data, dict): # Thêm kiểm tra kiểu dữ liệu
                if liquidity_data.get("swing_highs_BSL"):
                    extract_dict[f"liquidity_{tf_key}_bsl_count"] = len(liquidity_data["swing_highs_BSL"])
                    extract_dict[f"liquidity_{tf_key}_bsl_highest"] = liquidity_data["swing_highs_BSL"][0].get("price")
                if liquidity_data.get("swing_lows_SSL"):
                    extract_dict[f"liquidity_{tf_key}_ssl_count"] = len(liquidity_data["swing_lows_SSL"])
                    extract_dict[f"liquidity_{tf_key}_ssl_lowest"] = liquidity_data["swing_lows_SSL"][0].get("price")

            # Order Blocks
            obs = ict_patterns.get(f"order_blocks_{tf_key}")
            if isinstance(obs, dict): # Thêm kiểm tra kiểu dữ liệu
                if obs.get("nearest_bullish_ob"):
                    extract_dict[f"ob_{tf_key}_bullish_top"] = obs["nearest_bullish_ob"].get("top")
                    extract_dict[f"ob_{tf_key}_bullish_bottom"] = obs["nearest_bullish_ob"].get("bottom")
                if obs.get("nearest_bearish_ob"):
                    extract_dict[f"ob_{tf_key}_bearish_top"] = obs["nearest_bearish_ob"].get("top")
                    extract_dict[f"ob_{tf_key}_bearish_bottom"] = obs["nearest_bearish_ob"].get("bottom")

            # Liquidity Voids
            lvs = ict_patterns.get(f"liquidity_voids_{tf_key}", [])
            if lvs:
                extract_dict[f"liquidity_voids_{tf_key}_count"] = len(lvs)
                # Có thể thêm chi tiết hơn nếu cần, ví dụ: gần nhất, cao nhất/thấp nhất

    return extract_dict

def parse_mt5_data_to_report(safe_mt5_data) -> str:
    """Converts MT5 data into a structured report."""
    if not safe_mt5_data or not safe_mt5_data.raw:
        return "Không có dữ liệu MT5."

    mt5_data = safe_mt5_data.raw
    report_lines = []

    # Phần 1: Thông tin chung
    report_lines.append(f"## Báo cáo Phân tích Thị trường MT5 - {mt5_data.get('symbol')}")
    report_lines.append(f"Thời gian Broker: {mt5_data.get('broker_time')}")
    report_lines.append(f"Cân bằng tài khoản: {mt5_data.get('account', {}).get('balance'):.2f} {mt5_data.get('account', {}).get('currency')}")
    report_lines.append(f"Equity: {mt5_data.get('account', {}).get('equity'):.2f} {mt5_data.get('account', {}).get('currency')}")
    report_lines.append(f"Giá Bid/Ask: {mt5_data.get('tick', {}).get('bid')}/{mt5_data.get('tick', {}).get('ask')} (Spread: {mt5_data.get('info', {}).get('spread_current')})")
    report_lines.append(f"Killzone hiện tại: {mt5_data.get('killzone_active', 'N/A')}")
    report_lines.append(f"Silver Bullet Window: {'Có' if mt5_data.get('is_silver_bullet_window') else 'Không'}")
    report_lines.append(f"Chế độ biến động: {mt5_data.get('volatility_regime', 'N/A')}")
    report_lines.append("")

    # Phần 2: Key Levels
    report_lines.append("### Các Mức Giá Quan trọng (Key Levels)")
    key_levels = mt5_data.get("key_levels_nearby", [])
    if key_levels:
        for level in key_levels:
            report_lines.append(f"- {level.get('name')}: {level.get('price')} ({level.get('relation')})")
    else:
        report_lines.append("- Không có key levels đáng chú ý gần đây.")
    report_lines.append("")

    # Phần 3: Thông tin ICT Patterns
    report_lines.append("### Các Mẫu hình ICT")
    ict_patterns = mt5_data.get("ict_patterns", {})
    if ict_patterns:
        for tf_key in ["h1", "m15"]: # Ưu tiên H1 trước
            report_lines.append(f"#### Khung thời gian {tf_key.upper()}")

            # Premium/Discount
            pd_data = ict_patterns.get(f"premium_discount_{tf_key}", {})
            if pd_data:
                report_lines.append(f"- Premium/Discount: {pd_data.get('status')} (Range: {pd_data.get('range_low')} - {pd_data.get('range_high')}, EQ: {pd_data.get('equilibrium')})")

            # FVG
            fvgs = ict_patterns.get(f"fvgs_{tf_key}")
            if isinstance(fvgs, dict):
                if fvgs.get("nearest_bullish"):
                    fvg = fvgs["nearest_bullish"]
                    report_lines.append(f"- FVG Bullish gần nhất: {fvg.get('bottom')} - {fvg.get('top')}")
                if fvgs.get("nearest_bearish"):
                    fvg = fvgs["nearest_bearish"]
                    report_lines.append(f"- FVG Bearish gần nhất: {fvg.get('bottom')} - {fvg.get('top')}")

            # Order Blocks
            obs = ict_patterns.get(f"order_blocks_{tf_key}")
            if isinstance(obs, dict):
                if obs.get("nearest_bullish_ob"):
                    ob = obs["nearest_bullish_ob"]
                    report_lines.append(f"- OB Bullish gần nhất: {ob.get('bottom')} - {ob.get('top')}")
                if obs.get("nearest_bearish_ob"):
                    ob = obs["nearest_bearish_ob"]
                    report_lines.append(f"- OB Bearish gần nhất: {ob.get('bottom')} - {ob.get('top')}")

            # Liquidity
            liquidity_data = ict_patterns.get(f"liquidity_{tf_key}")
            if isinstance(liquidity_data, dict):
                if liquidity_data.get("swing_highs_BSL"):
                    report_lines.append(f"- BSL (Swing Highs): {len(liquidity_data['swing_highs_BSL'])} điểm, cao nhất {liquidity_data['swing_highs_BSL'][0].get('price')}")
                if liquidity_data.get("swing_lows_SSL"):
                    report_lines.append(f"- SSL (Swing Lows): {len(liquidity_data['swing_lows_SSL'])} điểm, thấp nhất {liquidity_data['swing_lows_SSL'][0].get('price')}")
            
            # Liquidity Voids
            lvs = ict_patterns.get(f"liquidity_voids_{tf_key}", [])
            if lvs:
                report_lines.append(f"- Liquidity Voids: {len(lvs)} vùng")
            report_lines.append("")
    else:
        report_lines.append("- Không có mẫu hình ICT nào được phát hiện.")
    report_lines.append("")

    # Phần 4: News Analysis
    report_lines.append("### Phân tích Tin tức")
    news_analysis = mt5_data.get("news_analysis", {})
    report_lines.append(f"- Trong cửa sổ tin tức: {'Có' if news_analysis.get('is_in_news_window') else 'Không'}")
    report_lines.append(f"- Lý do: {news_analysis.get('reason', 'N/A')}")
    if news_analysis.get("upcoming_events"):
        report_lines.append("- Các sự kiện sắp tới:")
        for event in news_analysis["upcoming_events"]:
            report_lines.append(f"  - {event.get('time')} {event.get('currency')} {event.get('impact')} {event.get('event')}")
    report_lines.append("")

    # Phần 5: JSON trích xuất (để AI dễ đọc)
    report_lines.append("### [EXTRACT_JSON]")
    extract_dict = _generate_extract_json(mt5_data)
    report_lines.append(json.dumps(extract_dict, indent=2, ensure_ascii=False))

    return "\n".join(report_lines)

def repair_json_string(s: str) -> str:
    """
    Attempts to repair a malformed JSON string by removing common issues.
    This is a heuristic approach and may not fix all cases.
    """
    # Remove any leading/trailing non-JSON characters
    s = s.strip()

    # Remove comments (single-line // and multi-line /* */)
    s = re.sub(r"//.*?\n", "", s)
    s = re.sub(r"/\*[\s\S]*?\*/", "", s)

    # Replace single quotes with double quotes for keys and string values
    # This is a bit tricky and might break valid JSON if single quotes are part of a string
    # A more robust solution would involve a proper JSON parser with error recovery
    s = re.sub(r"(\s*['\"]?\w+['\"]?\s*:\s*)'([^']*)'", r'\1"\2"', s)
    s = re.sub(r"'([^']*)'", r'"\1"', s)

    # Ensure keys are double-quoted
    s = re.sub(r"([{,]\s*)(\w+)(\s*:)", r'\1"\2"\3', s)

    # Remove trailing commas before } or ]
    s = re.sub(r",\s*([}\]])", r'\1', s)

    # Attempt to balance brackets and braces
    # This is a very basic attempt and might not work for complex cases
    open_braces = s.count('{')
    close_braces = s.count('}')
    open_brackets = s.count('[')
    close_brackets = s.count(']')

    s += '}' * (open_braces - close_braces)
    s += ']' * (open_brackets - close_brackets)
    
    # Remove any non-printable characters or control characters
    s = ''.join(ch for ch in s if ch.isprintable() or ch in ('\n', '\t', '\r'))

    return s
