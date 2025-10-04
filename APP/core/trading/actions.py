from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List

from APP.analysis import report_parser
from APP.configs.workspace_config import get_workspace_dir
from APP.core.trading import conditions
from APP.persistence import log_handler
from APP.services import mt5_service
from APP.ui.utils import ui_builder

if TYPE_CHECKING:
    from APP.configs.app_config import RunConfig
    from APP.ui.app_ui import AppUI

logger = logging.getLogger(__name__)

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None
    logger.warning("Không thể import MetaTrader5. Các chức năng MT5 sẽ bị vô hiệu hóa.")


def _get_last_trade_state_path() -> "Path":
    """Trả về đường dẫn đến tệp trạng thái giao dịch cuối cùng."""
    return get_workspace_dir() / "last_trade_state.json"


def _load_last_trade_state() -> Dict:
    """Tải trạng thái giao dịch cuối cùng từ tệp."""
    f = _get_last_trade_state_path()
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_last_trade_state(state: Dict):
    """Lưu trạng thái giao dịch hiện tại vào tệp."""
    f = _get_last_trade_state_path()
    try:
        f.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    except IOError as e:
        logger.error(f"Lỗi khi lưu trạng thái giao dịch cuối cùng: {e}")


def execute_trade_action(
    app: AppUI, combined_text: str, mt5_ctx: Dict, cfg: RunConfig
) -> bool:
    """
    Phân tích báo cáo, kiểm tra điều kiện và đặt lệnh thị trường/lệnh chờ nếu hợp lệ.
    """
    if not cfg.auto_trade_enabled or not mt5:
        return False

    # Phân tích setup từ báo cáo của AI
    setup = report_parser.parse_trade_setup_from_report(combined_text)
    if not setup or setup.get("direction") not in ("long", "short"):
        return False

    # Lấy dữ liệu thị trường cần thiết
    symbol = cfg.mt5_symbol
    tick = mt5_ctx.get("tick", {})
    ask = tick.get("ask", 0.0)
    bid = tick.get("bid", 0.0)
    current_price = tick.get("last") or bid or ask
    info = mt5_ctx.get("info", {})
    point = info.get("point", 0.0)
    digits = info.get("digits", 5)

    # Kiểm tra các điều kiện giao dịch bổ sung
    if not _is_trade_setup_valid(app, setup, mt5_ctx, cfg, current_price):
        return False

    # Tính toán khối lượng giao dịch
    volume = mt5_service.calculate_volume(
        symbol,
        cfg.trade_size_mode,
        setup["sl"],
        setup["entry"],
        cfg,
        info,
    )
    if not volume or volume < info.get("volume_min", 0.01):
        ui_builder.message(app, "warning", "Auto-Trade", f"Khối lượng ({volume}) không hợp lệ.")
        return False

    # Chuẩn bị và gửi lệnh
    return _prepare_and_send_orders(
        app, setup, cfg, symbol, current_price, volume, point, digits
    )


def _is_trade_setup_valid(
    app: AppUI, setup: Dict, mt5_ctx: Dict, cfg: RunConfig, current_price: float
) -> bool:
    """Kiểm tra tính hợp lệ của setup giao dịch."""
    rr2 = mt5_service.calculate_rr(setup.get("entry"), setup.get("sl"), setup.get("tp2"))
    if rr2 is not None and rr2 < cfg.trade_min_rr_tp2:
        log_handler.log_trade(
            {"stage": "precheck-fail", "reason": "rr_below_min", "rr_tp2": rr2}
        )
        return False

    if mt5_service.is_near_key_level(
        mt5_ctx, cfg.trade_min_dist_keylvl_pips, current_price
    ):
        log_handler.log_trade({"stage": "precheck-fail", "reason": "near_key_level"})
        return False

    # Kiểm tra cooldown
    setup_sig = hashlib.sha1(
        f"{cfg.mt5_symbol}|{setup.get('direction')}|{setup.get('entry')}|{setup.get('sl')}".encode()
    ).hexdigest()
    state = _load_last_trade_state()
    if state.get("sig") == setup_sig and (
        time.time() - state.get("time", 0)
    ) < cfg.trade_cooldown_min * 60:
        logger.info("Auto-Trade bị chặn: setup trùng lặp, cooldown active.")
        return False

    return True


def _prepare_and_send_orders(
    app: AppUI,
    setup: Dict,
    cfg: RunConfig,
    symbol: str,
    current_price: float,
    volume: float,
    point: float,
    digits: int,
) -> bool:
    setup_sig = hashlib.sha1(
        f"{symbol}|{setup.get('direction')}|{setup.get('entry')}|{setup.get('sl')}".encode()
    ).hexdigest()
    """Xây dựng và gửi các yêu cầu đặt lệnh đến MT5."""
    use_pending = (
        abs(setup["entry"] - current_price) / point
        >= cfg.trade_pending_threshold_points
    )

    vol1, vol2 = mt5_service.split_volume(volume, cfg.trade_split_tp1_pct, info={
        "volume_min": mt5_service.get_symbol_info_value(symbol, "volume_min", 0.01),
        "volume_step": mt5_service.get_symbol_info_value(symbol, "volume_step", 0.01),
    })
    if not vol1 or not vol2:
        return False

    requests = mt5_service.build_trade_requests(
        setup, symbol, vol1, vol2, cfg, use_pending, current_price, digits
    )

    if cfg.auto_trade_dry_run:
        ui_builder.message(app, "info", "Auto-Trade", "DRY-RUN: Ghi log, không gửi lệnh.")
        log_handler.log_trade({"stage": "dry-run", "requests": requests})
        _save_last_trade_state({"sig": setup_sig, "time": time.time()})
        return True

    results = [mt5_service.send_order_smart(app, req) for req in requests]
    
    if all(res and res.retcode == mt5.TRADE_RETCODE_DONE for res in results):
        _save_last_trade_state({"sig": setup_sig, "time": time.time()})
        ui_builder.message(app, "info", "Auto-Trade", "Đã đặt lệnh TP1/TP2 thành công.")
        return True
    else:
        ui_builder.message(app, "error", "Auto-Trade", "Có lỗi xảy ra khi đặt lệnh.")
        return False


def manage_existing_trades(app: AppUI, mt5_ctx: Dict, cfg: RunConfig):
    """
    Quản lý các lệnh đang mở, ví dụ: dời SL về entry, trailing stop.
    (Đây là placeholder, sẽ được triển khai logic chi tiết sau)
    """
    if not cfg.auto_trade_enabled or not mt5:
        return

    logger.debug("Bắt đầu quản lý các lệnh hiện có (BE/Trailing).")
    
    # Logic ví dụ:
    # 1. Lấy danh sách các lệnh đang mở có magic number phù hợp.
    # 2. Với mỗi cặp lệnh (TP1, TP2), kiểm tra xem giá đã chạm TP1 chưa.
    # 3. Nếu TP1 đã bị đóng (do chốt lời), dời SL của lệnh TP2 về giá entry.
    # 4. Triển khai logic trailing stop cho các lệnh còn lại nếu được cấu hình.
    
    pass
