from __future__ import annotations

import hashlib
import json
import re
import math
from typing import Any, Tuple


def repair_json_string(s: str) -> str:
    """
    Attempts to repair a JSON string that has unescaped newlines or quotes in its values.
    """
    in_string = False
    escaped = False
    new_s = []
    for char in s:
        if char == '"' and not escaped:
            in_string = not in_string
        
        # If we are inside a string, we need to escape special characters
        if in_string:
            if char == '\n':
                new_s.append('\\n')
                continue
            if char == '\r':
                continue # Skip carriage returns

        new_s.append(char)

        # Track whether the next character is escaped
        if char == '\\' and not escaped:
            escaped = True
        else:
            escaped = False
            
    return "".join(new_s)


def find_balanced_json_after(text: str, start_idx: int) -> Tuple[str | None, int | None]:
    depth, i = 0, start_idx
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


def extract_json_block_prefer(text: str) -> dict | None:
    fence = re.findall(r"```json\s*(\{[\s\S]*?\})\s*```", text, flags=re.IGNORECASE)
    for blob in fence:
        try:
            return json.loads(repair_json_string(blob), strict=False)
        except Exception:
            pass

    keywords = ["CHECKLIST_JSON", "MANAGEMENT_JSON", "EXTRACT_JSON", "setup", "trade", "signal"]
    lowered = text.lower()
    for kw in keywords:
        idx = lowered.find(kw.lower())
        if idx >= 0:
            brace = text.find("{", idx)
            if brace >= 0:
                js, _ = find_balanced_json_after(text, brace)
                if js:
                    try:
                        return json.loads(repair_json_string(js), strict=False)
                    except Exception:
                        pass

    first_brace = text.find("{")
    while first_brace >= 0:
        js, nxt = find_balanced_json_after(text, first_brace)
        if js:
            try:
                return json.loads(repair_json_string(js), strict=False)
            except Exception:
                pass
            first_brace = text.find("{", nxt if nxt else first_brace + 1)
        else:
            break
    return None


def coerce_setup_from_json(obj: Any) -> dict | None:
    if obj is None:
        return None

    candidates = []
    if isinstance(obj, dict):
        candidates.append(obj)
        for k in ("CHECKLIST_JSON", "EXTRACT_JSON", "setup", "trade", "signal", "proposed_plan"):
            v = obj.get(k)
            if isinstance(v, dict):
                candidates.append(v)

    def _num(x):
        if x is None: return None
        if isinstance(x, (int, float)) and math.isfinite(x): return float(x)
        if isinstance(x, str):
            xs = x.strip().replace(",", "")
            try: return float(xs)
            except Exception: return None
        return None

    def _dir(x):
        if not x: return None
        s = str(x).strip().lower()
        if s in ("long", "buy", "mua", "bull", "bullish"): return "long"
        if s in ("short", "sell", "bán", "ban", "bear", "bearish"): return "short"
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
        if d["direction"] in ("long","short") and all(d[k] is not None for k in ("entry","sl","tp1")):
            return d
    return None


def parse_float(s: str | None) -> float | None:
    if not s:
        return None
    s = re.sub(r"^\s*\d+\s*[\.\)\-–:]\s*", "", s.strip())
    nums = re.findall(r"[-+]?\d+(?:\.\d+)?", s.replace(",", ""))
    return float(nums[-1]) if nums else None


def parse_direction_from_line1(line1: str | None) -> str | None:
    if not line1:
        return None
    s = line1.lower()
    if "long" in s or "buy" in s or "mua" in s:
        return "long"
    if "short" in s or "sell" in s or "bán" in s:
        return "short"
    return None


def extract_summary_lines(text: str) -> Tuple[list[str] | None, str | None, bool]:
    """
    Extracts a 5-line or 7-line summary block from the report text.
    It identifies the block by looking for specific starting keywords.
    """
    if not text:
        return None, None, False

    lines = [ln.strip() for ln in text.splitlines()]
    start_idx = -1
    block_size = 0

    # Try to find the start of the 7-line summary (setup analysis)
    for i, ln in enumerate(lines):
        if re.match(r"^\s*(?:1\s*[\.\)]\s*)?Lệnh\s*:", ln, re.IGNORECASE):
            start_idx = i
            block_size = 7
            break

    # If not found, try to find the start of the 5-line summary (management)
    if start_idx == -1:
        for i, ln in enumerate(lines):
            if re.match(r"^\s*(?:1\s*[\.\)]\s*)?Trạng thái lệnh\s*:", ln, re.IGNORECASE):
                start_idx = i
                block_size = 5
                break

    if start_idx == -1:
        return None, None, False

    summary_lines = lines[start_idx : start_idx + block_size]
    if len(summary_lines) < block_size:
        return None, None, False  # Not a full block

    # Create a signature from the core trade parameters
    try:
        # Use lines 1-4 for signature (Entry, SL, TP1, TP2 for 7-line)
        # or lines 1-3 for 5-line (RR, Action, Reason)
        sig_text = "".join(summary_lines[1:4])
        sig = hashlib.sha1(sig_text.encode("utf-8")).hexdigest()[:16]
    except Exception:
        sig = None

    # Check for high probability keywords
    high_prob = "xác suất cao" in text.lower() or "đủ điều kiện" in text.lower()

    return summary_lines, sig, high_prob


def parse_ai_response(text: str) -> dict:
    """
    Parses the full AI response to find the primary JSON object.
    It can be either CHECKLIST_JSON or MANAGEMENT_JSON.
    """
    if not text:
        return {"error": "Empty response text"}
    try:
        # The JSON object is expected at the very beginning of the response
        json_obj, _ = find_balanced_json_after(text, text.find("{"))
        if json_obj:
            return json.loads(repair_json_string(json_obj), strict=False)
        else:
            return {"error": "No valid JSON object found at the beginning of the response"}
    except (json.JSONDecodeError, TypeError, IndexError) as e:
        return {"error": f"Failed to parse JSON from response: {e}"}
    except Exception as e:
        return {"error": f"An unexpected error occurred during JSON parsing: {e}"}


def parse_mt5_data_to_report(safe_mt5_data: Any) -> str:
    """
    Generates a structured report from the SafeMT5Data object.
    """
    if not safe_mt5_data or not safe_mt5_data.raw:
        return "Không có dữ liệu MT5."

    data = safe_mt5_data.raw
    report_lines = []

    # --- CONCEPT_VALUE_TABLE ---
    report_lines.append("`CONCEPT_VALUE_TABLE`:")
    tbl = "| Concept                 | Value                               |\n|-------------------------|-------------------------------------|"
    report_lines.append(tbl)
    
    info = data.get("info", {})
    tick = data.get("tick", {})
    sessions = data.get("sessions_today", {})
    vol = data.get("volatility", {}).get("ATR", {})
    
    report_lines.append(f"| symbol                  | {data.get('symbol', 'N/A')}                         |")
    report_lines.append(f"| spread_current          | {info.get('spread_current', 'N/A')} points                      |")
    report_lines.append(f"| session_active          | {safe_mt5_data.get_active_session() or 'N/A'} |")
    report_lines.append(f"| volatility_regime       | {data.get('volatility_regime', 'N/A')}                     |")
    report_lines.append(f"| atr_m5_pips             | {safe_mt5_data.get_atr_pips('M5'):.2f} pips                     |")
    report_lines.append(f"| mins_to_next_killzone   | {data.get('mins_to_next_killzone', 'N/A')} mins                      |")
    report_lines.append("")

    # --- EXTRACT_JSON ---
    report_lines.append("`EXTRACT_JSON`:")
    # A simplified JSON structure is better than a complex one for the prompt
    extract = {
        "tf": {
            "H1": data.get("trend_refs", {}).get("H1", {}),
            "M15": data.get("trend_refs", {}).get("M15", {}),
            "M5": data.get("trend_refs", {}).get("M5", {}),
        },
        "key_levels_nearby": data.get("key_levels_nearby", []),
        "open_trade_monitoring": data.get("positions", []) 
    }
    report_lines.append("```json")
    report_lines.append(json.dumps(extract, indent=2, ensure_ascii=False))
    report_lines.append("```")

    return "\n".join(report_lines)

def parse_setup_from_report(text: str) -> dict:
    """
    Parses a report text to extract a standardized trade plan.
    It handles both 'CHECKLIST_JSON' (for setups) and 'MANAGEMENT_JSON' (for trades in progress).
    """
    if not text:
        return {}

    json_obj = extract_json_block_prefer(text)
    if not isinstance(json_obj, dict):
        return {}

    # --- Helper functions for coercion ---
    def _num(x):
        if x is None: return None
        if isinstance(x, (int, float)) and math.isfinite(x): return float(x)
        if isinstance(x, str):
            xs = x.strip().replace(",", "")
            try: return float(xs)
            except Exception: return None
        return None

    def _dir(x):
        if not x: return None
        s = str(x).strip().lower()
        if s in ("long", "buy", "mua", "bull", "bullish"): return "long"
        if s in ("short", "sell", "bán", "ban", "bear", "bearish"): return "short"
        return None

    # --- Logic to extract plan from different JSON structures ---
    plan = {}
    mode = json_obj.get("mode")

    if mode == "setup" and "proposed_plan" in json_obj:
        # This is from prompt_no_entry_vision.txt
        p = json_obj["proposed_plan"]
        if isinstance(p, dict):
            plan = {
                "direction": _dir(p.get("direction")),
                "entry": _num(p.get("entry")),
                "sl": _num(p.get("sl")),
                "tp1": _num(p.get("tp1")),
                "tp2": _num(p.get("tp2")),
                "status": json_obj.get("conclusions"),
                "reasoning": json_obj.get("reasoning"),
            }

    elif mode == "management":
        # This is from prompt_entry_run_vision.txt
        plan = {
            "status": json_obj.get("status"),
            "current_rr": json_obj.get("current_rr"),
            "suggested_action": json_obj.get("suggested_action"),
            "reasoning": json_obj.get("reasoning"),
            "warnings": json_obj.get("warnings"),
        }

    # Standardize TP1/TP2
    if plan.get("tp1") is None and plan.get("tp2") is not None:
        plan["tp1"] = plan["tp2"]

    return plan
