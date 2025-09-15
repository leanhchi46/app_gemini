from __future__ import annotations

import json
import re
import hashlib
from typing import Any, Optional, Tuple


def extract_seven_lines(combined_text: str):
    if not combined_text:
        return None, None, False
    lines = [ln.strip() for ln in combined_text.strip().splitlines() if ln.strip()]
    start_idx = None
    for i, ln in enumerate(lines[:20]):
        if re.match(r"^1[\.\)\--:]?\s*", ln) or ("Lệnh:" in ln and ln.lstrip().startswith("1")):
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
                if re.match(rf"^{idx}\s*[\.\)\--:]", ln):
                    found = ln
                    break
        picked.append(found or f"{len(picked)+1}. (thiếu)")
        used.add(found)
    l1 = picked[0].lower()
    high = ("lệnh:" in l1) and (("mua" in l1) or ("bán" in l1)) and ("không có setup" not in l1) and (
        "theo doi lệnh hiện tại" not in l1
    )
    sig = hashlib.sha1(("|".join(picked)).encode("utf-8")).hexdigest()
    return picked, sig, high


def find_balanced_json_after(text: str, start_idx: int):
    if start_idx < 0 or start_idx >= len(text) or text[start_idx] != "{":
        return None, None
    depth, i = 0, start_idx
    while i < len(text):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return text[start_idx : i + 1], i + 1
                except Exception:
                    return None, None
        i += 1
    return None, None


def extract_json_block_prefer(text: str):
    if not text:
        return None
    # Prefer the longest top-level {...} block
    best = None
    best_len = -1
    try:
        first_brace = text.index("{")
    except ValueError:
        return None
    js, nxt = find_balanced_json_after(text, first_brace)
    if js:
        try:
            obj = json.loads(js)
            return obj
        except Exception:
            pass
    # If first failed, scan for next possible blocks
    i = first_brace
    while i < len(text):
        try:
            brace = text.index("{", i)
        except ValueError:
            break
        js, _ = find_balanced_json_after(text, brace)
        if js and len(js) > best_len:
            best = js
            best_len = len(js)
        i = brace + 1
    if best is not None:
        try:
            return json.loads(best)
        except Exception:
            return None
    return None


def parse_float(s: Optional[str]) -> Optional[float]:
    if s is None:
        return None
    try:
        s = str(s).strip().replace(",", "")
        return float(s)
    except Exception:
        return None


def parse_direction_from_line1(line1: str) -> Optional[str]:
    if not line1:
        return None
    s = line1.lower()
    if "buy" in s or "mua" in s or "long" in s:
        return "long"
    if "sell" in s or "bán" in s or "short" in s:
        return "short"
    return None


def coerce_setup_from_json(obj: dict) -> Optional[dict]:
    if not isinstance(obj, dict):
        return None
    out = {
        "direction": None,
        "entry": None,
        "sl": None,
        "tp1": None,
        "tp2": None,
        "bias_h1": None,
        "enough": False,
    }
    chk = obj.get("setup_status") or {}
    if isinstance(chk, dict):
        out["bias_h1"] = (chk.get("bias_h1") or chk.get("bias_H1") or chk.get("bias_h1_h1"))
        concl = (chk.get("conclusions") or "").upper()
        out["enough"] = ("D?" in concl or "DU" in concl)

    def _num(x):
        try:
            if x is None:
                return None
            return float(str(x).replace(",", "").strip())
        except Exception:
            return None

    def _dir(x):
        if not x:
            return None
        s = str(x).lower()
        if "buy" in s or "mua" in s or "long" in s:
            return "long"
        if "sell" in s or "bán" in s or "short" in s:
            return "short"
        return None

    root = obj or {}
    cands = []
    for k in ("proposed_plan", "plan", "trade", "signal", "setup"):
        if isinstance(root.get(k), dict):
            cands.append(root[k])
    for v in root.values():
        if isinstance(v, dict):
            for k in ("proposed_plan", "plan", "trade", "signal", "setup"):
                if isinstance(v.get(k), dict):
                    cands.append(v[k])
    for c in cands:
        d = {
            "direction": _dir(c.get("direction") or c.get("dir") or c.get("side")),
            "entry": _num(c.get("entry") or c.get("price") or c.get("ep")),
            "sl": _num(c.get("sl") or c.get("stop") or c.get("stop_loss")),
            "tp1": _num(c.get("tp1") or c.get("tp_1") or c.get("take_profit_1") or c.get("tp")),
            "tp2": _num(c.get("tp2") or c.get("tp_2") or c.get("take_profit_2")),
        }
        if d["tp1"] is None and d["tp2"] is not None:
            d["tp1"] = d["tp2"]
        if d["direction"] in ("long", "short") and all(d[k] is not None for k in ("entry", "sl", "tp1")):
            out.update(d)
            return out
    return None


def parse_setup_from_report(text: str) -> dict:
    out = {
        "direction": None,
        "entry": None,
        "sl": None,
        "tp1": None,
        "tp2": None,
        "bias_h1": None,
        "enough": False,
    }
    obj = extract_json_block_prefer(text)
    if obj:
        co = coerce_setup_from_json(obj)
        if co:
            out.update(co)
            return out

    lines_sig = None
    try:
        lines, lines_sig, _ = extract_seven_lines(text)
    except Exception:
        lines = None
    if lines:
        out["direction"] = parse_direction_from_line1(lines[0])

        def _lastnum(s):
            if not s:
                return None
            s = re.sub(r"^\s*\d+\s*[\.\)\--:]\s*", "", s.strip())
            nums = re.findall(r"[-+]?\d+(?:\.\d+)?", s.replace(",", ""))
            return float(nums[-1]) if nums else None

        out["entry"] = _lastnum(lines[1] if len(lines) > 1 else None)
        out["sl"] = _lastnum(lines[2] if len(lines) > 2 else None)
        out["tp1"] = _lastnum(lines[3] if len(lines) > 3 else None)
        out["tp2"] = _lastnum(lines[4] if len(lines) > 4 else None)
    return out

