from __future__ import annotations

import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _points_per_pip_from_info(info: dict) -> int:
    try:
        d = int((info or {}).get("digits") or 0)
    except Exception:
        d = 0
    return 10 if d >= 3 else 1


def _pip_size_from_info(info: dict) -> float:
    point = float((info or {}).get("point") or 0.0)
    ppp = _points_per_pip_from_info(info)
    return point * ppp if point else 0.0


def parse_ctx_json_files(reports_dir: Path, max_n: int = 5) -> list[dict]:
    if not reports_dir:
        return []
    files = sorted(reports_dir.glob("ctx_*.json"), reverse=True)[: max(1, int(max_n))]
    out: list[dict] = []
    for p in files:
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            continue
    return out


def summarize_checklist_trend(ctx_items: list[dict]) -> dict:
    if not ctx_items:
        return {"trend": "unknown", "enough_ratio": None}
    order = ["A", "B", "C", "D", "E", "F"]
    scores = {"D?": 2, "CH?": 1, "SAI": 0}
    seq: list[int] = []
    enough_cnt = 0
    total = 0
    for it in ctx_items:
        setup = it.get("blocks") or []
        setup_json = None
        for blk in setup:
            try:
                obj = json.loads(blk)
                if isinstance(obj, dict) and "setup_status" in obj:
                    setup_json = obj
                    break
            except Exception:
                pass
        if not setup_json:
            continue
        st = setup_json.get("setup_status", {})
        val = sum(scores.get(st.get(k, ""), 0) for k in order)
        seq.append(val)
        concl = setup_json.get("conclusions", "")
        if isinstance(concl, str) and "D?" in concl.upper():
            enough_cnt += 1
        total += 1
    if len(seq) < 2:
        return {"trend": "flat", "enough_ratio": (enough_cnt / total if total else None)}
    delta = seq[-1] - seq[0]
    trend = "improving" if delta > 0 else ("deteriorating" if delta < 0 else "flat")
    return {"trend": trend, "enough_ratio": (enough_cnt / total if total else None)}


def images_tf_map(names: list[str], detect_cb) -> dict:
    out = {}
    for n in names:
        try:
            out[n] = detect_cb(n) if detect_cb else None
        except Exception:
            out[n] = None
    return out


def folder_signature(names: list[str]) -> str:
    names = sorted(list(names or []))
    if not names:
        return ""
    sig = hashlib.sha1("\n".join(names).encode("utf-8")).hexdigest()
    return f"sha1:{sig}" if sig else ""


def compose_context(app, cfg, budget_chars: int = 1800) -> str:
    """Build context JSON string (trimmed to budget) using app helpers and cfg.

    This function intentionally depends on the UI app instance for data access
    (reports dir, MT5 helpers, image names, logging), while concentrating the
    assembly and slimming logic here.
    """
    mt5_ctx_lite: dict | None = {}
    mt5_flags: dict | None = {}
    mt5full = None

    # Load previous context jsons and derive trend/plan
    ctx_items = parse_ctx_json_files(app._get_reports_dir(folder_override=cfg.folder), max_n=cfg.ctx_json_n)
    trend = summarize_checklist_trend(ctx_items)

    latest_7 = None
    plan = None
    latest_blocks = None
    if ctx_items:
        latest = ctx_items[0]
        latest_7 = latest.get("seven_lines")
        latest_blocks = latest.get("blocks") or []
        for blk in latest_blocks:
            try:
                o = json.loads(blk)
                if isinstance(o, dict) and "proposed_plan" in o:
                    plan = o.get("proposed_plan")
                    break
            except Exception:
                pass

    mt5_ctx_full_text = ""
    if cfg.mt5_enabled:
        try:
            mt5_ctx_full_text = app._mt5_build_context(plan=plan, cfg=cfg)
            if mt5_ctx_full_text:
                mt5full = (json.loads(mt5_ctx_full_text) or {}).get("MT5_DATA", {})
                info = (mt5full.get("info") or {})
                tick = (mt5full.get("tick") or {})
                volATR = ((mt5full.get("volatility") or {}).get("ATR") or {})
                stats5 = (mt5full.get("tick_stats_5m") or {})
                key_near = mt5full.get("key_levels_nearby") or []
                pip_size = _pip_size_from_info(info)
                cp = tick.get("bid") or tick.get("last")
                atr_m5 = volATR.get("M5")
                tpm = stats5.get("ticks_per_min")
                dist_pdh = next((x.get("distance_pips") for x in key_near if x.get("name") == "PDH"), None)
                dist_pdl = next((x.get("distance_pips") for x in key_near if x.get("name") == "PDL"), None)
                dist_eq = next((x.get("distance_pips") for x in key_near if x.get("name") == "EQ50_D"), None)
                session_name = None
                ss = mt5full.get("sessions_today") or {}
                now_hhmm = datetime.now().strftime("%H:%M")
                for k in ["asia", "london", "newyork_pre", "newyork_post"]:
                    rng = ss.get(k) or {}
                    if rng.get("start") and rng.get("end") and rng["start"] <= now_hhmm < rng["end"]:
                        session_name = k
                        break
                mt5_ctx_lite = {
                    "symbol": mt5full.get("symbol"),
                    "current_price": cp,
                    "spread_points": info.get("spread_current"),
                    "atr_m5_pips": (atr_m5 / pip_size) if (atr_m5 and pip_size) else None,
                    "ticks_per_min": tpm,
                    "pdh_pdl_distance_pips": {"PDH": dist_pdh, "PDL": dist_pdl},
                    "eq50_d_distance_pips": dist_eq,
                    "session_active": session_name,
                    "mins_to_next_killzone": mt5full.get("mins_to_next_killzone"),
                }

                spread_cur = info.get("spread_current")
                p90 = stats5.get("p90_spread")
                low_liq_thr = int(cfg.nt_min_ticks_per_min)
                high_spread = (
                    spread_cur is not None and p90 is not None and spread_cur > p90 * float(cfg.nt_spread_factor)
                )
                low_liquidity = (tpm is not None and tpm < low_liq_thr)
                vol_reg = mt5full.get("volatility_regime")
                emaM5 = (((mt5full.get("trend_refs") or {}).get("EMA") or {}).get("M5") or {})
                ema50 = emaM5.get("ema50")
                ema200 = emaM5.get("ema200")
                atr_m5_safe = atr_m5 if atr_m5 is not None else 0
                trending = (ema50 is not None and ema200 is not None and atr_m5_safe) and (
                    abs(ema50 - ema200) > (atr_m5_safe * 0.2)
                )
                mt5_flags = {
                    "news_soon": False,
                    "high_spread": bool(high_spread),
                    "low_liquidity": bool(low_liquidity),
                    "volatility_regime": vol_reg,
                    "trend_regime": "trending" if trending else "choppy",
                }
        except Exception:
            mt5_ctx_full_text = ""

    try:
        file_names = [Path(r["path"]).name for r in getattr(app, "results", []) if r.get("path")]
    except Exception:
        file_names = []
    images_map = images_tf_map(file_names, getattr(app, "_detect_timeframe_from_name", None))
    run_meta = {
        "analysis_id": datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        "folder_signature": folder_signature(file_names),
        "images_tf_map": images_map,
    }

    pass_cnt = 0
    total = 0
    for it in ctx_items:
        blks = it.get("blocks") or []
        for blk in blks:
            try:
                o = json.loads(blk)
                if isinstance(o, dict) and "setup_status" in o:
                    concl = (o.get("conclusions") or "").upper()
                    total += 1
                    pass_cnt += 1 if ("D?" in concl or "DU" in concl) else 0
                    break
            except Exception:
                continue
    stats5 = (mt5full.get("tick_stats_5m") if mt5full else None) or {}
    running_stats = {
        "checklist_pass_ratio": (pass_cnt / total if total else None),
        "hit_rate_high_prob": None,
        "avg_rr_tp1": None,
        "median_spread": stats5.get("median_spread"),
        "median_ticks_per_min": stats5.get("ticks_per_min"),
    }

    risk_rules = {
        "max_risk_per_trade_pct": float(cfg.trade_equity_risk_pct),
        "daily_loss_limit_pct": 3.0,
        "max_trades_per_day": 3,
        "allowed_killzones": ["london", "newyork_pre", "newyork_post"],
        "news_blackout_min_before_after": 15,
    }

    composed = {
        "CONTEXT_COMPOSED": {
            "cycle": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "session": mt5_ctx_lite.get("session_active") if isinstance(mt5_ctx_lite, dict) else None,
            "trend_checklist": trend,
            "latest_plan": plan,
            "latest_7_lines": latest_7,
            "run_meta": run_meta,
            "running_stats": running_stats,
            "risk_rules": risk_rules,
            "environment_flags": mt5_flags or None,
            "mt5": (mt5full if mt5full else None),
            "mt5_lite": (mt5_ctx_lite or None),
        }
    }

    # Optional: log decision start
    try:
        app._log_trade_decision(
            {
                "stage": "run-start",
                "t": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                **(composed.get("CONTEXT_COMPOSED") or {}),
            },
            folder_override=(app.mt5_symbol_var.get().strip() or None),
        )
    except Exception:
        pass

    text = json.dumps(composed, ensure_ascii=False)
    if len(text) <= budget_chars:
        return text

    try:
        slim = composed["CONTEXT_COMPOSED"]
        slim["mt5"] = None
        text = json.dumps(composed, ensure_ascii=False)
        if len(text) > budget_chars:
            slim["latest_7_lines"] = (slim.get("latest_7_lines") or [])[:3]
            text = json.dumps(composed, ensure_ascii=False)
    except Exception:
        pass
    return text[:budget_chars]
