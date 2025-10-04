from __future__ import annotations
from pathlib import Path
from typing import TYPE_CHECKING, List, Dict
import logging # Thêm import logging

from src.config.constants import APP_DIR
from src.utils import report_parser # Cần cho parse_mt5_data_to_report

logger = logging.getLogger(__name__) # Khởi tạo logger

if TYPE_CHECKING:
    from scripts.tool import TradingToolApp
    from src.config.config import RunConfig
    from src.utils.safe_data import SafeMT5Data

def select_prompt_dynamically(app: "TradingToolApp", cfg: "RunConfig", safe_mt5_data: SafeMT5Data, prompt_no_entry: str, prompt_entry_run: str) -> str:
    """
    Chọn prompt phù hợp dựa trên trạng thái giao dịch hiện tại (có lệnh đang mở hay không).
    """
    logger.debug("Bắt đầu hàm select_prompt_dynamically.")
    prompt_to_use = ""
    has_positions = cfg.mt5_enabled and safe_mt5_data and safe_mt5_data.raw and safe_mt5_data.raw.get("positions")
    logger.debug(f"MT5 enabled: {cfg.mt5_enabled}, có lệnh đang mở: {bool(has_positions)}")
    
    try:
        if has_positions:
            prompt_path = APP_DIR / "prompt_entry_run_vision.txt"
            prompt_to_use = prompt_path.read_text(encoding="utf-8")
            app.ui_status("Worker: Lệnh đang mở, dùng prompt Vision Quản Lý Lệnh.")
            logger.info(f"Đã chọn prompt từ file: {prompt_path.name} (Lệnh đang mở).")
        else:
            prompt_path = APP_DIR / "prompt_no_entry_vision.txt"
            prompt_to_use = prompt_path.read_text(encoding="utf-8")
            app.ui_status("Worker: Không có lệnh mở, dùng prompt Vision Tìm Lệnh Mới.")
            logger.info(f"Đã chọn prompt từ file: {prompt_path.name} (Không có lệnh mở).")
    except Exception as e:
        app.ui_status(f"Lỗi đọc prompt từ file: {e}. Sử dụng prompt dự phòng.")
        logger.error(f"Lỗi đọc prompt từ file: {e}. Sử dụng prompt dự phòng.")
        # Cơ chế dự phòng: sử dụng prompt cũ nếu đọc file lỗi
        prompt_to_use = prompt_entry_run if has_positions else prompt_no_entry
        
    logger.debug("Kết thúc hàm select_prompt_dynamically.")
    return prompt_to_use

def construct_final_prompt(app: "TradingToolApp", prompt: str, mt5_dict: Dict, safe_mt5_data: SafeMT5Data, context_block: str, mt5_json_full: str, paths: List[str]) -> str:
    """
    Xây dựng nội dung prompt cuối cùng để gửi đến model AI.
    Tích hợp dữ liệu có cấu trúc từ MT5, ngữ cảnh lịch sử và thông tin timeframe.
    """
    logger.debug("Bắt đầu hàm construct_final_prompt.")
    # Bắt đầu với thông tin timeframe từ tên file
    tf_section = app._build_timeframe_section([Path(p).name for p in paths]).strip()
    parts_text = []
    if tf_section:
        parts_text.append(f"### Nhãn khung thời gian (tự nhận từ tên tệp)\n{tf_section}\n\n")
        logger.debug("Đã thêm timeframe section vào prompt.")

    if mt5_dict:
        logger.debug("MT5 data có sẵn, xây dựng structured report và chèn vào prompt.")
        # Chuyển đổi dữ liệu MT5 thành báo cáo có cấu trúc
        structured_report = report_parser.parse_mt5_data_to_report(safe_mt5_data)
        
        # Chèn dữ liệu số vào placeholder trong prompt
        prompt = prompt.replace(
            "[Dữ liệu từ `CONCEPT_VALUE_TABLE` và `EXTRACT_JSON` sẽ được chèn vào đây]",
            f"DỮ LIỆU SỐ THAM KHẢO:\n{structured_report}"
        )
        
        # Chèn ngữ cảnh lịch sử (nếu có)
        if context_block:
            prompt = prompt.replace(
                "[Dữ liệu từ `CONTEXT_COMPOSED` sẽ được chèn vào đây]",
                f"DỮ LIỆU LỊCH SỬ (VÒNG TRƯỚC):\n{context_block}"
            )
            logger.debug("Đã chèn context_block vào prompt.")
        else:
            # Xóa placeholder nếu không có ngữ cảnh
            prompt = prompt.replace(
                "**DỮ LIỆU LỊCH SỬ (NẾU CÓ):**\n[Dữ liệu từ `CONTEXT_COMPOSED` sẽ được chèn vào đây]",
                ""
            )
            logger.debug("Không có context_block, đã xóa placeholder.")
        parts_text.append(prompt)
    else:
        logger.debug("Không có MT5 data, chỉ dùng prompt gốc và JSON (nếu có).")
        # Trường hợp không có dữ liệu MT5, chỉ dùng prompt gốc và JSON (nếu có)
        parts_text.append(prompt)
        if mt5_json_full:
            parts_text.append(f"\n\n[PHỤ LỤC_MT5_JSON]\n{mt5_json_full}")
            logger.debug("Đã thêm MT5 JSON full vào prompt.")

    # Dùng dict.fromkeys để loại bỏ các phần tử trùng lặp và giữ nguyên thứ tự
    final_prompt_content = "".join(list(dict.fromkeys(parts_text)))
    logger.debug(f"Kết thúc hàm construct_final_prompt. Độ dài prompt cuối cùng: {len(final_prompt_content)}.")
    return final_prompt_content
