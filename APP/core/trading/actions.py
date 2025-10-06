from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None

from APP.analysis import report_parser
from APP.persistence import log_handler
from APP.services import mt5_service

if TYPE_CHECKING:
    from APP.configs.app_config import RunConfig
    from APP.ui.app_ui import AppUI

logger = logging.getLogger(__name__)


def execute_trade_action(
    app: AppUI, combined_text: str, mt5_ctx: dict[str, Any], cfg: RunConfig
) -> bool:
    """Phân tích, đánh giá và đặt lệnh dựa trên phân tích chuyên sâu của AI."""
    if not cfg.auto_trade.enabled or mt5 is None:
        return False

    ai_analysis = report_parser.extract_json_block_prefer(combined_text)
    plan = ai_analysis.get("proposed_plan", {})
    grade = ai_analysis.get("setup_grade")

    if grade not in ["A+", "B"] or not all(plan.get(k) for k in ["direction", "entry", "sl"]):
        logger.debug(f"Không có setup chất lượng cao (Grade: {grade}). Bỏ qua.")
        return False

    try:
        risk_multiplier = float(plan.get("risk_multiplier", 0.0))
    except (ValueError, TypeError):
        risk_multiplier = 0.0

    if risk_multiplier <= 0:
        logger.warning(f"Risk multiplier không hợp lệ hoặc bằng 0 ({risk_multiplier}). Bỏ qua.")
        return False

    lots = mt5_service.calculate_lots(
        cfg, mt5_ctx.get("symbol", ""), plan["entry"], plan["sl"],
        mt5_ctx.get("info", {}), mt5_ctx.get("account", {}), risk_multiplier
    )

    if not lots or lots <= 0:
        # Sửa lỗi: Thay thế hàm không tồn tại bằng cách gọi phương thức trên app qua queue
        app.ui_queue.put(lambda: app.ui_status("Lỗi tính toán khối lượng."))
        return False

    reqs = mt5_service.build_trade_requests(
        symbol=mt5_ctx.get("symbol", ""),
        direction=plan["direction"],
        entry_price=plan["entry"],
        sl_price=plan["sl"],
        tp1_price=plan.get("tp1"),
        tp2_price=plan.get("tp2"),
        total_lots=lots,
        tick=mt5_ctx.get("tick", {}),
        config=cfg,
        info=mt5_ctx.get("info", {})
    )

    if cfg.auto_trade.dry_run:
        app.ui_queue.put(lambda: app.ui_status(f"DRY-RUN ({grade}): Lệnh đã được ghi log."))
        log_handler.log_trade(
            run_config=cfg,
            trade_data={"stage": "dry-run", "grade": grade, "requests": reqs},
        )
        return True

    has_errors = False
    for req in reqs:
        res = mt5_service.order_send_smart(req)
        if not res or res.retcode != mt5.TRADE_RETCODE_DONE:
            has_errors = True
            app.ui_queue.put(lambda: app.ui_status(f"Lỗi gửi lệnh: {getattr(res, 'comment', 'Không rõ')}"))
    
    if not has_errors:
        app.ui_queue.put(lambda: app.ui_status(f"Đã đặt lệnh cho setup hạng {grade}."))
        return True
        
    return False


def manage_existing_trades(
    app: AppUI, combined_text: str, mt5_ctx: dict[str, Any], cfg: RunConfig
) -> bool:
    """Quản lý các giao dịch hiện có dựa trên phân tích chuyên sâu của AI."""
    open_positions = mt5_ctx.get("positions", [])
    if not open_positions:
        return False

    # Trích xuất khối JSON và lấy kế hoạch quản lý từ đó
    ai_analysis = report_parser.extract_json_block_prefer(combined_text)
    management_actions = ai_analysis.get("management_plan", {})
    if not management_actions:
        logger.debug("Không tìm thấy 'management_plan' trong phân tích của AI.")
        return False

    action_taken = False
    for pos in open_positions:
        ticket = pos.get("ticket")
        if not ticket:
            continue

        action = management_actions.get(str(ticket)) or management_actions.get("ALL")
        if not action:
            continue

        # Xử lý đóng lệnh một phần
        if action.get("action") == "CLOSE_PARTIAL" and action.get("percentage"):
            success = mt5_service.close_position_partial(ticket, action["percentage"])
            if success:
                action_taken = True

        # Xử lý cập nhật SL/TP
        new_sl = action.get("sl")
        if isinstance(new_sl, str):
            if new_sl == "entry":
                new_sl = pos.get("price_open")
            elif new_sl in ["last_swing_low_m5", "last_swing_high_m5"]:
                tf_code = mt5.TIMEFRAME_M5 if mt5 else None
                if not tf_code:
                    continue
                bars_to_check = 20 # Có thể đưa vào config
                low, high = mt5_service.get_last_swing_low_high(pos["symbol"], tf_code, bars_to_check)
                
                is_buy = pos.get("type") == 0 # 0 for BUY, 1 for SELL
                if is_buy and new_sl == "last_swing_low_m5" and low:
                    new_sl = low
                elif not is_buy and new_sl == "last_swing_high_m5" and high:
                    new_sl = high
                else:
                    new_sl = None # Không tìm thấy giá trị hợp lệ, không thay đổi SL

        if new_sl is not None or action.get("tp") is not None:
            # Đảm bảo new_sl là float trước khi gọi modify_position
            final_sl = float(new_sl) if new_sl is not None else None
            success = mt5_service.modify_position(ticket, sl=final_sl, tp=action.get("tp"))
            if success:
                action_taken = True
                
    if action_taken:
        app.ui_queue.put(lambda: app.ui_status("Đã thực hiện hành động quản lý lệnh."))

    return action_taken
