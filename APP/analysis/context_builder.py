from __future__ import annotations

import json
import hashlib
import logging
from pathlib import Path
from typing import Any, Dict, List, Tuple, TYPE_CHECKING

from APP.analysis import report_parser
from APP.services import mt5_service, news_service

if TYPE_CHECKING:
    from APP.configs.app_config import RunConfig
    from APP.ui.app_ui import AppUI
    from APP.utils.safe_data import SafeMT5Data

logger = logging.getLogger(__name__)


def _parse_ctx_json_files(reports_dir: Path, max_n: int = 5) -> list[dict]:
    """Phân tích các tệp ngữ cảnh JSON (ctx_*.json) gần đây nhất từ một thư mục."""
    if not reports_dir or not reports_dir.is_dir():
        return []
    files = sorted(reports_dir.glob("ctx_*.json"), reverse=True)[:max_n]
    out = []
    for p in files:
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"Lỗi khi đọc hoặc phân tích tệp ngữ cảnh {p.name}: {e}")
    return out


def build_context_from_reports(
    reports_dir: Path, budget_chars: int = 1800
) -> Tuple[str, Dict | None]:
    """
    Xây dựng một khối ngữ cảnh từ các báo cáo JSON đã lưu trước đó.
    """
    all_ctx_items = _parse_ctx_json_files(reports_dir, max_n=20)
    if not all_ctx_items:
        return "", None

    # Trích xuất kế hoạch từ báo cáo gần đây nhất
    latest_item_text = "\n".join(all_ctx_items[0].get("blocks", []))
    plan = report_parser.parse_trade_setup_from_report(latest_item_text)

    # Tóm tắt lịch sử gần đây
    recent_history_summary = []
    for i, item in enumerate(all_ctx_items[:3]):
        summary_lines, _, _ = report_parser.extract_summary_lines(
            "\n".join(item.get("blocks", []))
        )
        if summary_lines:
            header = f"--- Context T-{i} ({item.get('cycle', 'unknown')}) ---\n"
            recent_history_summary.append(header + "\n".join(summary_lines))

    composed = {
        "latest_plan": plan,
        "recent_history_summary": "\n\n".join(recent_history_summary),
    }

    # Làm gọn văn bản để phù hợp với budget
    context_str = json.dumps(composed, ensure_ascii=False)
    if len(context_str) > budget_chars:
        composed["recent_history_summary"] = (
            composed["recent_history_summary"][:budget_chars] + "..."
        )
        context_str = json.dumps(composed, ensure_ascii=False)

    return context_str, plan


def coordinate_context_building(
    app: AppUI, cfg: RunConfig
) -> Tuple[SafeMT5Data | None, Dict, str, str]:
    """
    Điều phối việc xây dựng toàn bộ ngữ cảnh cho worker.
    """
    logger.debug("Bắt đầu điều phối xây dựng ngữ cảnh.")
    
    # 1. Xây dựng ngữ cảnh lịch sử
    reports_dir = app.get_reports_dir(folder_override=cfg.folder)
    composed, plan = build_context_from_reports(
        reports_dir, budget_chars=max(800, cfg.ctx_limit)
    )
    context_block = f"\n\n[CONTEXT_COMPOSED]\n{composed}" if composed else ""

    # 2. Lấy dữ liệu MT5
    safe_mt5_data = None
    mt5_dict = {}
    if cfg.mt5_enabled:
        safe_mt5_data = mt5_service.build_context(
            cfg.mt5_symbol,
            n_m1=cfg.mt5_n_M1,
            n_m5=cfg.mt5_n_M5,
            n_m15=cfg.mt5_n_M15,
            n_h1=cfg.mt5_n_H1,
            plan=plan,
        )
        if safe_mt5_data and safe_mt5_data.raw:
            mt5_dict = safe_mt5_data.raw

    # 3. Làm giàu dữ liệu MT5 với phân tích tin tức (nếu có)
    if mt5_dict and cfg.trade_news_block_enabled:
        try:
            news_events = news_service.get_forex_factory_news(cfg)
            is_in_window, reason = news_service.is_within_news_window(
                events=news_events,
                symbol=cfg.mt5_symbol,
                minutes_before=cfg.trade_news_block_before_min,
                minutes_after=cfg.trade_news_block_after_min,
            )
            mt5_dict["news_analysis"] = {
                "is_in_news_window": is_in_window,
                "reason": reason,
            }
        except Exception as e:
            logger.error(f"Lỗi khi phân tích tin tức: {e}")
            mt5_dict["news_analysis"] = {"error": str(e)}

    mt5_json_full = json.dumps({"MT5_DATA": mt5_dict}, ensure_ascii=False) if mt5_dict else ""
    
    return safe_mt5_data, mt5_dict, context_block, mt5_json_full
