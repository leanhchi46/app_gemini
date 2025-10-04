from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List

from APP.configs.constants import PATHS
from APP.analysis import report_parser

if TYPE_CHECKING:
    from APP.configs.app_config import RunConfig
    from APP.ui.app_ui import AppUI
    from APP.utils.safe_data import SafeMT5Data

logger = logging.getLogger(__name__)


def select_prompt_dynamically(app: "AppUI", cfg: "RunConfig", safe_mt5_data: "SafeMT5Data", prompt_no_entry: str, prompt_entry_run: str) -> str:
    """
    Chọn prompt phù hợp dựa trên trạng thái giao dịch hiện tại (có lệnh đang mở hay không).
    """
    logger.debug("Bắt đầu hàm select_prompt_dynamically.")
    prompt_to_use = ""
    has_positions = cfg.mt5.enabled and safe_mt5_data and safe_mt5_data.positions
    logger.debug(f"MT5 enabled: {cfg.mt5.enabled}, có lệnh đang mở: {bool(has_positions)}")

    try:
        if has_positions:
            prompt_path = PATHS.APP_DIR / "prompts" / "prompt_entry_run_vision.txt"
            prompt_to_use = prompt_path.read_text(encoding="utf-8")
            app.ui_status("Worker: Lệnh đang mở, dùng prompt Vision Quản Lý Lệnh.")
            logger.info(f"Đã chọn prompt từ file: {prompt_path.name} (Lệnh đang mở).")
        else:
            prompt_path = PATHS.APP_DIR / "prompts" / "prompt_no_entry_vision.txt"
            prompt_to_use = prompt_path.read_text(encoding="utf-8")
            app.ui_status("Worker: Không có lệnh mở, dùng prompt Vision Tìm Lệnh Mới.")
            logger.info(f"Đã chọn prompt từ file: {prompt_path.name} (Không có lệnh mở).")
    except Exception as e:
        app.ui_status(f"Lỗi đọc prompt từ file: {e}. Sử dụng prompt dự phòng.")
        logger.error(f"Lỗi đọc prompt từ file: {e}. Sử dụng prompt dự phòng.")
        prompt_to_use = prompt_entry_run if has_positions else prompt_no_entry

    logger.debug("Kết thúc hàm select_prompt_dynamically.")
    return prompt_to_use


def construct_final_prompt(app: "AppUI", prompt: str, mt5_dict: Dict, safe_mt5_data: "SafeMT5Data", context_block: str, mt5_json_full: str, paths: List[str]) -> str:
    """
    Xây dựng nội dung prompt cuối cùng để gửi đến model AI.
    """
    logger.debug("Bắt đầu hàm construct_final_prompt.")
    tf_section = app._build_timeframe_section([Path(p).name for p in paths]).strip()
    parts_text = []
    if tf_section:
        parts_text.append(f"### Nhãn khung thời gian (tự nhận từ tên tệp)\n{tf_section}\n\n")

    if mt5_dict:
        structured_report = report_parser.parse_mt5_data_to_report(safe_mt5_data)
        prompt = prompt.replace(
            "[Dữ liệu từ `CONCEPT_VALUE_TABLE` và `EXTRACT_JSON` sẽ được chèn vào đây]",
            f"DỮ LIỆU SỐ THAM KHẢO:\n{structured_report}"
        )
        if context_block:
            prompt = prompt.replace(
                "[Dữ liệu từ `CONTEXT_COMPOSED` sẽ được chèn vào đây]",
                f"DỮ LIỆU LỊCH SỬ (VÒNG TRƯỚC):\n{context_block}"
            )
        else:
            prompt = prompt.replace(
                "**DỮ LIỆU LỊCH SỬ (NẾU CÓ):**\n[Dữ liệu từ `CONTEXT_COMPOSED` sẽ được chèn vào đây]",
                ""
            )
        parts_text.append(prompt)
    else:
        parts_text.append(prompt)
        if mt5_json_full:
            parts_text.append(f"\n\n[PHỤ LỤC_MT5_JSON]\n{mt5_json_full}")

    final_prompt_content = "".join(list(dict.fromkeys(parts_text)))
    logger.debug(f"Kết thúc hàm construct_final_prompt. Độ dài prompt cuối cùng: {len(final_prompt_content)}.")
    return final_prompt_content

__all__ = ["select_prompt_dynamically", "construct_final_prompt"]
