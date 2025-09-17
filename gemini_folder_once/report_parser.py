from __future__ import annotations
import json
from typing import Any

def _generate_extract_json(data: dict[str, Any]) -> dict[str, Any]:
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
    cp = data.get("tick", {}).get("bid") or data.get("tick", {}).get("last") or 0.0
    ict_patterns = data.get("ict_patterns", {})

    # Process available timeframes (H1, M15)
    for tf_str, tf_key in [("H1", "h1"), ("M15", "m15")]:
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

    # Add empty placeholders for M5 and M1 as per the user's format
    for tf_str in ["M5", "M1"]:
        extract_dict["tf"][tf_str] = {
            "current_price": cp, "bias": "unknown", "swing": {"H": None, "L": None},
            "premium_discount": {}, "liquidity": {"BSL": [], "SSL": [], "EQH": [], "EQL": []},
            "OB": [], "FVG": [], "BPR": []
        }

    # Populate risk_reward from 'rr_projection'
    rr_projection = data.get("rr_projection", {})
    plan = data.get("plan", {})  # A plan might be passed in the context
    extract_dict["risk_reward"] = {
        "entry": plan.get("entry"),
        "sl": plan.get("sl"),
        "tp1": plan.get("tp1"),
        "tp2": plan.get("tp2"),
        "rr_tp1": rr_projection.get("tp1_rr")
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


def _generate_concept_value_table(data: dict[str, Any]) -> str:
    """Helper to build the CONCEPT_VALUE_TABLE part of the report."""
    cp = data.get("tick", {}).get("bid") or data.get("tick", {}).get("last") or 0.0
    point = data.get("info", {}).get("point", 0.0)
    pip_size = (data.get("pip", {}).get("value_per_point", 0.0) / (data.get("pip", {}).get("points_per_pip", 1) or 1)) if point else 0.0

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
    h1_swing_h = data.get("tf_data", {}).get("H1", {}).get("swing", {}).get("H")
    h1_swing_l = data.get("tf_data", {}).get("H1", {}).get("swing", {}).get("L")
    rows.append(format_row("H1", "Current Price", cp))
    rows.append(format_row("H1", "Swing High", h1_swing_h))
    rows.append(format_row("H1", "Swing Low", h1_swing_l))
    rows.append(format_row("H1", "EQ50_D", (data.get("levels", {}).get("daily") or {}).get("eq50")))
    rows.append(format_row("H1", "Daily VWAP", (data.get("vwap") or {}).get("day")))
    rows.append(format_row("H1", "PDL", (data.get("levels", {}).get("prev_day") or {}).get("low")))
    rows.append(format_row("H1", "PDH", (data.get("levels", {}).get("prev_day") or {}).get("high")))
    rows.append(format_row("H1", "EMA50", ((data.get("trend_refs", {}).get("EMA") or {}).get("H1") or {}).get("ema50")))

    # M15 Concepts
    m15_swing_h = data.get("tf_data", {}).get("M15", {}).get("swing", {}).get("H")
    m15_swing_l = data.get("tf_data", {}).get("M15", {}).get("swing", {}).get("L")
    rows.append(format_row("M15", "Current Price", cp))
    rows.append(format_row("M15", "Swing High", m15_swing_h))
    rows.append(format_row("M15", "Swing Low", m15_swing_l))

    # Filter out None rows before joining
    return "\n".join(filter(None, rows))


def _generate_checklist_json(data: dict[str, Any], tf_data: dict) -> dict[str, Any]:
    """
    Helper to build the CHECKLIST_JSON part of the report, following the detailed ICT prompt.
    """
    from datetime import datetime

    cp = data.get("tick", {}).get("bid", 0.0)
    setup_status = {}
    
    # --- A: Identity & Consistency ---
    setup_status["A1"] = "ĐỦ" # Assuming 4 images are of the same asset
    setup_status["A2"] = "ĐỦ" # Assuming no open trade is detected (logic to be added)

    # --- B: HTF Bias (H1) ---
    h1_mss = data.get("ict_patterns", {}).get("mss_h1", {})
    h1_pd_info = data.get("ict_patterns", {}).get("premium_discount_h1", {})
    h1_liquidity = tf_data.get("H1", {}).get("liquidity", {})
    h1_fvgs = data.get("ict_patterns", {}).get("fvgs_h1", [])
    
    # B1: Bias by BOS/CHoCH
    h1_bias_signal = h1_mss.get("signal")
    setup_status["B1"] = "ĐỦ" if h1_bias_signal in ["bullish", "bearish"] else "SAI"
    
    # B2: HTF Liquidity Target
    if h1_bias_signal == "bullish" and h1_liquidity.get("BSL"):
        setup_status["B2"] = "ĐỦ"
    elif h1_bias_signal == "bearish" and h1_liquidity.get("SSL"):
        setup_status["B2"] = "ĐỦ"
    else:
        setup_status["B2"] = "CHỜ"

    # B3: Premium/Discount Alignment
    h1_pd_status = h1_pd_info.get("status")
    if h1_bias_signal == "bullish" and h1_pd_status == "discount":
        setup_status["B3"] = "ĐỦ"
    elif h1_bias_signal == "bearish" and h1_pd_status == "premium":
        setup_status["B3"] = "ĐỦ"
    else:
        setup_status["B3"] = "CHỜ"

    # B4: Displacement Confirmation
    if h1_bias_signal != "neutral" and h1_mss.get("start_time"):
        # Check for strong FVG after the market structure shift
        displacement_fvg_found = False
        for fvg in h1_fvgs:
            if fvg["start_time"] > h1_mss["start_time"]:
                if (h1_bias_signal == "bullish" and fvg["dir"] == "up") or \
                   (h1_bias_signal == "bearish" and fvg["dir"] == "down"):
                    displacement_fvg_found = True
                    break
        setup_status["B4"] = "ĐỦ" if displacement_fvg_found else "CHỜ"
    else:
        setup_status["B4"] = "CHỜ"
        
    final_h1_bias = h1_bias_signal if setup_status["B1"] == "ĐỦ" else "sideways"

    # --- C: MTF POI (M15) ---
    best_poi_info = _find_best_m15_poi(data, tf_data, final_h1_bias)
    poi_details = best_poi_info["details"]
    setup_status["C1"] = "ĐỦ" if poi_details["type"] != "None" else "SAI"
    setup_status["C2"] = "ĐỦ" if best_poi_info["has_confluence"] else "CHỜ"
    
    # C3: Price in POI
    try:
        if poi_details["type"] != "None":
            zone_parts = poi_details["price_zone"].split('-')
            lo, hi = float(zone_parts[0]), float(zone_parts[1])
            # Price is considered "near" if it's within a small range of the POI
            if (lo - 0.1 * (hi-lo)) <= cp <= (hi + 0.1 * (hi-lo)):
                setup_status["C3"] = "ĐỦ"
            else:
                setup_status["C3"] = "CHỜ"
        else:
            setup_status["C3"] = "SAI"
    except Exception:
        setup_status["C3"] = "CHỜ"

    # C4: POI in High-Prob Session
    killzone_active = data.get("killzone_active")
    setup_status["C4"] = "ĐỦ" if killzone_active in ["london", "newyork_am"] else "CHỜ"

    # --- D, E, F: Placeholders ---
    setup_status.update({"D1": "CHỜ", "D2": "CHỜ", "D3": "CHỜ", "D4": "CHỜ"})
    setup_status.update({"E1": "CHỜ", "E2": "CHỜ", "E3": "CHỜ", "E4": "CHỜ"})
    
    # F1, F2 are assumed true for now. F3 depends on news data.
    setup_status.update({"F1": "ĐỦ", "F2": "ĐỦ"})
    news_analysis = data.get("news_analysis", {})
    if news_analysis.get("is_in_news_window"):
        setup_status["F3"] = "SAI"
    else:
        setup_status["F3"] = "ĐỦ"

    # --- D, E: LTF Entry Model ---
    # Only analyze LTF if the HTF/MTF setup is valid
    core_conditions_met = all(setup_status.get(k) == "ĐỦ" for k in ["A1", "A2", "B1", "B2", "B3", "B4", "C1", "C2", "C3", "C4", "F3"])
    if core_conditions_met:
        ltf_status = _analyze_ltf_entry_model(data, final_h1_bias)
        setup_status.update(ltf_status)
    else:
        # Keep LTF statuses as CHỜ if HTF setup is not ready
        setup_status.update({"D1": "CHỜ", "D2": "CHỜ", "D3": "CHỜ", "D4": "CHỜ"})
        setup_status.update({"E1": "CHỜ", "E2": "CHỜ", "E3": "CHỜ", "E4": "CHỜ"})


    # --- Dynamic Conclusion ---
    conclusions, missing_conditions = _get_conclusion_from_status(setup_status)

    # --- Final Assembly ---
    plan = data.get("plan", {})
    checklist = {
        "cycle": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "symbol": data.get("symbol", "unknown"),
        "mode": "setup",
        "bias_H1": final_h1_bias,
        "poi_M15": poi_details,
        "setup_status": setup_status,
        "conclusions": conclusions,
        "missing_conditions": missing_conditions,
        "proposed_plan": {
            "direction": plan.get("direction", "null"),
            "entry": plan.get("entry"), "sl": plan.get("sl"),
            "tp1": plan.get("tp1"), "tp2": plan.get("tp2")
        }
    }
    return checklist

def _is_poi_fresh(poi_zone: dict, series_after: list) -> bool:
    """Checks if a POI has been touched by subsequent price action."""
    if not series_after:
        return True
    poi_lo, poi_hi = poi_zone["lo"], poi_zone["hi"]
    for candle in series_after:
        if candle["low"] <= poi_hi and candle["high"] >= poi_lo:
            return False  # Price has touched or gone through the POI
    return True

def _find_best_m15_poi(data: dict, tf_data: dict, h1_bias: str) -> dict:
    """Finds and scores the best M15 POI based on confluence."""
    cp = data.get("tick", {}).get("bid", 0.0)
    m15_series = data.get("series", {}).get("M15", [])
    sessions = data.get("sessions_today", {})
    killzones = {k: v for k, v in sessions.items() if "newyork" in k or "london" in k}

    potential_pois = []
    m15_fvgs = tf_data.get("M15", {}).get("FVG", [])
    m15_obs = tf_data.get("M15", {}).get("OB", [])
    h1_fvgs = tf_data.get("H1", {}).get("FVG", [])
    h1_obs = tf_data.get("H1", {}).get("OB", [])

    for fvg in m15_fvgs: potential_pois.append({"type": "FVG", "zone": fvg, "score": 0})
    for ob in m15_obs: potential_pois.append({"type": "OB", "zone": ob, "score": 0})

    h1_pd_status = data.get("ict_patterns", {}).get("premium_discount_h1", {}).get("status")
    
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

def _get_conclusion_from_status(setup_status: dict) -> tuple[str, list[str]]:
    """Generates conclusion and missing conditions from the setup status dict."""
    condition_map = {
        "A1": "Asset/TF Identity", "A2": "No Open Trade",
        "B1": "H1 Bias by Structure", "B2": "HTF Liquidity Target", "B3": "P/D Alignment", "B4": "Displacement Confirmation",
        "C1": "Valid M15 POI", "C2": "POI Confluence", "C3": "Price in/near POI", "C4": "POI in High-Prob Session",
        "D1": "LTF Inducement/Sweep", "D2": "LTF CHoCH/BOS", "D3": "LTF Displacement", "D4": "Refined Entry Zone",
        "E1": "M1 Trigger Shift", "E2": "Pullback to M1 Zone", "E3": "Valid SL/TP", "E4": "RR >= 1:2",
        "F1": "Trade Management Plan", "F2": "No H1 Invalidation", "F3": "News/Session Check"
    }
    
    if any(v == "SAI" for v in setup_status.values()):
        conclusion = "SAI"
        missing = [f"{condition_map.get(k)} is invalid" for k, v in setup_status.items() if v == "SAI"]
        return conclusion, missing

    # Check core conditions for a valid, high-probability setup before LTF entry
    core_conditions = ["A1", "A2", "B1", "B2", "B3", "B4", "C1", "C2", "C3", "C4", "F3"]
    if all(setup_status.get(k) == "ĐỦ" for k in core_conditions):
        conclusion = "ĐỦ" # Sufficient for high-level setup, pending M1 trigger
        missing = [f"Waiting for {condition_map.get(k)}" for k, v in setup_status.items() if v == "CHỜ" and k.startswith(('D', 'E'))]
    else:
        conclusion = "CHƯA ĐỦ"
        missing = [f"Waiting for {condition_map.get(k)}" for k, v in setup_status.items() if v == "CHỜ"]
        
    return conclusion, missing


def parse_mt5_data_to_report(mt5_data: dict[str, Any]) -> str:
    """
    Parses the raw MT5_DATA dictionary and generates a structured,
    machine-readable report string containing CONCEPT_VALUE_TABLE,
    CHECKLIST_JSON, and EXTRACT_JSON.

    Args:
        mt5_data: The dictionary containing all the MT5 data.

    Returns:
        A formatted string containing the full report.
    """
    # 1. Generate the EXTRACT_JSON object first, as it pre-processes some data
    extract_dict = _generate_extract_json(mt5_data)
    
    # Pass the processed data to the concept table generator
    concept_value_table = _generate_concept_value_table({**mt5_data, "tf_data": extract_dict["tf"]})
    
    extract_json = json.dumps(extract_dict, indent=2, ensure_ascii=False)

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
