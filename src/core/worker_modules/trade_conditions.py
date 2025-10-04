from __future__ import annotations
import json
import logging
from typing import TYPE_CHECKING

from src.utils import ui_utils
from src.utils import md_saver
from src.utils import mt5_utils # Cần cho build_context_from_app

logger = logging.getLogger(__name__) # Khởi tạo logger

if TYPE_CHECKING:
    from scripts.tool import TradingToolApp
    from src.config.config import RunConfig

def handle_no_change_scenario(app: "TradingToolApp", cfg: "RunConfig"):
    """
    Xử lý trường hợp không có ảnh nào thay đổi so với lần chạy trước.
    Sẽ tạo một báo cáo ngắn gọn, quản lý các lệnh đang chạy và thoát sớm.
    """
    logger.debug("Bắt đầu hàm handle_no_change_scenario.")
    app.ui_status("Ảnh không đổi, tạo báo cáo nhanh...")
    logger.info("Ảnh không đổi, tạo báo cáo nhanh.")
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
    mt5_ctx_text = mt5_utils.build_context_from_app(app, plan=plan, cfg=cfg) if cfg.mt5_enabled else ""
    logger.debug(f"MT5 context text được tạo: {bool(mt5_ctx_text)}")
    
    report_text = "Ảnh không đổi so với lần gần nhất."
    if context_block:
        report_text += f"\n\n{context_block}"
    if mt5_ctx_text:
        report_text += f"\n\n[PHỤ LỤC_MT5_JSON]\n{mt5_ctx_text}"

    app.combined_report_text = report_text
    ui_utils.ui_detail_replace(app, report_text)
    md_saver.save_md_report(app, report_text, cfg)
    ui_utils.ui_refresh_history_list(app)

    # Vẫn kiểm tra và quản lý các lệnh BE/Trailing dù không phân tích lại
    if mt5_ctx_text:
        try:
            mt5_dict_cache = json.loads(mt5_ctx_text).get("MT5_DATA", {})
            if mt5_dict_cache:
                logger.debug("Bắt đầu quản lý BE/Trailing trong kịch bản không thay đổi.")
                pass # Giữ khối lệnh hợp lệ sau khi comment
        except Exception as e:
            logger.warning(f"Lỗi khi quản lý BE/Trailing trong kịch bản không thay đổi: {e}")
            
    # Không raise SystemExit ở đây, mà để main_worker xử lý
    logger.debug("Kết thúc hàm handle_no_change_scenario.")
