# -*- coding: utf-8 -*-
"""
Module này chịu trách nhiệm xây dựng và điều phối toàn bộ ngữ cảnh (context)
được cung cấp cho model AI. Nó tổng hợp dữ liệu lịch sử, dữ liệu thị trường
thời gian thực, tin tức và các phân tích khác để tạo ra một "bức tranh"
toàn cảnh cho việc ra quyết định.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, cast

# TODO: Tích hợp backtester và vectorizer vào cấu trúc APP
# from . import backtester
# from . import vectorizer
from APP.analysis import report_parser
from APP.services import mt5_service, news_service
from APP.ui.utils.timeframe_detector import TimeframeDetector
from APP.utils.safe_data import SafeData

if TYPE_CHECKING:
    from APP.configs.app_config import RunConfig
    from APP.ui.app_ui import AppUI

logger = logging.getLogger(__name__)


# region Helper Functions from src/core/context_builder.py
# Các hàm này được chuyển từ file gốc để tập trung logic xử lý file báo cáo


def _parse_jsonl_file(log_file: Path) -> List[Dict]:
    """
    Hàm nội bộ để đọc và parse một file có định dạng .jsonl.

    Args:
        log_file: Đường dẫn đầy đủ đến file .jsonl.

    Returns:
        Danh sách các đối tượng dict từ file, hoặc danh sách rỗng nếu có lỗi.
    """
    if not log_file.exists():
        logger.debug(f"File log {log_file.name} không tồn tại.")
        return []

    items = []
    try:
        with open(log_file, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    items.append(json.loads(line))
        logger.debug(f"Đã parse {len(items)} items từ {log_file.name}.")
    except Exception:
        logger.error(f"Lỗi khi parse file {log_file.name}", exc_info=True)
        return []
    return items


def parse_proposed_trades_file(reports_dir: Path) -> List[Dict]:
    """
    Phân tích file 'proposed_trades.jsonl' để lấy danh sách các giao dịch được đề xuất.
    """
    logger.debug(f"Bắt đầu parse proposed_trades.jsonl từ: {reports_dir}")
    return _parse_jsonl_file(reports_dir / "proposed_trades.jsonl")


def parse_vector_database_file(reports_dir: Path) -> List[Dict]:
    """
    Phân tích file 'vector_database.jsonl' để lấy danh sách các vector trạng thái thị trường.
    """
    logger.debug(f"Bắt đầu parse vector_database.jsonl từ: {reports_dir}")
    return _parse_jsonl_file(reports_dir / "vector_database.jsonl")


def parse_ctx_json_files(reports_dir: Path, max_n: int = 5) -> List[Dict]:
    """
    Phân tích các file ngữ cảnh JSON (ctx_*.json) từ một thư mục.

    Args:
        reports_dir: Đường dẫn đến thư mục chứa các file ngữ cảnh.
        max_n: Số lượng file ngữ cảnh tối đa cần đọc (mới nhất).

    Returns:
        Danh sách các từ điển, mỗi từ điển đại diện cho một ngữ cảnh đã parse.
    """
    logger.debug(f"Parsing last {max_n} context files from: {reports_dir}")
    if not reports_dir or not reports_dir.exists():
        logger.warning(f"Thư mục báo cáo không tồn tại: {reports_dir}")
        return []
    files = sorted(reports_dir.glob("ctx_*.json"), reverse=True)[: max(1, int(max_n))]
    out: List[Dict] = []
    for p in files:
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            logger.warning(f"Lỗi khi parse file context {p.name}", exc_info=True)
            continue
    logger.debug(f"Đã parse thành công {len(out)} file context.")
    return out


def summarize_checklist_trend(ctx_items: List[Dict]) -> Dict:
    """
    Tóm tắt xu hướng từ các mục checklist trong ngữ cảnh lịch sử.

    Hàm này tính điểm cho mỗi lần chạy dựa trên kết quả checklist và
    so sánh điểm của lần chạy gần nhất với lần xa nhất để xác định xu hướng.

    Args:
        ctx_items: Danh sách các từ điển ngữ cảnh lịch sử.

    Returns:
        Một từ điển chứa xu hướng ("improving", "deteriorating", "flat", "unknown")
        và tỷ lệ các lần chạy đạt yêu cầu ("enough_ratio").
    """
    logger.debug(f"Bắt đầu tóm tắt xu hướng checklist từ {len(ctx_items)} items.")
    if not ctx_items:
        logger.debug("Không có items, trả về trend 'unknown'.")
        return {"trend": "unknown", "enough_ratio": None}

    scores = {"ĐỦ": 2, "CHỜ": 1, "SAI": 0}
    seq: List[int] = []
    enough_cnt = 0
    total = 0

    # Duyệt qua các item theo thứ tự từ cũ đến mới (đảo ngược list đầu vào)
    for it in reversed(ctx_items):
        setup_json = None
        blocks = it.get("blocks") or []
        for blk in blocks:
            try:
                obj = json.loads(blk)
                if isinstance(obj, dict) and "setup_status" in obj:
                    setup_json = obj
                    break
            except (json.JSONDecodeError, TypeError):
                continue

        if not setup_json:
            continue

        st = setup_json.get("setup_status", {})
        # Giả định các key A-F tồn tại trong status
        val = sum(scores.get(st.get(k, ""), 0) for k in "ABCDEF")
        seq.append(val)

        concl = setup_json.get("conclusions", "")
        if isinstance(concl, str) and ("ĐỦ" in concl.upper() or "DU" in concl.upper()):
            enough_cnt += 1
        total += 1

    if not total:
        logger.debug("Không tìm thấy checklist nào hợp lệ.")
        return {"trend": "unknown", "enough_ratio": None}

    enough_ratio = enough_cnt / total
    if len(seq) < 2:
        logger.debug("Không đủ dữ liệu để xác định xu hướng (cần ít nhất 2 điểm).")
        return {"trend": "flat", "enough_ratio": enough_ratio}

    # So sánh điểm đầu và điểm cuối để xác định xu hướng
    delta = seq[-1] - seq[0]
    trend = "improving" if delta > 0 else ("deteriorating" if delta < 0 else "flat")

    logger.debug(f"Tóm tắt xu hướng hoàn tất: Trend={trend}, Enough Ratio={enough_ratio:.2f}")
    return {"trend": trend, "enough_ratio": enough_ratio}


def folder_signature(names: List[str]) -> str:
    """
    Tạo chữ ký SHA1 cho một danh sách các tên tệp.
    """
    names = sorted(list(names or []))
    if not names:
        return ""
    sig = hashlib.sha1("\n".join(names).encode("utf-8")).hexdigest()
    return f"sha1:{sig}" if sig else ""


# endregion


def build_context_from_reports(
    reports_dir: Path,
    image_results: List[Dict],
    timeframe_detector: "TimeframeDetector",
    cfg: "RunConfig",
    budget_chars: int = 1800,
) -> Tuple[str, Optional[Dict]]:
    """
    Xây dựng chuỗi JSON ngữ cảnh lịch sử (được cắt bớt theo ngân sách).

    Hàm này tập trung logic lắp ráp và làm gọn ngữ cảnh từ các lần chạy trước,
    dữ liệu backtest, và các quy tắc rủi ro. Hàm này được thiết kế để không
    phụ thuộc trực tiếp vào đối tượng AppUI, giúp tăng khả năng kiểm thử.

    Args:
        reports_dir: Đường dẫn đến thư mục chứa báo cáo.
        image_results: Danh sách kết quả hình ảnh từ UI.
        detect_tf_callback: Hàm callback để phát hiện timeframe từ tên file.
        cfg: Đối tượng cấu hình (RunConfig).
        budget_chars: Ngân sách ký tự tối đa cho chuỗi JSON.

    Returns:
        Một tuple chứa:
        - Chuỗi JSON ngữ cảnh đã được tạo và làm gọn.
        - Kế hoạch (plan) được trích xuất từ ngữ cảnh gần nhất (nếu có).
    """
    logger.debug(f"Bắt đầu xây dựng ngữ cảnh lịch sử với budget: {budget_chars} chars.")

    # 1. Tải và phân tích các ngữ cảnh lịch sử
    all_ctx_items = parse_ctx_json_files(reports_dir, max_n=20)
    trend = summarize_checklist_trend(all_ctx_items)
    detailed_ctx_items = all_ctx_items[:3]
    recent_history_summary = []
    plan = None
    latest_summary_lines = None

    if detailed_ctx_items:
        latest_item_text = "\n".join(detailed_ctx_items[0].get("blocks", []))
        plan = report_parser.parse_setup_from_report(latest_item_text)
        logger.debug(f"Kế hoạch gần nhất được trích xuất: {plan is not None}")

        for i, item in enumerate(detailed_ctx_items):
            summary, _, _ = report_parser.extract_summary_lines("\n".join(item.get("blocks", [])))
            if summary:
                header = f"--- Context T-{i} ({item.get('cycle', 'unknown')}) ---\n"
                recent_history_summary.append(header + "\n".join(summary))

        latest_summary_lines, _, _ = report_parser.extract_summary_lines(latest_item_text)

    # 2. Tạo metadata cho lần chạy hiện tại
    file_names = [Path(r["path"]).name for r in image_results if r.get("path")]
    run_meta = {
        "analysis_id": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "folder_signature": folder_signature(file_names),
        "images_tf_map": timeframe_detector.create_images_tf_map(file_names),
    }

    # 3. Thống kê và quy tắc
    # TODO: Tích hợp lại logic backtester khi có sẵn
    # proposed_trades = parse_proposed_trades_file(reports_dir)
    # backtest_results = backtester.evaluate_trade_outcomes(proposed_trades[-50:], cfg.mt5.symbol)
    backtest_results = {"status": "not_implemented"}
    
    running_stats = {"backtest_results": backtest_results}
    risk_rules = {
        "max_risk_per_trade_pct": cfg.auto_trade.risk_per_trade,
        "daily_loss_limit_pct": 3.0,
        "max_trades_per_day": 3,
    }

    # 4. Tổng hợp và làm gọn
    composed = {
        "CONTEXT_COMPOSED": {
            "cycle": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "trend_checklist": trend,
            "latest_plan": plan,
            "latest_summary_lines": latest_summary_lines,
            "recent_history_summary": "\n\n".join(recent_history_summary) or None,
            "run_meta": run_meta,
            "running_stats": running_stats,
            "risk_rules": risk_rules,
        }
    }

    def to_json(data: Dict) -> str:
        return json.dumps(data, ensure_ascii=False)

    text = to_json(composed)
    if len(text) <= budget_chars:
        logger.debug(f"Ngữ cảnh lịch sử có kích thước {len(text)} chars (trong budget).")
        return text, plan

    # Logic làm gọn (slimming)
    logger.warning(f"Ngữ cảnh ban đầu ({len(text)} chars) vượt budget ({budget_chars}). Bắt đầu làm gọn.")
    try:
        slim_ctx = composed["CONTEXT_COMPOSED"]
        if "recent_history_summary" in slim_ctx:
            slim_ctx.pop("recent_history_summary")
            text = to_json(composed)
            if len(text) <= budget_chars:
                return text, plan
        # Thêm các bước làm gọn khác nếu cần
    except Exception:
        logger.exception("Lỗi trong quá trình làm gọn ngữ cảnh.")

    if len(text) > budget_chars:
        logger.error(f"Ngữ cảnh vẫn quá dài ({len(text)}) sau khi làm gọn.")

    return text, plan


def _create_concept_value_table(data: SafeData) -> str:
    """
    Tạo một bảng Markdown tóm tắt các thông tin quan trọng nhất từ dữ liệu MT5.
    """
    if not data or not data.raw:
        return "Không có dữ liệu MT5."

    table = "| Khái niệm (Concept) | Giá trị (Value) |\n|---|---|\n"
    def add_row(concept: str, value: Any):
        nonlocal table
        if value is not None and value != "":
            table += f"| {concept} | {value} |\n"

    add_row("Symbol", data.get('symbol'))
    add_row("Killzone Hiện tại", data.get('killzone_active', "Không có"))
    add_row("Chế độ Biến động", data.get('volatility_regime', "Không rõ"))
    ict_patterns = data.get('ict_patterns', {})
    
    # Xử lý an toàn cho mss_h1, có thể là None
    mss_h1 = ict_patterns.get('mss_h1')
    h1_order_flow = mss_h1.get('type', "Không rõ") if isinstance(mss_h1, dict) else "Không rõ"
    add_row("H1 Order Flow", h1_order_flow)

    # Xử lý an toàn cho mss_m15, có thể là None
    mss_m15 = ict_patterns.get('mss_m15')
    m15_structure = mss_m15.get('type', "Không rõ") if isinstance(mss_m15, dict) else "Không rõ"
    add_row("M15 Structure", m15_structure)

    add_row("Trong Cửa sổ Tin tức", data.get('news_analysis', {}).get('is_in_news_window'))
    
    upcoming = data.get('news_analysis', {}).get('upcoming_events', [])
    if upcoming:
        next_event = upcoming[0]
        add_row("Tin tức Sắp tới", f"{next_event.get('time_remaining')} - {next_event.get('title')}")
    
    return table


def coordinate_context_building(
    app: "AppUI", cfg: "RunConfig"
) -> Tuple[Optional[SafeData], Dict, str, str]:
    """
    Điều phối việc xây dựng toàn bộ ngữ cảnh cần thiết cho model AI.

    Hàm này là điểm vào chính, kết hợp ngữ cảnh lịch sử với dữ liệu thời gian thực
    để tạo ra đầu vào hoàn chỉnh cho worker phân tích.

    Returns:
        Một tuple chứa:
        - SafeMT5Data: Đối tượng dữ liệu MT5 đã được làm giàu.
        - Dict: Dữ liệu MT5 dưới dạng dictionary.
        - str: Khối ngữ cảnh lịch sử (đã có header).
        - str: Toàn bộ dữ liệu MT5 dưới dạng chuỗi JSON.
    """
    logger.info("Bắt đầu điều phối xây dựng ngữ cảnh toàn diện.")

    # 1. Thu thập các phụ thuộc từ 'app' để truyền vào hàm con
    # reports_dir = app.get_reports_dir() # This should be handled by the caller
    image_results = getattr(app, "results", [])
    timeframe_detector = app.timeframe_detector

    # 2. Xây dựng ngữ cảnh lịch sử bằng cách gọi hàm đã được tách rời
    composed_json, plan = build_context_from_reports(
        reports_dir=Path(app.folder_path.get()) / "Reports", # Get reports dir directly
        image_results=image_results,
        timeframe_detector=timeframe_detector,
        cfg=cfg,
        budget_chars=max(800, int(cfg.context.ctx_limit)),
    )
    context_block = f"\n\n[CONTEXT_COMPOSED]\n{composed_json}" if composed_json else ""

    # 3. Lấy và làm giàu dữ liệu MT5 thời gian thực
    safe_mt5_data_untyped = (
        mt5_service.get_market_data(
            cfg=cfg.mt5, plan=plan, return_json=False
        )
        if cfg.mt5.enabled
        else None
    )
    safe_mt5_data: Optional[SafeData] = cast(Optional[SafeData], safe_mt5_data_untyped)

    if safe_mt5_data and safe_mt5_data.raw:
        logger.debug("Dữ liệu MT5 có sẵn, bắt đầu làm giàu với tin tức.")
        # Làm giàu với phân tích tin tức bằng cơ chế cache
        try:
            is_in_window, reason, updated_events, updated_fetch_time = news_service.within_news_window_cached(
                symbol=cfg.mt5.symbol,
                minutes_before=cfg.news.block_before_min,
                minutes_after=cfg.news.block_after_min,
                cache_events=app.news_events,
                cache_fetch_time=app.news_fetch_time,
                ttl_sec=cfg.news.cache_ttl_sec,
            )
            # Cập nhật lại cache trên app
            app.news_events = updated_events
            app.news_fetch_time = updated_fetch_time

            upcoming = news_service.next_events_for_symbol(
                events=updated_events, symbol=cfg.mt5.symbol, limit=3
            )
            safe_mt5_data.raw["news_analysis"] = {
                "is_in_news_window": is_in_window, "reason": reason, "upcoming_events": upcoming
            }
            logger.debug(f"Phân tích tin tức hoàn tất. Trong cửa sổ tin tức: {is_in_window}")
        except Exception:
            logger.error("Lỗi khi làm giàu dữ liệu với tin tức.", exc_info=True)
            safe_mt5_data.raw["news_analysis"] = {"error": "failed to fetch or analyze news"}

        # Tạo và thêm bảng tóm tắt
        concept_table_str = _create_concept_value_table(safe_mt5_data)
        safe_mt5_data.raw["concept_value_table"] = concept_table_str
        logger.debug("Đã tạo và thêm bảng tóm tắt khái niệm.")

    mt5_dict = safe_mt5_data.raw if safe_mt5_data else {}
    mt5_json_full = safe_mt5_data.to_json(indent=2) if safe_mt5_data else ""

    logger.info("Điều phối xây dựng ngữ cảnh hoàn tất.")
    return safe_mt5_data, mt5_dict, context_block, mt5_json_full

__all__ = ["coordinate_context_building", "build_context_from_reports"]
