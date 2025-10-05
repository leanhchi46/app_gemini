# -*- coding: utf-8 -*-
"""
Module for handling JSON data persistence.

This module provides the JsonSaver class, which is responsible for parsing,
structuring, and saving analysis reports and trade data into JSON files.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TYPE_CHECKING

# logger và TYPE_CHECKING
logger = logging.getLogger(__name__)
if TYPE_CHECKING:
    from APP.configs.app_config import RunConfig

# Các import cục bộ
from APP.analysis import report_parser
from APP.configs import workspace_config
from APP.persistence import log_handler
from APP.utils import general_utils


class JsonSaver:
    """
    Handles saving and management of JSON report files.

    This class encapsulates the logic for processing raw text reports from the AI model,
    extracting relevant data, structuring it into a standardized JSON format,
    and saving it to the appropriate reports directory. It also handles
    the logging of proposed trades for backtesting purposes.
    """

    def __init__(self, config: RunConfig):
        """
        Initializes the JsonSaver with a specific run configuration.

        Args:
            config: The RunConfig object containing all settings for the current run.
        """
        self.config: RunConfig = config
        self.reports_dir: Path | None = workspace_config.get_reports_dir(
            base_folder=self.config.folder.folder, symbol=self.config.mt5.symbol
        )
        logger.debug(f"JsonSaver được khởi tạo cho workspace: {self.config.folder.folder}")

    def _log_proposed_trade(self, report_text: str, report_path: Path, context_obj: dict[str, Any]) -> None:
        """
        Parses a trade setup from the report and logs it for backtesting.

        Args:
            report_text: The raw text from the AI analysis.
            report_path: The path to the saved JSON report file.
            context_obj: The dictionary containing the composed context.
        """
        try:
            setup = report_parser.parse_setup_from_report(report_text)
            if setup and setup.get("direction") and setup.get("entry"):
                logger.debug("Tìm thấy setup giao dịch, log cho backtesting.")
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
                    "symbol": self.config.mt5.symbol,
                    "report_file": report_path.name,
                    "setup": setup,
                    "context_snapshot": ctx_snapshot
                }
                log_handler.log_trade(run_config=self.config, trade_data=trade_log_payload)
                logger.debug("Đã log proposed trade.")
        except Exception as e:
            logger.warning(f"Lỗi khi log proposed trade cho backtesting: {e}")

    def _build_initial_data(self, composed_context_str: str | None) -> dict[str, Any]:
        """
        Parses the initial context string, with repair mechanism.
        """
        if not composed_context_str:
            return {}
        try:
            return json.loads(composed_context_str)
        except json.JSONDecodeError as e:
            logger.warning(f"Không thể giải mã composed_context, đang thử sửa chữa. Lỗi: {e}.")
            try:
                repaired_composed = report_parser.repair_json_string(composed_context_str)
                return json.loads(repaired_composed)
            except Exception as repair_e:
                logger.error(f"Sửa chữa và parse composed_context thất bại: {repair_e}")
                return {}

    def _extract_and_assimilate_data(
        self, report_text: str, initial_data: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Extracts all relevant data from the report text and merges it.
        """
        data_to_save = initial_data.copy()

        # Extract all valid JSON blocks from the report text
        found_blocks = report_parser.extract_json_block_prefer(report_text)
        if found_blocks:
            if "blocks" in data_to_save and isinstance(data_to_save.get("blocks"), list):
                data_to_save["blocks"].extend(found_blocks)
            else:
                data_to_save["blocks"] = found_blocks
            logger.debug(f"Đã thêm {len(found_blocks)} khối JSON vào data_to_save.")
        else:
            logger.warning("Không tìm thấy khối JSON nào trong báo cáo để lưu.")

        # Extract standardized summary and plan data
        summary_lines, sig, high_prob = report_parser.extract_summary_lines(report_text)
        if summary_lines:
            data_to_save.update({
                "summary_lines": summary_lines,
                "signature": sig,
                "high_prob": bool(high_prob)
            })
            logger.debug("Đã trích xuất và lưu summary_lines, signature, high_prob.")

        parsed_plan = report_parser.parse_setup_from_report(report_text)
        if parsed_plan:
            data_to_save["parsed_plan"] = parsed_plan
            logger.debug(f"Đã parse và lưu plan: {parsed_plan}")

        return data_to_save

    def _finalize_and_write_file(
        self, report_data: dict[str, Any], images_tf_map: dict[str, str]
    ) -> Path | None:
        """
        Adds final metadata and writes the report data to a JSON file.
        """
        if not self.reports_dir:
            logger.error("Không thể ghi file vì thư mục reports chưa được thiết lập.")
            return None
            
        if "cycle" not in report_data:
            report_data["cycle"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if "images_tf_map" not in report_data:
            report_data["images_tf_map"] = images_tf_map

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = self.reports_dir / f"ctx_{ts}.json"

        try:
            out_path.write_text(json.dumps(report_data, ensure_ascii=False, indent=2), encoding="utf-8")
            logger.info(f"Đã lưu file JSON báo cáo thành công tại: {out_path.name}")
            general_utils.cleanup_old_files(self.reports_dir, "ctx_*.json", self.config.folder.max_files)
            return out_path
        except Exception as e:
            logger.exception(f"LỖI NGHIÊM TRỌNG khi lưu JSON cuối cùng vào {out_path.name}")
            return None

    def save_report(
        self,
        report_text: str,
        images_tf_map: dict[str, str],
        composed_context_str: str | None = None
    ) -> Path | None:
        """
        Orchestrates the saving of the full analysis report as a JSON file.
        """
        logger.debug("Bắt đầu quá trình lưu báo cáo JSON.")
        if not self.reports_dir or not self.reports_dir.is_dir():
            logger.error("Không thể xác định thư mục Reports hoặc thư mục không tồn tại để lưu .json.")
            return None

        # Stage 1: Build initial data from context
        initial_data = self._build_initial_data(composed_context_str)

        # Stage 2: Extract and assimilate data from the main report text
        final_data = self._extract_and_assimilate_data(report_text, initial_data)

        # Stage 3: Finalize with metadata and write to disk
        saved_path = self._finalize_and_write_file(final_data, images_tf_map)

        if saved_path:
            # Stage 4: Log the proposed trade for backtesting if save was successful
            self._log_proposed_trade(report_text, saved_path, initial_data)

        logger.debug("Kết thúc quá trình lưu báo cáo JSON.")
        return saved_path
