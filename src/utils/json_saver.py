from __future__ import annotations
import re
import json
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from src.utils import utils, report_parser, ui_utils
from src.core import context_builder
from src.utils.report_parser import find_balanced_json_after
from src.config.constants import APP_DIR

if TYPE_CHECKING:
    from scripts.tool import TradingToolApp
    from src.config.config import RunConfig

def save_json_report(app: "TradingToolApp", text: str, cfg: "RunConfig", names: list[str], composed_str: str):
    """
    Saves the JSON report file.
    This function is refactored from the main app class for better organization.
    """
    d = app._get_reports_dir(cfg.folder)
    if not d:
        ui_utils.ui_status(app, "Lỗi: Không thể xác định thư mục Reports để lưu .json.")
        return
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    context_obj = {}
    if composed_str:
        try:
            context_obj = json.loads(composed_str)
        except json.JSONDecodeError:
            logging.warning(f"Could not decode composed context, attempting repair. Content: {composed_str[:500]}...")
            try:
                repaired_composed = report_parser.repair_json_string(composed_str)
                context_obj = json.loads(repaired_composed)
            except Exception as repair_e:
                logging.error(f"Failed to repair and parse composed context: {repair_e}")
                context_obj = {} # Ultimate fallback
    
    # Use the robust find_balanced_json_after to extract all JSON blocks
    found = []
    start_search_idx = 0
    while start_search_idx < len(text):
        brace_idx = text.find("{", start_search_idx)
        if brace_idx == -1:
            break
        
        json_str, next_idx = find_balanced_json_after(text, brace_idx)
        
        if json_str and next_idx:
            try:
                # Repair and validate the JSON string
                repaired_str = report_parser.repair_json_string(json_str)
                json.loads(repaired_str, strict=False)
                found.append(repaired_str) # Save the repaired version
                start_search_idx = next_idx
            except Exception as e:
                try:
                    with open(APP_DIR / "json_error_dump.txt", "w", encoding="utf-8") as f:
                        f.write(f"--- JSON PARSE ERROR ---\n")
                        f.write(f"Time: {datetime.now().isoformat()}\n")
                        f.write(f"Error: {e}\n\n")
                        f.write(f"--- Problematic JSON String ---\n")
                        f.write(json_str)
                except Exception:
                    pass  # Ignore if logging fails
                logging.error(f"Failed to parse JSON block: {e}")
                logging.debug(f"Problematic JSON string:\n---\n{json_str}\n---")
                # If it's not valid JSON, just move on
                start_search_idx = brace_idx + 1
        else:
            # No more balanced JSON found
            break
    
    if not found:
        ui_utils.ui_status(app, "Cảnh báo: Không tìm thấy khối JSON nào để lưu.")

    data_to_save = context_obj if isinstance(context_obj, dict) else {}

    if found:
        if "blocks" in data_to_save and isinstance(data_to_save["blocks"], list):
            data_to_save["blocks"].extend(found)
        else:
            data_to_save["blocks"] = found
    
    # Use the new universal parsers to extract and save standardized data
    summary_lines, sig, high_prob = report_parser.extract_summary_lines(text)
    if summary_lines:
        data_to_save["summary_lines"] = summary_lines
        data_to_save["signature"] = sig
        data_to_save["high_prob"] = bool(high_prob)

    parsed_plan = report_parser.parse_setup_from_report(text)
    if parsed_plan:
        data_to_save["parsed_plan"] = parsed_plan
    
    if "cycle" not in data_to_save:
        data_to_save["cycle"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    if "images_tf_map" not in data_to_save:
        data_to_save["images_tf_map"] = app._images_tf_map(names)

    out = d / f"ctx_{ts}.json"
    try:
        out.write_text(json.dumps(data_to_save, ensure_ascii=False, indent=2), encoding="utf-8")
        ui_utils.ui_status(app, f"Đã lưu thành công file: {out.name}")
        
        # Cleanup old .json files
        utils.cleanup_old_files(d, "ctx_*.json", 10)
        
    except Exception as e:
        logging.exception(f"CRITICAL ERROR during final JSON save to {out.name}")
        ui_utils.ui_status(app, f"LỖI GHI FILE JSON: {e}")
        ui_utils.ui_message(app, "error", "Lỗi Lưu JSON", f"Không thể ghi file vào đường dẫn:\n{out}\n\nLỗi: {e}")
        return None

    # --- Log proposed trade for backtesting ---
    try:
        setup = report_parser.parse_setup_from_report(text)
        if setup and setup.get("direction") and setup.get("entry"):
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
    except Exception:
        pass # Silently fail if parsing/logging fails

    return out
