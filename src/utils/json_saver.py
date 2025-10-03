from __future__ import annotations
import re
import json
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from src.utils import utils, report_parser, ui_utils
from src.config.constants import APP_DIR # Cần cho APP_DIR

logger = logging.getLogger(__name__) # Khởi tạo logger

if TYPE_CHECKING:
    from scripts.tool import TradingToolApp
    from src.config.config import RunConfig

def save_json_report(app: "TradingToolApp", text: str, cfg: "RunConfig", names: list[str], composed_str: str):
    """
    Saves the JSON report file.
    This function is refactored from the main app class for better organization.
    """
    logger.debug("Bắt đầu save_json_report.")
    d = app._get_reports_dir(cfg.folder)
    if not d:
        ui_utils.ui_status(app, "Lỗi: Không thể xác định thư mục Reports để lưu .json.")
        logger.error("Không thể xác định thư mục Reports để lưu .json.")
        return None # Trả về None khi có lỗi
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    logger.debug(f"Thư mục reports: {d}, timestamp: {ts}.")

    context_obj = {}
    if composed_str:
        try:
            context_obj = json.loads(composed_str)
            logger.debug("Đã parse composed_str thành context_obj.")
        except json.JSONDecodeError as e:
            logger.warning(f"Could not decode composed context, attempting repair. Error: {e}. Content: {composed_str[:500]}...")
            try:
                repaired_composed = report_parser.repair_json_string(composed_str)
                context_obj = json.loads(repaired_composed)
                logger.debug("Đã sửa chữa và parse composed_str thành công.")
            except Exception as repair_e:
                logger.error(f"Failed to repair and parse composed context: {repair_e}")
                context_obj = {} # Ultimate fallback
    
    # Use the robust find_balanced_json_after to extract all JSON blocks
    found = []
    start_search_idx = 0
    while start_search_idx < len(text):
        brace_idx = text.find("{", start_search_idx)
        if brace_idx == -1:
            break
        
        json_str, next_idx = report_parser.find_balanced_json_after(text, brace_idx) # Cập nhật lệnh gọi
        
        if json_str and next_idx:
            try:
                # Repair and validate the JSON string
                repaired_str = report_parser.repair_json_string(json_str)
                json.loads(repaired_str, strict=False) # Validate after repair
                found.append(repaired_str) # Save the repaired version
                start_search_idx = next_idx
                logger.debug(f"Tìm thấy và parse thành công JSON block. Next search from: {next_idx}")
            except Exception as e:
                # Log the error and the problematic string for debugging
                logger.error(f"Failed to parse or repair JSON block: {e}")
                logger.debug(f"Problematic JSON string:\n---\n{json_str}\n---")
                start_search_idx = brace_idx + 1
        else:
            # No more balanced JSON found
            break
    
    if not found:
        ui_utils.ui_status(app, "Cảnh báo: Không tìm thấy khối JSON nào để lưu.")
        logger.warning("Không tìm thấy khối JSON nào để lưu.")

    data_to_save = context_obj if isinstance(context_obj, dict) else {}

    if found:
        if "blocks" in data_to_save and isinstance(data_to_save["blocks"], list):
            data_to_save["blocks"].extend(found)
        else:
            data_to_save["blocks"] = found
        logger.debug(f"Đã thêm {len(found)} JSON blocks vào data_to_save.")
    
    # Use the new universal parsers to extract and save standardized data
    summary_lines, sig, high_prob = report_parser.extract_summary_lines(text)
    if summary_lines:
        data_to_save["summary_lines"] = summary_lines
        data_to_save["signature"] = sig
        data_to_save["high_prob"] = bool(high_prob)
        logger.debug("Đã trích xuất và lưu summary lines, signature, high_prob.")

    parsed_plan = report_parser.parse_setup_from_report(text)
    if parsed_plan:
        data_to_save["parsed_plan"] = parsed_plan
        logger.debug(f"Đã parse và lưu plan: {parsed_plan}")
    
    if "cycle" not in data_to_save:
        data_to_save["cycle"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        logger.debug(f"Đã đặt cycle: {data_to_save['cycle']}")
    
    if "images_tf_map" not in data_to_save:
        data_to_save["images_tf_map"] = app._images_tf_map(names)
        logger.debug("Đã tạo và lưu images_tf_map.")

    out = d / f"ctx_{ts}.json"
    try:
        out.write_text(json.dumps(data_to_save, ensure_ascii=False, indent=2), encoding="utf-8")
        ui_utils.ui_status(app, f"Đã lưu thành công file: {out.name}")
        logger.info(f"Đã lưu file JSON báo cáo thành công tại: {out.name}")
        
        # Cleanup old .json files
        utils.cleanup_old_files(d, "ctx_*.json", 10)
        logger.debug("Đã dọn dẹp các file JSON cũ.")
        
    except Exception as e:
        logging.exception(f"CRITICAL ERROR during final JSON save to {out.name}")
        ui_utils.ui_status(app, f"LỖI GHI FILE JSON: {e}")
        ui_utils.ui_message(app, "error", "Lỗi Lưu JSON", f"Không thể ghi file vào đường dẫn:\n{out}\n\nLỗi: {e}")
        return None

    # --- Log proposed trade for backtesting ---
    try:
        setup = report_parser.parse_setup_from_report(text)
        if setup and setup.get("direction") and setup.get("entry"):
            logger.debug("Tìm thấy setup giao dịch, log cho backtesting.")
            # Extract context snapshot for logging
            ctx_snapshot = {}
            if context_obj:
                inner_ctx = context_obj.get("CONTEXT_COMPOSED", {})
                ctx_snapshot = {
                    "session": inner_ctx.get("session"),
                    "trend_checklist": inner_ctx.get("trend_checklist", {}).get("trend"),
                    "volatility_regime": (inner_ctx.get("environment_flags") or {}).get("volatility_regime"),
                    "trend_regime": (inner_ctx.get("environment_flags") or {}).get("trend_regime"),
                }

            trade_log_payload = {
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "symbol": cfg.mt5_symbol,
                "report_file": out.name,
                "setup": setup,
                "context_snapshot": ctx_snapshot
            }
            app._log_proposed_trade(trade_log_payload, folder_override=cfg.folder)
            logger.debug("Đã log proposed trade.")
    except Exception as e:
        logger.warning(f"Lỗi khi log proposed trade cho backtesting: {e}")
        pass # Silently fail if parsing/logging fails

    logger.debug("Kết thúc save_json_report.")
    return out
