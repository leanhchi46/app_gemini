from __future__ import annotations
import re
import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from . import utils, report_parser

if TYPE_CHECKING:
    from ..gemini_batch_image_analyzer import GeminiFolderOnceApp, RunConfig

def save_json_report(app: "GeminiFolderOnceApp", text: str, cfg: "RunConfig", names: list[str], context_obj: dict):
    """
    Saves the JSON report file.
    This function is refactored from the main app class for better organization.
    """
    d = app._get_reports_dir(cfg.folder)
    if not d:
        app.ui_status("Lỗi: Không thể xác định thư mục Reports để lưu .json.")
        return
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    found = []
    for m in re.finditer(r"\{[\s\S]*?\}", text):
        j = m.group(0).strip()
        try:
            json.loads(j)
            found.append(j)
        except Exception:
            continue
    
    if not found:
        app.ui_status("Cảnh báo: Không tìm thấy khối JSON nào để lưu.")

    data_to_save = context_obj if isinstance(context_obj, dict) else {}

    if found:
        if "blocks" in data_to_save and isinstance(data_to_save["blocks"], list):
            data_to_save["blocks"].extend(found)
        else:
            data_to_save["blocks"] = found
    
    if "seven_lines" not in data_to_save:
        lines, sig, high = report_parser.extract_seven_lines(text)
        if lines:
            data_to_save["seven_lines"] = lines
            data_to_save["signature"] = sig
            data_to_save["high_prob"] = bool(high)
    
    if "cycle" not in data_to_save:
        data_to_save["cycle"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    if "images_tf_map" not in data_to_save:
        data_to_save["images_tf_map"] = app._images_tf_map(names)

    out = d / f"ctx_{ts}.json"
    try:
        out.write_text(json.dumps(data_to_save, ensure_ascii=False, indent=2), encoding="utf-8")
        app.ui_status(f"Đã lưu thành công file: {out.name}")
        
        # Cleanup old .json files
        utils.cleanup_old_files(d, "ctx_*.json", 10)
        
    except Exception as e:
        app.ui_status(f"LỖI GHI FILE JSON: {e}")
        app.ui_message("error", "Lỗi Lưu JSON", f"Không thể ghi file vào đường dẫn:\n{out}\n\nLỗi: {e}")
        return None

    # --- Log proposed trade for backtesting ---
    try:
        setup = app._parse_setup_from_report(text)
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
