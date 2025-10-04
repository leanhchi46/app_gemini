from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from APP.persistence import md_handler
from APP.services import mt5_service
from APP.ui.utils import ui_builder

if TYPE_CHECKING:
    from APP.configs.app_config import RunConfig
    from APP.ui.app_ui import AppUI
    from APP.utils.safe_data import SafeMT5Data

logger = logging.getLogger(__name__)


def handle_early_exit(app: "AppUI", cfg: "RunConfig", reason: str):
    """
    Xử lý các trường hợp cần thoát sớm khỏi quy trình phân tích,
    ví dụ như không có ảnh nào thay đổi.
    Sẽ tạo một báo cáo ngắn gọn, quản lý các lệnh đang chạy và báo hiệu để thoát.
    """
    logger.debug(f"Bắt đầu hàm handle_early_exit. Lý do: {reason}")
    app.ui_status(f"{reason}, tạo báo cáo nhanh...")
    logger.info(f"{reason}, tạo báo cáo nhanh.")
    
    # Lấy ngữ cảnh hiện tại để quản lý trade
    composed = app.compose_context(cfg, budget_chars=max(800, int(cfg.context.ctx_limit))) or ""
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
    mt5_ctx = mt5_service.build_context_from_app(app, plan=plan, cfg=cfg) if cfg.mt5.enabled else None
    mt5_ctx_text = mt5_ctx.to_json() if mt5_ctx else ""
    logger.debug(f"MT5 context được tạo: {bool(mt5_ctx_text)}")
    
    report_text = f"Dừng sớm: {reason}."
    if context_block:
        report_text += f"\n\n{context_block}"
    if mt5_ctx_text:
        report_text += f"\n\n[PHỤ LỤC_MT5_JSON]\n{mt5_ctx_text}"

    app.combined_report_text = report_text
    ui_builder.ui_detail_replace(app, report_text)
    md_handler.save_md_report(app, report_text, cfg)
    ui_builder.ui_refresh_history_list(app)

    # Vẫn kiểm tra và quản lý các lệnh BE/Trailing
    if mt5_ctx:
        try:
            # Logic quản lý trade sẽ được gọi từ đây trong tương lai
            logger.debug("Bắt đầu quản lý BE/Trailing trong kịch bản thoát sớm.")
            # manage_existing_trades(app, cfg, mt5_ctx) # Sẽ được thêm vào sau
        except Exception as e:
            logger.warning(f"Lỗi khi quản lý BE/Trailing trong kịch bản thoát sớm: {e}")
            
    logger.debug("Kết thúc hàm handle_early_exit.")


def check_no_run_conditions(app: "AppUI", cfg: "RunConfig") -> str | None:
    """
    Kiểm tra các điều kiện không cho phép chạy phân tích (NO-RUN).
    Trả về lý do nếu không được chạy, ngược lại trả về None.
    """
    logger.debug("Kiểm tra các điều kiện NO-RUN.")
    # Logic kiểm tra NO-RUN sẽ được thêm vào đây
    # Ví dụ: kiểm tra cuối tuần, killzone, etc.
    return None


def check_no_trade_conditions(app: "AppUI", cfg: "RunConfig", mt5_data: "SafeMT5Data") -> list[str]:
    """
    Kiểm tra các điều kiện không cho phép vào lệnh (NO-TRADE).
    Trả về một danh sách các lý do nếu không được vào lệnh.
    """
    logger.debug("Kiểm tra các điều kiện NO-TRADE.")
    reasons = []
    # Logic kiểm tra NO-TRADE sẽ được thêm vào đây
    # Ví dụ: spread, ATR, tin tức, etc.
    return reasons

__all__ = ["handle_early_exit", "check_no_run_conditions", "check_no_trade_conditions"]
