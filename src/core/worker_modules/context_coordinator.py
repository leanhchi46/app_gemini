from __future__ import annotations
import json
import logging
from typing import TYPE_CHECKING, Dict, Tuple

logger = logging.getLogger(__name__) # Khởi tạo logger

from src.core import context_builder # Cần cho compose_context
from src.services import news # Cần cho phân tích tin tức
from src.utils.safe_data import SafeMT5Data # Cần cho type hint

if TYPE_CHECKING:
    from scripts.tool import TradingToolApp
    from src.config.config import RunConfig

def prepare_and_build_context(app: "TradingToolApp", cfg: "RunConfig") -> Tuple[SafeMT5Data, Dict, str, str]:
    """
    Xây dựng toàn bộ ngữ cảnh cần thiết để cung cấp cho model AI.
    Bao gồm: ngữ cảnh lịch sử, dữ liệu MT5, và phân tích tin tức.
    """
    logger.debug("Bắt đầu prepare_and_build_context.")
    # 1. Xây dựng ngữ cảnh lịch sử từ các lần chạy trước
    composed = app.compose_context(cfg, budget_chars=max(800, int(cfg.ctx_limit))) or ""
    plan = None
    if composed:
        try:
            _obj = json.loads(composed)
            plan = (_obj.get("CONTEXT_COMPOSED") or {}).get("latest_plan")
            logger.debug(f"Đã trích xuất plan từ composed context: {plan}")
        except Exception as e:
            logger.warning(f"Lỗi khi parse plan từ composed context: {e}")
            pass
    context_block = f"\n\n[CONTEXT_COMPOSED]\n{composed}" if composed else ""
    logger.debug("Đã xây dựng context_block.")

    # 2. Lấy dữ liệu MT5 thời gian thực
    safe_mt5_data = app._mt5_build_context(plan=plan, cfg=cfg) if cfg.mt5_enabled else None
    mt5_dict = (safe_mt5_data.raw if safe_mt5_data and safe_mt5_data.raw else {})
    logger.debug(f"Đã lấy dữ liệu MT5. MT5 enabled: {cfg.mt5_enabled}, dữ liệu có: {bool(mt5_dict)}")
    
    # 3. Làm giàu dữ liệu MT5 với phân tích tin tức
    if mt5_dict:
        logger.debug("MT5 data có sẵn, bắt đầu phân tích tin tức.")
        try:
            app._refresh_news_cache(ttl=300, async_fetch=False, cfg=cfg)
            logger.debug("Đã refresh news cache.")
            is_in_window, reason = news.is_within_news_window(
                events=app.ff_cache_events_local,
                symbol=cfg.mt5_symbol,
                minutes_before=cfg.trade_news_block_before_min, # Sử dụng cfg.trade_news_block_before_min
                minutes_after=cfg.trade_news_block_after_min,   # Sử dụng cfg.trade_news_block_after_min
            )
            upcoming = news.next_events_for_symbol(
                events=app.ff_cache_events_local,
                symbol=cfg.mt5_symbol,
                limit=3
            )
            mt5_dict["news_analysis"] = {
                "is_in_news_window": is_in_window,
                "reason": reason,
                "upcoming_events": upcoming
            }
            logger.debug(f"Đã phân tích tin tức. Trong cửa sổ tin tức: {is_in_window}, lý do: {reason}.")
        except Exception as e:
            logger.error(f"Lỗi khi phân tích tin tức: {e}")
            # Đảm bảo key luôn tồn tại để tránh lỗi downstream
            mt5_dict["news_analysis"] = {
                "is_in_news_window": False, "reason": "News check failed", "upcoming_events": []
            }
            
    mt5_json_full = json.dumps({"MT5_DATA": mt5_dict}, ensure_ascii=False) if mt5_dict else ""
    logger.debug("Đã tạo mt5_json_full.")
    
    logger.debug("Kết thúc prepare_and_build_context.")
    return safe_mt5_data, mt5_dict, context_block, mt5_json_full
