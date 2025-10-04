from __future__ import annotations

import json
import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.utils import mt5_utils
from . import backtester
from . import vectorizer
from src.utils import report_parser

logger = logging.getLogger(__name__) # Khởi tạo logger


"""
Note: MT5 info helpers are centralized in src.utils.mt5_utils and
accept both dicts (our JSON schema) and MT5 objects. Import and reuse them
here to avoid divergence.
"""


def parse_proposed_trades_file(reports_dir: Path) -> list[dict]:
    """
    Phân tích file 'proposed_trades.jsonl' để lấy danh sách các giao dịch được đề xuất.

    Args:
        reports_dir: Đường dẫn đến thư mục chứa file log.

    Returns:
        Danh sách các từ điển, mỗi từ điển đại diện cho một giao dịch được đề xuất.
        Trả về danh sách rỗng nếu file không tồn tại hoặc có lỗi khi parse.
    """
    logger.debug(f"Bắt đầu hàm parse_proposed_trades_file từ thư mục: {reports_dir}")
    if not reports_dir:
        logger.debug("reports_dir trống, trả về list rỗng.")
        logger.debug("Kết thúc hàm parse_proposed_trades_file (thư mục trống).")
        return []
    log_file = reports_dir / "proposed_trades.jsonl"
    if not log_file.exists():
        logger.debug(f"File log {log_file} không tồn tại.")
        return []
    
    trades = []
    try:
        with open(log_file, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    trades.append(json.loads(line))
        logger.debug(f"Đã parse {len(trades)} trades từ {log_file}.")
    except Exception as e:
        logger.error(f"Lỗi khi parse proposed_trades.jsonl: {e}")
        logger.debug("Kết thúc hàm parse_proposed_trades_file (lỗi parse).")
        return [] # Trả về danh sách rỗng nếu có lỗi khi parse
    logger.debug("Kết thúc hàm parse_proposed_trades_file.")
    return trades


def parse_vector_database_file(reports_dir: Path) -> list[dict]:
    """
    Phân tích file 'vector_database.jsonl' để lấy danh sách các vector trạng thái thị trường.

    Args:
        reports_dir: Đường dẫn đến thư mục chứa file log.

    Returns:
        Danh sách các từ điển, mỗi từ điển đại diện cho một vector trạng thái thị trường.
        Trả về danh sách rỗng nếu file không tồn tại hoặc có lỗi khi parse.
    """
    logger.debug(f"Bắt đầu hàm parse_vector_database_file từ thư mục: {reports_dir}")
    if not reports_dir:
        logger.debug("reports_dir trống, trả về list rỗng.")
        logger.debug("Kết thúc hàm parse_vector_database_file (thư mục trống).")
        return []
    log_file = reports_dir / "vector_database.jsonl"
    if not log_file.exists():
        logger.debug(f"File log {log_file} không tồn tại.")
        return []
    
    vectors = []
    try:
        with open(log_file, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    vectors.append(json.loads(line))
        logger.debug(f"Đã parse {len(vectors)} vectors từ {log_file}.")
    except Exception as e:
        logger.error(f"Lỗi khi parse vector_database.jsonl: {e}")
        logger.debug("Kết thúc hàm parse_vector_database_file (lỗi parse).")
        return []
    logger.debug("Kết thúc hàm parse_vector_database_file.")
    return vectors


def parse_ctx_json_files(reports_dir: Path, max_n: int = 5) -> list[dict]:
    """
    Phân tích các file ngữ cảnh JSON (ctx_*.json) từ một thư mục.

    Args:
        reports_dir: Đường dẫn đến thư mục chứa các file ngữ cảnh.
        max_n: Số lượng file ngữ cảnh tối đa cần đọc (mới nhất).

    Returns:
        Danh sách các từ điển, mỗi từ điển đại diện cho một ngữ cảnh đã parse.
    """
    logger.debug(f"Bắt đầu hàm parse_ctx_json_files từ thư mục: {reports_dir}, max_n: {max_n}")
    if not reports_dir:
        logger.debug("reports_dir trống, trả về list rỗng.")
        logger.debug("Kết thúc hàm parse_ctx_json_files (thư mục trống).")
        return []
    files = sorted(reports_dir.glob("ctx_*.json"), reverse=True)[: max(1, int(max_n))]
    out: list[dict] = []
    for p in files:
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
            logger.debug(f"Đã parse file context: {p.name}")
        except Exception as e:
            logger.warning(f"Lỗi khi parse file context {p.name}: {e}")
            continue
    logger.debug(f"Đã parse {len(out)} file context.")
    logger.debug("Kết thúc hàm parse_ctx_json_files.")
    return out


def summarize_checklist_trend(ctx_items: list[dict]) -> dict:
    """
    Tóm tắt xu hướng từ các mục checklist trong ngữ cảnh lịch sử.

    Args:
        ctx_items: Danh sách các từ điển ngữ cảnh lịch sử.

    Returns:
        Một từ điển chứa xu hướng ("improving", "deteriorating", "flat", "unknown")
        và tỷ lệ "enough" (D? hoặc DU).
    """
    logger.debug(f"Bắt đầu hàm summarize_checklist_trend với {len(ctx_items)} items.")
    if not ctx_items:
        logger.debug("ctx_items trống, trả về trend unknown.")
        logger.debug("Kết thúc hàm summarize_checklist_trend (không có items).")
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
        logger.debug("Chỉ có 1 hoặc 0 item trong sequence, trend là flat.")
        logger.debug("Kết thúc hàm summarize_checklist_trend (sequence quá ngắn).")
        return {"trend": "flat", "enough_ratio": (enough_cnt / total if total else None)}
    delta = seq[-1] - seq[0]
    trend = "improving" if delta > 0 else ("deteriorating" if delta < 0 else "flat")
    logger.debug(f"Kết thúc hàm summarize_checklist_trend. Trend: {trend}, Enough Ratio: {enough_cnt / total if total else None}")
    return {"trend": trend, "enough_ratio": (enough_cnt / total if total else None)}


def images_tf_map(names: list[str], detect_cb: Any) -> dict:
    """
    Tạo một bản đồ khung thời gian cho các tên tệp hình ảnh.

    Args:
        names: Danh sách các tên tệp hình ảnh.
        detect_cb: Hàm callback để phát hiện khung thời gian từ tên tệp.

    Returns:
        Một từ điển ánh xạ tên tệp hình ảnh tới khung thời gian của nó.
    """
    logger.debug(f"Bắt đầu hàm images_tf_map với {len(names)} tên ảnh.")
    out = {}
    for n in names:
        try:
            out[n] = detect_cb(n) if detect_cb else None
            logger.debug(f"Đã phát hiện timeframe cho ảnh '{n}': {out[n]}")
        except Exception as e:
            out[n] = None
            logger.warning(f"Lỗi khi phát hiện timeframe cho ảnh '{n}': {e}")
    logger.debug("Kết thúc hàm images_tf_map.")
    return out


def folder_signature(names: list[str]) -> str:
    """
    Tạo chữ ký SHA1 cho một danh sách các tên tệp.

    Args:
        names: Danh sách các tên tệp.

    Returns:
        Chuỗi chữ ký SHA1.
    """
    logger.debug(f"Bắt đầu hàm folder_signature với {len(names)} tên ảnh.")
    names = sorted(list(names or []))
    if not names:
        logger.debug("Không có tên ảnh, trả về signature rỗng.")
        logger.debug("Kết thúc hàm folder_signature (không có tên).")
        return ""
    sig = hashlib.sha1("\n".join(names).encode("utf-8")).hexdigest()
    logger.debug(f"Đã tạo folder signature: sha1:{sig}")
    logger.debug("Kết thúc hàm folder_signature.")
    return f"sha1:{sig}" if sig else ""


def compose_context(app: Any, cfg: Any, budget_chars: int = 1800) -> str:
    """
    Xây dựng chuỗi JSON ngữ cảnh (được cắt bớt theo ngân sách) bằng cách sử dụng
    các hàm trợ giúp của ứng dụng và cấu hình.

    Hàm này cố ý phụ thuộc vào phiên bản ứng dụng UI để truy cập dữ liệu
    (thư mục báo cáo, các hàm trợ giúp MT5, tên hình ảnh, ghi log), đồng thời tập trung
    logic lắp ráp và làm gọn tại đây.

    Args:
        app: Đối tượng ứng dụng chính.
        cfg: Đối tượng cấu hình.
        budget_chars: Ngân sách ký tự tối đa cho chuỗi JSON ngữ cảnh.

    Returns:
        Chuỗi JSON ngữ cảnh đã được tạo và làm gọn.
    """
    logger.debug(f"Bắt đầu hàm compose_context với budget_chars: {budget_chars}.")
    mt5_ctx_lite: dict | None = {}
    mt5_flags: dict | None = {}
    mt5full = None

    # --- Time-weighted Context ---
    # 1. Load a larger window of historical contexts (e.g., last 20)
    all_ctx_items = parse_ctx_json_files(app._get_reports_dir(folder_override=cfg.folder), max_n=20)
    logger.debug(f"Đã tải {len(all_ctx_items)} historical contexts.")
    
    # 2. Use all of them for long-term trend analysis
    trend = summarize_checklist_trend(all_ctx_items)
    logger.debug(f"Trend checklist summary: {trend}")

    # 3. Extract detailed context ONLY from the most recent items (e.g., last 3)
    detailed_ctx_items = all_ctx_items[:3]
    recent_history_summary = []
    plan = None
    
    if detailed_ctx_items:
        logger.debug(f"Có {len(detailed_ctx_items)} detailed context items.")
        # Extract the plan from the absolute latest context using the new universal parser
        # The plan is now a standardized dictionary from parse_setup_from_report
        latest_item_text = "\n".join(detailed_ctx_items[0].get("blocks", []))
        plan = report_parser.parse_setup_from_report(latest_item_text)
        logger.debug(f"Latest plan extracted: {plan}")

        # Build a summary from the last few reports
        for i, item in enumerate(detailed_ctx_items):
            tf_map = item.get("images_tf_map", {})
            tf_string = ""
            if tf_map:
                unique_tfs = sorted(list(set(tf_map.values())))
                tf_string = f" (Images: {', '.join(unique_tfs)})"

            header = f"--- Context T-{i} ({item.get('cycle', 'unknown time')}){tf_string} ---\n"
            
            # Use the new universal summary extractor
            summary_lines = item.get("summary_lines") # Assuming json_saver will save this
            if not summary_lines: # Fallback for older files
                 summary_lines, _, _ = report_parser.extract_summary_lines("\n".join(item.get("blocks", [])))

            if summary_lines and isinstance(summary_lines, list):
                summary = header + "\n".join(summary_lines)
                recent_history_summary.append(summary)
        logger.debug(f"Đã tạo {len(recent_history_summary)} recent history summaries.")

    # Extract the latest summary lines for delta comparison
    latest_summary_lines = None
    if detailed_ctx_items:
        latest_item = detailed_ctx_items[0]
        summary_lines = latest_item.get("summary_lines")
        if not summary_lines:
            summary_lines, _, _ = report_parser.extract_summary_lines("\n".join(latest_item.get("blocks", [])))
        
        if summary_lines and isinstance(summary_lines, list):
            latest_summary_lines = summary_lines
            logger.debug("Đã trích xuất latest summary lines.")

    if cfg.mt5_enabled:
        logger.debug("MT5 enabled, bắt đầu xây dựng MT5 context.")
        try:
            mt5_safe_data = app._mt5_build_context(plan=plan, cfg=cfg)
            if mt5_safe_data and mt5_safe_data.raw:
                mt5full = mt5_safe_data.raw
                info = (mt5full.get("info") or {})
                tick = (mt5full.get("tick") or {})
                volATR = ((mt5full.get("volatility") or {}).get("ATR") or {})
                stats5 = (mt5full.get("tick_stats_5m") or {})
                key_near = mt5full.get("key_levels_nearby") or []
                pip_size = mt5_utils.pip_size_from_info(info)
                cp = tick.get("bid") or tick.get("last")
                atr_m5 = volATR.get("M5")
                tpm = stats5.get("ticks_per_min")
                dist_pdh = next((x.get("distance_pips") for x in key_near if x.get("name") == "PDH"), None)
                dist_pdl = next((x.get("distance_pips") for x in key_near if x.get("name") == "PDL"), None)
                dist_eq = next((x.get("distance_pips") for x in key_near if x.get("name") == "EQ50_D"), None)
                session_name = None
                ss = mt5full.get("sessions_today") or {}
                now_hhmm = datetime.now().strftime("%H:%M")
                for k in ["asia", "london", "newyork_pre", "newyork_pm"]:
                    rng = ss.get(k)
                    if rng and rng.get("start") and rng.get("end") and rng["start"] <= now_hhmm < rng["end"]:
                        session_name = k
                        break
                mt5_ctx_lite = {
                    "symbol": mt5full.get("symbol"),
                    "positions": mt5full.get("positions"),
                    "current_price": cp,
                    "spread_points": info.get("spread_current"),
                    "atr_m5_pips": (atr_m5 / pip_size) if (atr_m5 and pip_size) else None,
                    "ticks_per_min": tpm,
                    "pdh_pdl_distance_pips": {"PDH": dist_pdh, "PDL": dist_pdl},
                    "eq50_d_distance_pips": dist_eq,
                    "session_active": session_name,
                    "mins_to_next_killzone": mt5full.get("mins_to_next_killzone"),
                }
                logger.debug("Đã xây dựng MT5 context lite.")

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
                logger.debug("Đã xây dựng MT5 flags.")
        except Exception:
            logger.exception("Failed to build MT5 context. Will proceed without it.")
            mt5full = None

    try:
        file_names = [Path(r["path"]).name for r in getattr(app, "results", []) if r.get("path")]
    except Exception:
        file_names = []
        logger.warning("Không lấy được file names từ app.results.")
    images_map = images_tf_map(file_names, getattr(app, "_detect_timeframe_from_name", None))
    run_meta = {
        "analysis_id": datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        "folder_signature": folder_signature(file_names),
        "images_tf_map": images_map,
    }
    logger.debug(f"Đã tạo run_meta: {run_meta}")

    pass_cnt = 0
    total = 0
    for it in all_ctx_items:
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
    logger.debug(f"Checklist pass ratio: {pass_cnt / total if total else None}")
    
    # --- Backtesting Integration ---
    proposed_trades = parse_proposed_trades_file(app._get_reports_dir(folder_override=cfg.folder))
    # Limit to last 50 trades to keep it fast
    backtest_results = backtester.evaluate_trade_outcomes(proposed_trades[-50:], cfg.mt5_symbol)
    logger.debug(f"Backtest results: {backtest_results}")

    stats5 = (mt5full.get("tick_stats_5m") if mt5full else None) or {}
    running_stats = {
        "checklist_pass_ratio": (pass_cnt / total if total else None),
        "backtest_results": backtest_results,
        "median_spread": stats5.get("median_spread"),
        "median_ticks_per_min": stats5.get("ticks_per_min"),
    }
    logger.debug(f"Running stats: {running_stats}")

    risk_rules = {
        "max_risk_per_trade_pct": float(cfg.trade_equity_risk_pct),
        "daily_loss_limit_pct": 3.0,
        "max_trades_per_day": 3,
        "allowed_killzones": ["london", "newyork_pre", "newyork_post"],
        "news_blackout_min_before_after": 15,
    }
    logger.debug(f"Risk rules: {risk_rules}")

    composed = {
        "CONTEXT_COMPOSED": {
            "cycle": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "session": mt5_ctx_lite.get("session_active") if isinstance(mt5_ctx_lite, dict) else None,
            "trend_checklist": trend,
            "latest_plan": plan or None,
            "latest_summary_lines": latest_summary_lines,
            "recent_history_summary": "\n\n".join(recent_history_summary) if recent_history_summary else None,
            "run_meta": run_meta,
            "running_stats": running_stats,
            "risk_rules": risk_rules,
            "environment_flags": mt5_flags or None,
            "mt5": (mt5full if mt5full else None),
            "mt5_lite": (mt5_ctx_lite or None),
        }
    }
    logger.debug("Đã tạo composed context.")

    # --- Vectorization and Similarity Search ---
    similar_scenarios = None
    if mt5full:
        logger.debug("MT5 full data có sẵn, bắt đầu vectorization và similarity search.")
        try:
            current_vector = vectorizer.vectorize_market_state(mt5full)
            if current_vector:
                logger.debug("Đã vectorize market state.")
                # Log the current vector for future comparisons
                vector_payload = {
                    "id": run_meta["analysis_id"],
                    "timestamp_utc": run_meta["analysis_id"],
                    "vector": current_vector,
                    "ctx_filename": f"ctx_{run_meta['analysis_id'].replace(':', '').replace('-', '').replace('T', '_').replace('Z', '')}.json"
                }
                # Note: The ctx_filename is an approximation but should be very close
                app._log_vector_data(vector_payload, folder_override=cfg.folder)
                logger.debug("Đã log vector data.")

                # Find similar past scenarios
                reports_dir = app._get_reports_dir(folder_override=cfg.folder)
                historical_vectors = parse_vector_database_file(reports_dir)
                logger.debug(f"Đã tải {len(historical_vectors)} historical vectors.")
                
                # Limit to last 500 vectors for performance
                similar_vectors = vectorizer.find_similar_vectors(current_vector, historical_vectors[-500:], top_n=3)
                logger.debug(f"Tìm thấy {len(similar_vectors)} similar vectors.")
                
                if similar_vectors:
                    similar_scenarios = []
                    for sim in similar_vectors:
                        try:
                            # Find the corresponding ctx file and extract its summary
                            ctx_path = reports_dir / sim["id"].split("'ctx_filename': '")[1].split("'")[0]
                            if ctx_path.exists():
                                past_ctx = json.loads(ctx_path.read_text(encoding="utf-8"))
                                seven_lines = past_ctx.get("seven_lines")
                                if seven_lines:
                                    similar_scenarios.append({
                                        "similarity": f"{sim['similarity']:.2%}",
                                        "past_summary": "\n".join(seven_lines)
                                    })
                                    logger.debug(f"Đã thêm similar scenario từ {ctx_path.name}.")
                        except Exception:
                            continue
        except Exception:
            pass # Fail silently

    composed["CONTEXT_COMPOSED"]["similar_past_scenarios"] = similar_scenarios
    logger.debug("Đã thêm similar_past_scenarios vào composed context.")

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
        logger.debug("Đã log decision start.")
    except Exception as e:
        logger.error(f"Lỗi khi log decision start: {e}")
        pass

    # --- Slimming Logic to fit budget ---
    def to_json(data):
        return json.dumps(data, ensure_ascii=False)

    text = to_json(composed)
    logger.debug(f"Kích thước context ban đầu: {len(text)} ký tự.")
    if len(text) <= budget_chars:
        logger.debug("Context nằm trong budget, không cần slimming.")
        return text

    # If oversized, start removing/slimming components in order of priority.
    try:
        # Create a deep copy to modify for slimming
        slim_composed = json.loads(text)
        slim_ctx = slim_composed.get("CONTEXT_COMPOSED", {})
        logger.debug("Bắt đầu slimming context.")

        # Priority 1: Remove full MT5 object (large and redundant if lite exists)
        if "mt5" in slim_ctx:
            slim_ctx.pop("mt5", None)
            text = to_json(slim_composed)
            logger.debug(f"Đã xóa full MT5 object. Kích thước mới: {len(text)} ký tự.")
            if len(text) <= budget_chars:
                return text

        # Priority 2: Remove similar past scenarios
        if "similar_past_scenarios" in slim_ctx:
            slim_ctx.pop("similar_past_scenarios", None)
            text = to_json(slim_composed)
            logger.debug(f"Đã xóa similar past scenarios. Kích thước mới: {len(text)} ký tự.")
            if len(text) <= budget_chars:
                return text

        # Priority 3: Trim recent history summary, then remove it
        if "recent_history_summary" in slim_ctx and slim_ctx["recent_history_summary"]:
            # First, try trimming it
            slim_ctx["recent_history_summary"] = slim_ctx["recent_history_summary"][:500] + "..."
            text = to_json(slim_composed)
            logger.debug(f"Đã trim recent history summary. Kích thước mới: {len(text)} ký tự.")
            if len(text) <= budget_chars:
                return text
            
            # If still too long, remove it completely
            slim_ctx.pop("recent_history_summary", None)
            text = to_json(slim_composed)
            logger.debug(f"Đã xóa recent history summary. Kích thước mới: {len(text)} ký tự.")
            if len(text) <= budget_chars:
                return text
        
        # Priority 4: Remove running stats
        if "running_stats" in slim_ctx:
            slim_ctx.pop("running_stats", None)
            text = to_json(slim_composed)
            logger.debug(f"Đã xóa running stats. Kích thước mới: {len(text)} ký tự.")
            if len(text) <= budget_chars:
                return text

        # If still too long after slimming, log a warning but return the valid (though oversized) JSON.
        # Truncating is worse as it creates invalid data. The model API might handle the extra length.
        if len(text) > budget_chars:
             logger.warning(f"Context still too long ({len(text)} chars) after slimming, but returning full valid JSON to avoid corruption.")
        
        logger.debug("Kết thúc slimming context.")
        return text

    except Exception as e:
        logger.exception(f"Error during context slimming: {e}")
        # Fallback to original text but DO NOT truncate to ensure valid JSON.
        logger.debug("Kết thúc hàm compose_context (lỗi slimming).")
        return json.dumps(composed, ensure_ascii=False)
