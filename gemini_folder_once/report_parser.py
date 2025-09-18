from __future__ import annotations
import re
import json
import hashlib
from typing import Any
from .safe_data import SafeMT5Data

def _generate_extract_json(data: SafeMT5Data) -> dict[str, Any]:
    """Helper to build the EXTRACT_JSON part of the report."""
    extract_dict = {
        "tf": {},
        "comparisons": [],  # This will be populated below
        "risk_reward": {},
        "tolerance": {"method": "mt5", "value": "~0%"},  # Placeholder
        "conclusion": "CHƯA ĐỦ",  # Placeholder
        "missing": []  # Placeholder
    }

    # Populate timeframe data from the 'ict_patterns' and 'levels' keys
    cp = data.get_tick_value("bid") or data.get_tick_value("last") or 0.0
    ict_patterns = data.get("ict_patterns", {}) # Safely get the entire ict_patterns dictionary

    # Process all available timeframes (H1, M15, M5, M1)
    for tf_str, tf_key in [("H1", "h1"), ("M15", "m15"), ("M5", "m5"), ("M1", "m1")]:
        liquidity_data = ict_patterns.get(f"liquidity_{tf_key}", {})
        bsl = liquidity_data.get("swing_highs_BSL", [])
        ssl = liquidity_data.get("swing_lows_SSL", [])
        
        swing_h = bsl[0]['price'] if bsl else None
        swing_l = ssl[0]['price'] if ssl else None

        extract_dict["tf"][tf_str] = {
            "current_price": cp,
            "bias": "unknown",  # This will be updated later
            "swing": {"H": swing_h, "L": swing_l},
            "premium_discount": ict_patterns.get(f"premium_discount_{tf_key}", {}),
            "liquidity": {
                "BSL": [p['price'] for p in bsl],
                "SSL": [p['price'] for p in ssl],
                "EQH": [],  # Not directly available, needs logic
                "EQL": [],  # Not directly available, needs logic
            },
            "OB": ict_patterns.get(f"order_blocks_{tf_key}", []),
            "FVG": ict_patterns.get(f"fvgs_{tf_key}", []),
            "BPR": []  # Not available in mt5_utils
        }

    # Populate risk_reward from 'rr_projection'
    extract_dict["risk_reward"] = {
        "entry": data.get_plan_value("entry"),
        "sl": data.get_plan_value("sl"),
        "tp1": data.get_plan_value("tp1"),
        "tp2": data.get_plan_value("tp2"),
        "rr_tp1": data.get_rr_projection("tp1_rr")
    }

    # --- Inter-timeframe Comparisons ---
    try:
        h1_fvgs = extract_dict["tf"].get("H1", {}).get("FVG", [])
        h1_obs = extract_dict["tf"].get("H1", {}).get("OB", [])
        m15_fvgs = extract_dict["tf"].get("M15", {}).get("FVG", [])
        m15_obs = extract_dict["tf"].get("M15", {}).get("OB", [])

        def is_inside(inner_zone, outer_zone):
            return outer_zone["lo"] <= inner_zone["lo"] and inner_zone["hi"] <= outer_zone["hi"]

        # Check if M15 OBs are inside H1 structures
        for m15_ob in m15_obs:
            for h1_fvg in h1_fvgs:
                if is_inside(m15_ob, h1_fvg):
                    extract_dict["comparisons"].append({
                        "tf": "M15", "concept": "OB", "zone": f"{m15_ob['lo']}-{m15_ob['hi']}",
                        "relation": "INSIDE_H1_FVG", "distance": 0
                    })
            for h1_ob in h1_obs:
                if is_inside(m15_ob, h1_ob):
                     extract_dict["comparisons"].append({
                        "tf": "M15", "concept": "OB", "zone": f"{m15_ob['lo']}-{m15_ob['hi']}",
                        "relation": "INSIDE_H1_OB", "distance": 0
                    })

        # Check if M15 FVGs are inside H1 structures
        for m15_fvg in m15_fvgs:
            for h1_fvg in h1_fvgs:
                if is_inside(m15_fvg, h1_fvg):
                    extract_dict["comparisons"].append({
                        "tf": "M15", "concept": "FVG", "zone": f"{m15_fvg['lo']}-{m15_fvg['hi']}",
                        "relation": "INSIDE_H1_FVG", "distance": 0
                    })
    except Exception:
        pass # Ignore errors in comparison generation

    return extract_dict


def _generate_concept_value_table(data: SafeMT5Data, tf_data: dict) -> str:
    """Helper to build the CONCEPT_VALUE_TABLE part of the report."""
    cp = data.get_tick_value("bid") or data.get_tick_value("last") or 0.0
    point = data.get_info_value("point", 0.0)
    pip_value_per_point = data.get_pip_value("value_per_point", 0.0)
    points_per_pip = data.get_pip_value("points_per_pip", 1) or 1
    pip_size = (pip_value_per_point / points_per_pip) if point else 0.0

    def format_row(tf: str, concept: str, value: float | None, confidence: str = "High") -> str | None:
        if value is None or not cp or not point:
            return None
        relation = "ABOVE" if value > cp else "BELOW"
        distance = abs(value - cp) / point
        # Format value and distance for readability
        value_str = f"~{value:.3f}"
        dist_str = f"~{distance:.3f}"
        return f"{tf} | {concept} | {value_str} | {relation} | {dist_str} | {confidence}"

    rows = ["E) CONCEPT_VALUE_TABLE:", "", "Timeframe | Concept | Value/Zone | RelationToPrice | Distance | Confidence", "--- | --- | --- | --- | --- | ---"]
    
    # H1 Concepts
    h1_swing_h = (tf_data.get("H1", {}).get("swing") or {}).get("H")
    h1_swing_l = (tf_data.get("H1", {}).get("swing") or {}).get("L")
    rows.append(format_row("H1", "Current Price", cp))
    rows.append(format_row("H1", "Swing High", h1_swing_h))
    rows.append(format_row("H1", "Swing Low", h1_swing_l))
    rows.append(format_row("H1", "EQ50_D", data.get_daily_level("eq50")))
    rows.append(format_row("H1", "Daily VWAP", data.get_vwap("day")))
    rows.append(format_row("H1", "PDL", data.get_prev_day_level("low")))
    rows.append(format_row("H1", "PDH", data.get_prev_day_level("high")))
    rows.append(format_row("H1", "EMA50", data.get_ema("H1", "ema50")))

    # M15 Concepts
    m15_swing_h = (tf_data.get("M15", {}).get("swing") or {}).get("H")
    m15_swing_l = (tf_data.get("M15", {}).get("swing") or {}).get("L")
    rows.append(format_row("M15", "Current Price", cp))
    rows.append(format_row("M15", "Swing High", m15_swing_h))
    rows.append(format_row("M15", "Swing Low", m15_swing_l))

    # M5 Concepts
    m5_swing_h = (tf_data.get("M5", {}).get("swing") or {}).get("H")
    m5_swing_l = (tf_data.get("M5", {}).get("swing") or {}).get("L")
    rows.append(format_row("M5", "Current Price", cp))
    rows.append(format_row("M5", "Swing High", m5_swing_h))
    rows.append(format_row("M5", "Swing Low", m5_swing_l))

    # M1 Concepts
    m1_swing_h = (tf_data.get("M1", {}).get("swing") or {}).get("H")
    m1_swing_l = (tf_data.get("M1", {}).get("swing") or {}).get("L")
    rows.append(format_row("M1", "Current Price", cp))
    rows.append(format_row("M1", "Swing High", m1_swing_h))
    rows.append(format_row("M1", "Swing Low", m1_swing_l))

    # Filter out None rows before joining
    return "\n".join(filter(None, rows))


def _generate_checklist_json(data: SafeMT5Data, tf_data: dict) -> dict[str, Any]:
    """
    Generates a JSON template for the AI to fill out. It no longer calculates the status itself.
    It still provides the open trade monitoring data if in management mode.
    """
    from datetime import datetime

    positions = data.get("positions")
    if positions:
        # --- MANAGEMENT MODE ---
        pos = positions[0]
        current_price = data.get_tick_value("bid", 0.0) or data.get_tick_value("last", 0.0)
        entry_price = pos.get("price_open", 0.0)
        sl = pos.get("sl", 0.0)
        trade_type = "BUY" if pos.get("type") == 0 else "SELL"
        initial_risk = abs(entry_price - sl) if sl != 0 and entry_price != 0 else 0
        current_reward = (current_price - entry_price) if trade_type == "BUY" else (entry_price - current_price)
        current_rr = (current_reward / initial_risk) if initial_risk > 1e-9 else 0

        open_trade_monitoring = {
            "ticket": pos.get("ticket"),
            "type": trade_type,
            "volume": pos.get("volume"),
            "entry_price": entry_price,
            "stop_loss": sl,
            "take_profit": pos.get("tp", 0.0),
            "current_price": current_price,
            "current_profit": pos.get("profit"),
            "current_rr": round(current_rr, 2),
        }

        # Return the data needed for the management prompt
        return {
            "cycle": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "symbol": data.get("symbol", "unknown"),
            "mode": "management",
            "open_trade_monitoring": open_trade_monitoring,
        }

    # --- SETUP MODE (TEMPLATE ONLY) ---
    # Returns a blank checklist structure for the AI to fill.
    checklist_template = {
        "cycle": "[ĐIỀN THỜI GIAN HIỆN TẠI, ví dụ: 2025-09-18 18:00]",
        "symbol": data.get("symbol", "unknown"),
        "mode": "setup",
        "bias_H1": "[KẾT LUẬN TỪ B1, ví dụ: Bullish/Bearish/Sideways]",
        "poi_M15": {
            "type": "[LOẠI POI TỪ C1, ví dụ: FVG/OB]",
            "price_zone": "[VÙNG GIÁ POI TỪ C1]"
        },
        "setup_status": {
            "A1": "[ĐỦ/CHỜ/SAI]", "A2": "[ĐỦ/CHỜ/SAI]",
            "B1": "[ĐỦ/CHỜ/SAI]", "B2": "[ĐỦ/CHỜ/SAI]", "B3": "[ĐỦ/CHỜ/SAI]", "B4": "[ĐỦ/CHỜ/SAI]",
            "C1": "[ĐỦ/CHỜ/SAI]", "C2": "[ĐỦ/CHỜ/SAI]", "C3": "[ĐỦ/CHỜ/SAI]", "C4": "[ĐỦ/CHỜ/SAI]",
            "D1": "[ĐỦ/CHỜ/SAI]", "D2": "[ĐỦ/CHỜ/SAI]", "D3": "[ĐỦ/CHỜ/SAI]", "D4": "[ĐỦ/CHỜ/SAI]",
            "E1": "[ĐỦ/CHỜ/SAI]", "E2": "[ĐỦ/CHỜ/SAI]", "E3": "[ĐỦ/CHỜ/SAI]", "E4": "[ĐỦ/CHỜ/SAI]",
            "F1": "[ĐỦ/CHỜ/SAI]", "F2": "[ĐỦ/CHỜ/SAI]", "F3": "[ĐỦ/CHỜ/SAI]"
        },
        "conclusions": "[KẾT LUẬN TỔNG THỂ, ví dụ: ĐỦ/CHƯA ĐỦ/SAI]",
        "missing_conditions": [ "[LIỆT KÊ CÁC ĐIỀU KIỆN CÒN 'CHỜ']" ],
        "reasoning": {
            "B1": "Lý do cho quyết định B1...",
            "B2": "Lý do cho quyết định B2...",
            "...": "..."
        }
    }
    return checklist_template

def _is_poi_fresh(poi_zone: dict, series_after: list) -> bool:
    """Checks if a POI has been touched by subsequent price action."""
    if not series_after:
        return True
    poi_lo, poi_hi = poi_zone["lo"], poi_zone["hi"]
    for candle in series_after:
        if candle["low"] <= poi_hi and candle["high"] >= poi_lo:
            return False  # Price has touched or gone through the POI
    return True

def _find_best_m15_poi(data: SafeMT5Data, tf_data: dict, h1_bias: str) -> dict:
    """Finds and scores the best M15 POI based on confluence."""
    cp = data.get_tick_value("bid", 0.0)
    m15_series = (data.get("series") or {}).get("M15", [])
    sessions = data.get("sessions_today", {})
    killzones = {k: v for k, v in sessions.items() if "newyork" in k or "london" in k}

    potential_pois = []
    m15_fvgs = (tf_data.get("M15") or {}).get("FVG", [])
    m15_obs = (tf_data.get("M15") or {}).get("OB", [])
    h1_fvgs = (tf_data.get("H1") or {}).get("FVG", [])
    h1_obs = (tf_data.get("H1") or {}).get("OB", [])

    for fvg in m15_fvgs: potential_pois.append({"type": "FVG", "zone": fvg, "score": 0})
    for ob in m15_obs: potential_pois.append({"type": "OB", "zone": ob, "score": 0})

    h1_pd_info = data.get_ict_pattern("premium_discount_h1", {})
    h1_pd_status = h1_pd_info.get("status") if h1_pd_info else None
    
    def is_inside(inner, outer):
        return outer["lo"] <= inner["lo"] and inner["hi"] <= outer["hi"]

    for p in potential_pois:
        score = 0
        # Alignment with H1 Bias and P/D
        if h1_bias == "bullish" and h1_pd_status == "discount":
            if (p["type"] == "FVG" and p["zone"].get("dir") == "up") or \
               (p["type"] == "OB" and p["zone"].get("type") == "bull"):
                score += 20
        elif h1_bias == "bearish" and h1_pd_status == "premium":
            if (p["type"] == "FVG" and p["zone"].get("dir") == "down") or \
               (p["type"] == "OB" and p["zone"].get("type") == "bear"):
                score += 20
        
        # Confluence with H1 structures
        p["confluence"] = False
        for h1_fvg in h1_fvgs:
            if is_inside(p["zone"], h1_fvg): score += 10; p["confluence"] = True
        for h1_ob in h1_obs:
            if is_inside(p["zone"], h1_ob): score += 10; p["confluence"] = True

        # Freshness Bonus/Penalty
        poi_start_time = p["zone"].get("start_time")
        if poi_start_time:
            candles_after_poi = [c for c in m15_series if c["time"] > poi_start_time]
            if not _is_poi_fresh(p["zone"], candles_after_poi):
                score -= 15 # Penalty for mitigated POI
        
        # Killzone Formation Bonus
        if poi_start_time:
            poi_hhmm = poi_start_time[11:16]
            for kz_name, kz_times in killzones.items():
                if kz_times.get("start") <= poi_hhmm < kz_times.get("end"):
                    score += 10
                    break

        # Proximity bonus
        distance = abs(cp - (p["zone"]["hi"] + p["zone"]["lo"]) / 2)
        if distance > 0: score += (1 / distance) * 100
        p["score"] = score

    if not potential_pois:
        return {"details": {"type": "None", "price_zone": "N/A"}, "has_confluence": False}

    best_poi = max(potential_pois, key=lambda x: x["score"])
    return {
        "details": {
            "type": best_poi["type"],
            "price_zone": f"{best_poi['zone']['lo']}-{best_poi['zone']['hi']}"
        },
        "has_confluence": best_poi.get("confluence", False)
    }

def _analyze_ltf_entry_model(data: dict, h1_bias: str) -> dict:
    """
    Analyzes M1/M5 data to find an ICT entry model when price is at a valid POI.
    This is a placeholder for the complex logic required.
    """
    # Placeholder implementation. In a real scenario, this function would
    # involve detailed analysis of M1/M5 series from data.get("series").
    # - Find minor highs/lows for inducement.
    # - Detect a sweep of that liquidity.
    # - Detect a CHoCH/BOS in the direction of h1_bias.
    # - Confirm with displacement (new FVG/OB).
    # - Identify the refined entry zone.
    
    ltf_status = {
        "D1": "CHỜ",  # LTF Inducement/Sweep
        "D2": "CHỜ",  # LTF CHoCH/BOS
        "D3": "CHỜ",  # LTF Displacement
        "D4": "CHỜ",  # Refined Entry Zone
        "E1": "CHỜ",
        "E2": "CHỜ",
        "E3": "CHỜ",
        "E4": "CHỜ"
    }
    
    # This function will be fully implemented later. For now, it returns placeholders.
    return ltf_status

def parse_ai_response(text: str) -> dict:
    """
    Parses the AI's full response text to find and extract the completed
    CHECKLIST_JSON or MANAGEMENT_JSON object.
    """
    # Find the first occurrence of a JSON object in the text
    match = re.search(r"\{[\s\S]*?\}", text)
    if not match:
        return {"error": "No JSON object found in the AI response."}
    
    json_str = match.group(0)
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        return {"error": "Failed to decode the JSON object from the AI response."}


def parse_mt5_data_to_report(mt5_data: SafeMT5Data) -> str:
    """
    Parses the raw MT5_DATA dictionary and generates a structured,
    machine-readable report string. The structure of the report depends
    on whether there is an open position ("management" mode) or not ("setup" mode).
    """
    positions = mt5_data.get("positions")

    if positions:
        # --- MANAGEMENT MODE REPORT ---
        # Generate the checklist for management mode. tf_data is not needed.
        checklist_dict = _generate_checklist_json(mt5_data, {})
        checklist_json = json.dumps(checklist_dict, indent=2, ensure_ascii=False)

        # Generate a concept table for context, it's still useful
        extract_dict_for_table = _generate_extract_json(mt5_data)
        concept_value_table = _generate_concept_value_table(mt5_data, extract_dict_for_table["tf"])

        # Assemble the report for management mode, omitting the setup-specific EXTRACT_JSON
        report_parts = [
            concept_value_table,
            "2) CHECKLIST_JSON:",
            checklist_json,
        ]
        return "\n".join(report_parts)
    
    else:
        # --- SETUP MODE REPORT (Original Logic) ---
        # 1. Generate the EXTRACT_JSON object first, as it pre-processes some data
        extract_dict = _generate_extract_json(mt5_data)
        
        # Pass the processed data to the concept table generator
        concept_value_table = _generate_concept_value_table(mt5_data, extract_dict["tf"])
        
        # 3. Generate the CHECKLIST_JSON, which contains the master bias
        checklist_dict = _generate_checklist_json(mt5_data, extract_dict["tf"])
        
        # Update the bias in the extract_dict to be consistent with the checklist's conclusion
        final_h1_bias = checklist_dict.get("bias_H1", "unknown")
        if "H1" in extract_dict["tf"]:
            extract_dict["tf"]["H1"]["bias"] = final_h1_bias

        checklist_json = json.dumps(checklist_dict, indent=2, ensure_ascii=False)
        
        # Re-generate extract_json string with the updated bias
        extract_json = json.dumps(extract_dict, indent=2, ensure_ascii=False)

        # Assemble the final report string
        report_parts = [
            concept_value_table,
            "2) CHECKLIST_JSON:",
            checklist_json,
            "\n3) EXTRACT_JSON:",
            extract_json,
        ]

        return "\n".join(report_parts)

def extract_seven_lines(combined_text: str):
    """
    Extracts the 7-line summary from the combined report text.
    """
    try:
        lines = [ln.strip() for ln in combined_text.strip().splitlines() if ln.strip()]
        start_idx = None
        for i, ln in enumerate(lines[:20]):
            if re.match(r"^1[\.\)\-–:]?\s*", ln) or ("Lệnh:" in ln and ln.lstrip().startswith("1")):
                start_idx = i
                break
            if "Lệnh:" in ln:
                start_idx = i
                break
        if start_idx is None:
            return None, None, False
        block = []
        j = start_idx
        while j < len(lines) and len(block) < 10:
            block.append(lines[j])
            j += 1
        picked = []
        wanted = ["Lệnh:", "Entry", "SL", "TP1", "TP2", "Lý do", "Lưu ý"]
        used = set()
        for key in wanted:
            found = None
            for ln in block:
                if ln in used:
                    continue
                if key.lower().split(":")[0] in ln.lower():
                    found = ln
                    break
            if found is None:
                idx = len(picked) + 1
                for ln in block:
                    if re.match(rf"^{idx}\s*[\.\)\-–:]", ln):
                        found = ln
                        break
            picked.append(found or f"{len(picked)+1}. (thiếu)")
            used.add(found)
        l1 = picked[0].lower()
        high = ("lệnh:" in l1) and (("mua" in l1) or ("bán" in l1)) and ("không có setup" not in l1) and ("theo dõi lệnh hiện tại" not in l1)
        sig = hashlib.sha1(("|".join(picked)).encode("utf-8")).hexdigest()
        return picked, sig, high
    except Exception:
        return None, None, False
