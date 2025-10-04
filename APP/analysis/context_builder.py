from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Dict, Tuple

from APP.services import news_service
from APP.utils.safe_data import SafeMT5Data

if TYPE_CHECKING:
    from APP.configs.app_config import RunConfig
    from APP.ui.app_ui import AppUI

logger = logging.getLogger(__name__)


def build_context_from_reports(app: "AppUI", cfg: "RunConfig") -> Tuple[str, Dict | None]:
    """
    Xây dựng ngữ cảnh lịch sử từ các báo cáo trước đó.
    """
    logger.debug("Bắt đầu xây dựng ngữ cảnh từ báo cáo.")
    composed = app.compose_context(cfg, budget_chars=max(800, int(cfg.context.ctx_limit))) or ""
    plan = None
    if composed:
        try:
            _obj = json.loads(composed)
            plan = (_obj.get("CONTEXT_COMPOSED") or {}).get("latest_plan")
            logger.debug(f"Đã trích xuất plan từ composed context: {plan}")
        except Exception as e:
            logger.warning(f"Lỗi khi parse plan từ composed context: {e}")
    context_block = f"\n\n[CONTEXT_COMPOSED]\n{composed}" if composed else ""
    logger.debug("Kết thúc xây dựng ngữ cảnh từ báo cáo.")
    return context_block, plan


def coordinate_context_building(app: "AppUI", cfg: "RunConfig") -> Tuple[SafeMT5Data | None, Dict, str, str]:
    """
    Điều phối việc xây dựng toàn bộ ngữ cảnh cần thiết cho model AI,
    bao gồm dữ liệu MT5, tin tức và lịch sử.
    """
    logger.debug("Bắt đầu điều phối xây dựng ngữ cảnh.")
    
    # 1. Xây dựng ngữ cảnh lịch sử
    context_block, plan = build_context_from_reports(app, cfg)

    # 2. Lấy dữ liệu MT5
    safe_mt5_data = app._mt5_build_context(plan=plan, cfg=cfg) if cfg.mt5.enabled else None
    mt5_dict = safe_mt5_data.raw if safe_mt5_data and safe_mt5_data.raw else {}

    # 3. Làm giàu dữ liệu MT5 với phân tích tin tức
    if mt5_dict:
        logger.debug("Bắt đầu làm giàu dữ liệu MT5 với tin tức.")
        try:
            app._refresh_news_cache(ttl=300, async_fetch=False, cfg=cfg)
            is_in_window, reason = news_service.is_within_news_window(
                events=app.ff_cache_events_local,
                symbol=cfg.mt5.symbol,
                minutes_before=cfg.news.block_before_min,
                minutes_after=cfg.news.block_after_min,
            )
            upcoming = news_service.next_events_for_symbol(
                events=app.ff_cache_events_local,
                symbol=cfg.mt5.symbol,
                limit=3
            )
            mt5_dict["news_analysis"] = {
                "is_in_news_window": is_in_window,
                "reason": reason,
                "upcoming_events": upcoming
            }
        except Exception as e:
            logger.error(f"Lỗi khi phân tích tin tức: {e}")
            mt5_dict["news_analysis"] = {
                "is_in_news_window": False, "reason": "News check failed", "upcoming_events": []
            }
            
    mt5_json_full = json.dumps({"MT5_DATA": mt5_dict}, ensure_ascii=False) if mt5_dict else ""
    
    logger.debug("Kết thúc điều phối xây dựng ngữ cảnh.")
    return safe_mt5_data, mt5_dict, context_block, mt5_json_full

__all__ = ["coordinate_context_building", "build_context_from_reports"]
