from __future__ import annotations
import json
import logging
from datetime import datetime
from typing import TYPE_CHECKING, List, Dict, Any, Tuple

from src.core import no_run
from src.core import no_trade
from src.utils import ui_utils
from src.utils import md_saver
from src.utils import mt5_utils # Cần cho build_context_from_app
from src.utils.safe_data import SafeMT5Data # Cần cho type hint

if TYPE_CHECKING:
    from scripts.tool import TradingToolApp
    from src.config.config import RunConfig

def handle_no_run_check(app: "TradingToolApp", cfg: "RunConfig") -> bool:
    """
    Kiểm tra điều kiện NO-RUN và xử lý logic thoát sớm nếu cần.
    Trả về True nếu worker nên thoát sớm, False nếu tiếp tục.
    """
    should_run, reason = no_run.check_no_run_conditions(app)
    if not should_run:
        app.ui_status(reason)
        app._log_trade_decision({
            "stage": "no-run-skip",
            "t": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "reason": reason
        }, folder_override=(app.mt5_symbol_var.get().strip() or None))
        return True # Thoát sớm
    return False

def handle_no_trade_check(app: "TradingToolApp", cfg: "RunConfig", safe_mt5_data: SafeMT5Data, mt5_dict: Dict, context_block: str, mt5_json_full: str) -> bool:
    """
    Kiểm tra điều kiện NO-TRADE và xử lý logic thoát sớm nếu cần.
    Trả về True nếu worker nên thoát sớm, False nếu tiếp tục.
    """
    if cfg.nt_enabled and mt5_dict:
        ok, reasons, _, _, _ = no_trade.evaluate(
            safe_mt5_data, cfg, cache_events=app.ff_cache_events_local,
            cache_fetch_time=app.ff_cache_fetch_time, ttl_sec=300
        )
        app.last_no_trade_ok = bool(ok)
        app.last_no_trade_reasons = list(reasons or [])
        if not ok:
            app._log_trade_decision({
                "stage": "no-trade",
                "t": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "reasons": reasons
            }, folder_override=(app.mt5_symbol_var.get().strip() or None))
            
            note = "NO-TRADE: Điều kiện giao dịch không thỏa.\n- " + "\n- ".join(reasons)
            if context_block: note += f"\n\n{context_block}"
            if mt5_json_full: note += f"\n\n[PHỤ LỤC_MT5_JSON]\n{mt5_json_full}"
            
            app.combined_report_text = note
            ui_utils.ui_detail_replace(app, note)
            app._auto_save_report(note, cfg)
            ui_utils.ui_refresh_history_list(app)
            
            if mt5_dict: # auto_trade.mt5_manage_be_trailing(app, mt5_dict, cfg) # Tạm thời vô hiệu hóa
                pass # Giữ khối lệnh hợp lệ sau khi comment
            return True # Thoát sớm
    return False

def handle_no_change_scenario(app: "TradingToolApp", cfg: "RunConfig"):
    """
    Xử lý trường hợp không có ảnh nào thay đổi so với lần chạy trước.
    Sẽ tạo một báo cáo ngắn gọn, quản lý các lệnh đang chạy và thoát sớm.
    """
    app.ui_status("Ảnh không đổi, tạo báo cáo nhanh...")
    composed = app.compose_context(cfg, budget_chars=max(800, int(cfg.ctx_limit))) or ""
    plan = None
    if composed:
        try:
            _obj = json.loads(composed)
            plan = (_obj.get("CONTEXT_COMPOSED") or {}).get("latest_plan")
        except Exception:
            pass
    
    context_block = f"\n\n[CONTEXT_COMPOSED]\n{composed}" if composed else ""
    mt5_ctx_text = mt5_utils.build_context_from_app(app, plan=plan, cfg=cfg) if cfg.mt5_enabled else ""
    
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
                # auto_trade.mt5_manage_be_trailing(app, mt5_dict_cache, cfg) # Tạm thời vô hiệu hóa
                pass # Giữ khối lệnh hợp lệ sau khi comment
        except Exception as e:
            logging.warning(f"Lỗi khi quản lý BE/Trailing trong kịch bản không thay đổi: {e}")
            
    # Không raise SystemExit ở đây, mà để main_worker xử lý
