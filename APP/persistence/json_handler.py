from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List

from APP.analysis import report_parser
from APP.persistence import log_handler
from APP.utils import general_utils

if TYPE_CHECKING:
    from APP.configs.app_config import RunConfig
    from APP.ui.app_ui import AppUI

logger = logging.getLogger(__name__)


class JsonSaver:
    def __init__(self, app: AppUI):
        # Giữ lại `app` để truy cập các phương thức helper không dễ di chuyển
        # như `_images_tf_map`, nhưng logic chính sẽ được tách rời.
        self.app = app

    def save_report(
        self,
        text: str,
        cfg: RunConfig,
        names: List[str],
        composed_str: str = "",
    ) -> Path | None:
        """
        Lưu báo cáo phân tích dưới dạng tệp JSON có cấu trúc.
        """
        reports_dir = self.app.get_reports_dir(folder_override=cfg.folder)
        if not reports_dir:
            logger.error("Không thể xác định thư mục Reports để lưu .json.")
            return None

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Xây dựng đối tượng dữ liệu để lưu
        data_to_save = self._build_data_to_save(text, names, composed_str)

        out_path = reports_dir / f"ctx_{ts}.json"
        try:
            out_path.write_text(
                json.dumps(data_to_save, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            logger.info(f"Đã lưu báo cáo JSON thành công tại: {out_path.name}")
            general_utils.cleanup_old_files(reports_dir, "ctx_*.json", 10)
        except IOError as e:
            logger.exception(f"LỖI NGHIÊM TRỌNG khi lưu JSON vào {out_path.name}")
            return None

        # Ghi log giao dịch được đề xuất để backtest
        self._log_proposed_trade(data_to_save, cfg, out_path.name)

        return out_path

    def _build_data_to_save(
        self, text: str, names: List[str], composed_str: str
    ) -> Dict[str, Any]:
        """Xây dựng đối tượng dict cuối cùng để lưu vào tệp JSON."""
        data = {}
        if composed_str:
            try:
                data = json.loads(composed_str)
            except json.JSONDecodeError:
                logger.warning("Không thể phân tích composed_str, bắt đầu với dict rỗng.")

        # Trích xuất và thêm các khối JSON từ văn bản báo cáo
        json_blocks = report_parser.extract_json_block(text)
        if json_blocks and not json_blocks.get("error"):
            data["blocks"] = data.get("blocks", []) + [json_blocks]

        # Trích xuất và thêm thông tin tóm tắt
        summary_lines, sig, high_prob = report_parser.extract_summary_lines(text)
        data.update({
            "summary_lines": summary_lines,
            "signature": sig,
            "high_prob": high_prob,
        })

        # Trích xuất và thêm kế hoạch giao dịch
        data["parsed_plan"] = report_parser.parse_trade_setup_from_report(text)
        
        # Thêm siêu dữ liệu
        data["cycle"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        data["images_tf_map"] = self.app.images_tf_map(names)

        return data

    def _log_proposed_trade(self, data: Dict, cfg: RunConfig, report_filename: str):
        """Ghi log một giao dịch được đề xuất cho mục đích backtesting."""
        setup = data.get("parsed_plan")
        if not (setup and setup.get("direction") and setup.get("entry")):
            return

        try:
            context_snapshot = {}
            inner_ctx = data.get("CONTEXT_COMPOSED", {})
            if inner_ctx:
                context_snapshot = {
                    "session": inner_ctx.get("session"),
                    "trend_checklist": (inner_ctx.get("trend_checklist") or {}).get("trend"),
                    "volatility_regime": (inner_ctx.get("environment_flags") or {}).get("volatility_regime"),
                }

            payload = {
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "symbol": cfg.mt5_symbol,
                "report_file": report_filename,
                "setup": setup,
                "context_snapshot": context_snapshot,
            }
            log_handler.log_proposed_trade(
                payload, self.app.get_reports_dir(folder_override=cfg.folder)
            )
        except Exception as e:
            logger.warning(f"Lỗi khi ghi log proposed trade: {e}")
