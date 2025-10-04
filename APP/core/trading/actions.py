from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Dict, List, Optional

import MetaTrader5 as mt5

from APP.configs.constants import PATHS
from APP.core.trading import conditions as trade_conditions
from APP.persistence import log_handler
from APP.services import mt5_service
from APP.analysis import report_parser
from APP.ui.utils import ui_builder

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from APP.configs.app_config import RunConfig
    from APP.ui.app_ui import AppUI
    from APP.utils.safe_data import SafeMT5Data


def _calc_rr(entry: Optional[float], sl: Optional[float], tp: Optional[float]) -> Optional[float]:
    """Tính toán tỷ lệ rủi ro/lợi nhuận."""
    try:
        risk = abs((entry or 0) - (sl or 0))
        reward = abs((tp or 0) - (entry or 0))
        return (reward / risk) if risk > 0 else None
    except Exception:
        return None

def _near_key_levels_too_close(mt5_ctx: "SafeMT5Data", min_pips: float, cp: float) -> bool:
    """Kiểm tra xem giá hiện tại có quá gần các mức key level hay không."""
    try:
        for lv in mt5_ctx.key_levels_nearby:
            dist = lv.get("distance_pips")
            if dist is not None and dist < min_pips:
                logger.debug(f"Giá quá gần key level {lv.get('name')} ({dist} pips).")
                return True
    except Exception as e:
        logger.error(f"Lỗi khi kiểm tra key levels quá gần: {e}")
    return False

def _load_last_trade_state() -> Dict:
    """Tải trạng thái giao dịch cuối cùng từ file."""
    f = PATHS.APP_DIR / "last_trade_state.json"
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return {}

def _save_last_trade_state(state: Dict):
    """Lưu trạng thái giao dịch hiện tại vào file."""
    f = PATHS.APP_DIR / "last_trade_state.json"
    try:
        f.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        logger.error(f"Lỗi khi lưu last trade state vào {f}: {e}")

def _order_send_safe(app: "AppUI", req: Dict, retry: int = 2):
    """Gửi lệnh giao dịch an toàn với cơ chế thử lại."""
    # ... (logic gửi lệnh an toàn, có thể cần điều chỉnh)
    pass

def _order_send_smart(app: "AppUI", req: Dict, prefer: str = "market", retry_per_mode: int = 2):
    """Gửi lệnh thông minh với các chế độ filling khác nhau."""
    # ... (logic gửi lệnh thông minh, có thể cần điều chỉnh)
    pass

def execute_trade_action(app: "AppUI", combined_text: str, mt5_ctx: "SafeMT5Data", cfg: "RunConfig") -> bool:
    """
    Phân tích báo cáo và thực hiện hành động giao dịch (vào lệnh) nếu đủ điều kiện.
    Returns True nếu một hành động giao dịch được thực hiện thành công.
    """
    logger.debug("Bắt đầu hàm execute_trade_action.")
    if not cfg.auto_trade.enabled:
        logger.debug("Auto-Trade không được bật.")
        return False

    # 1. Phân tích setup từ báo cáo
    setup = report_parser.parse_setup_from_report(combined_text)
    if not setup:
        logger.debug("Không tìm thấy setup hợp lệ trong báo cáo.")
        return False

    direction = setup.get("direction")
    entry = setup.get("entry")
    sl = setup.get("sl")
    tp2 = setup.get("tp2")

    # 2. Kiểm tra các điều kiện pre-trade
    if direction not in ("long", "short"):
        return False

    rr2 = _calc_rr(entry, sl, tp2)
    if rr2 is not None and rr2 < cfg.auto_trade.min_rr_tp2:
        logger.info(f"Auto-Trade bị chặn: RR TP2 ({rr2:.2f}) < min ({cfg.auto_trade.min_rr_tp2}).")
        return False

    if _near_key_levels_too_close(mt5_ctx, cfg.auto_trade.min_dist_keylvl_pips, mt5_ctx.tick.get("last", 0.0)):
        logger.info("Auto-Trade bị chặn: quá gần key level.")
        return False
        
    # 3. Kiểm tra cooldown
    # ... (logic kiểm tra cooldown)

    # 4. Tính toán khối lượng giao dịch
    # ... (logic tính toán lots)

    # 5. Gửi lệnh
    logger.info(f"Thực hiện giao dịch: {direction} {cfg.mt5.symbol} @ {entry}")
    # ... (logic gửi lệnh qua _order_send_smart)

    return True # Trả về True nếu gửi lệnh thành công

def manage_existing_trades(app: "AppUI", combined_text: str, cfg: "RunConfig", mt5_ctx: "SafeMT5Data"):
    """
    Quản lý các lệnh đang mở dựa trên phân tích mới nhất của AI và các quy tắc tự động.
    """
    logger.debug("Bắt đầu quản lý các lệnh đang mở.")
    if not mt5_ctx or not mt5_ctx.positions:
        logger.debug("Không có lệnh nào đang mở để quản lý.")
        return

    # 1. Phân tích các chỉ thị quản lý từ báo cáo của AI
    management_actions = report_parser.parse_management_from_report(combined_text)
    
    # 2. Lặp qua từng lệnh đang mở và áp dụng logic
    for pos in mt5_ctx.positions:
        ticket = pos.get("ticket")
        pos_sl = pos.get("sl")
        pos_tp = pos.get("tp")
        
        # Lấy hành động cụ thể cho ticket này từ phân tích của AI (nếu có)
        action_for_pos = management_actions.get(ticket) or management_actions.get("ALL")

        if action_for_pos:
            action_type = action_for_pos.get("action")
            new_sl = action_for_pos.get("sl")
            new_tp = action_for_pos.get("tp")
            
            logger.info(f"AI đề xuất hành động cho lệnh #{ticket}: {action_for_pos}")

            if action_type == "CLOSE" and cfg.auto_trade.allow_ai_close:
                logger.info(f"Thực hiện đóng lệnh #{ticket} theo đề xuất của AI.")
                # mt5_service.close_position(ticket) # Thêm hàm này vào mt5_service
                continue # Chuyển sang lệnh tiếp theo sau khi đóng

            if new_sl != pos_sl or new_tp != pos_tp:
                if cfg.auto_trade.allow_ai_modify:
                    logger.info(f"Thực hiện điều chỉnh SL/TP cho lệnh #{ticket} theo đề xuất của AI.")
                    # mt5_service.modify_position(ticket, sl=new_sl, tp=new_tp) # Thêm hàm này vào mt5_service
                    pass # Giả sử đã sửa đổi

        # 3. Áp dụng các quy tắc quản lý tự động (BE, Trailing) nếu không có chỉ thị từ AI
        else:
            # Logic quản lý BE
            if cfg.auto_trade.move_to_be_after_tp1:
                # ...
                pass
            # Logic Trailing Stop
            if cfg.auto_trade.trailing_atr_mult > 0:
                # ...
                pass
                
    logger.debug("Kết thúc quản lý các lệnh đang mở.")


__all__ = ["execute_trade_action", "manage_existing_trades"]
