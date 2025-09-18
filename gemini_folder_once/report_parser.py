from __future__ import annotations

import hashlib
import json
import re
import math
from typing import Any, Tuple


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
            return json.loads(blob)
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
                        return json.loads(js)
                    except Exception:
                        pass

    first_brace = text.find("{")
    while first_brace >= 0:
        js, nxt = find_balanced_json_after(text, first_brace)
        if js:
            try:
                return json.loads(js)
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


def extract_seven_lines(text: str) -> Tuple[list[str] | None, str | None, bool]:
    if not text:
        return None, None, False
    
    lines = [ln.strip() for ln in text.splitlines()]
    
    # Find the start of the 7-line summary
    start_idx = -1
    for i, ln in enumerate(lines):
        # Match patterns like "1. Lệnh:", "1) Lệnh", "Lệnh:"
        if re.match(r"^\s*(?:1\s*[\.\)]\s*)?Lệnh\s*:", ln, re.IGNORECASE):
            start_idx = i
            break
            
    if start_idx == -1:
        return None, None, False
        
    # Extract the 7 lines
    seven_lines = lines[start_idx : start_idx + 7]
    if len(seven_lines) < 7:
        return None, None, False # Not a full block

    # Create a signature from the core trade parameters
    try:
        sig_text = "".join(seven_lines[1:5]) # Entry, SL, TP1, TP2
        sig = hashlib.sha1(sig_text.encode("utf-8")).hexdigest()[:16]
    except Exception:
        sig = None

    # Check for high probability keywords
    high_prob = "xác suất cao" in text.lower() or "đủ điều kiện" in text.lower()

    return seven_lines, sig, high_prob


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
            return json.loads(json_obj)
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

def parse_setup_from_report(text: str):
    out = {
        "direction": None, "entry": None, "sl": None, "tp1": None, "tp2": None,
        "bias_h1": None, "enough": False
    }
    if not text:
        return out

    obj = extract_json_block_prefer(text)

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
        if s in ("long","buy","mua","bull","bullish"): return "long"
        if s in ("short","sell","bán","ban","bear","bearish"): return "short"
        return None

    def _pick_from_json(root):
        if not isinstance(root, dict): return None

        chk = root.get("CHECKLIST_JSON") or root.get("checklist") or root
        if isinstance(chk, dict) and ("setup_status" in chk or "conclusions" in chk):
            out["bias_h1"] = (chk.get("bias_H1") or chk.get("bias_h1") or "").lower() or out["bias_h1"]
            concl = (chk.get("conclusions") or "").upper()
            out["enough"] = out["enough"] or ("ĐỦ" in concl or "DU" in concl)

        cands = []
        for k in ("proposed_plan","plan","trade","signal","setup"):
            if isinstance(root.get(k), dict):
                cands.append(root[k])

        for v in root.values():
            if isinstance(v, dict):
                for k in ("proposed_plan","plan","trade","signal","setup"):
                    if isinstance(v.get(k), dict):
                        cands.append(v[k])
        for c in cands:
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

    plan = _pick_from_json(obj) if obj else None
    if plan:
        out.update(plan)
        return out

    lines, _, _ = extract_seven_lines(text)
    if lines:
        out["direction"] = parse_direction_from_line1(lines[0])
        out["entry"] = parse_float(lines[1] if len(lines)>1 else None)
        out["sl"]    = parse_float(lines[2] if len(lines)>2 else None)
        out["tp1"]   = parse_float(lines[3] if len(lines)>3 else None)
        out["tp2"]   = parse_float(lines[4] if len(lines)>4 else None)
    return out
