# -*- coding: utf-8 -*-
import re
import json
import math

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
