from __future__ import annotations
from pathlib import Path
from typing import TYPE_CHECKING, List, Dict, Any

from src.config.constants import APP_DIR
from src.utils import ui_utils
from src.utils import report_parser # Cần cho parse_mt5_data_to_report

if TYPE_CHECKING:
    from scripts.tool import TradingToolApp
    from src.config.config import RunConfig
    from src.utils.safe_data import SafeMT5Data

def select_prompt_dynamically(app: "TradingToolApp", cfg: "RunConfig", safe_mt5_data: SafeMT5Data, prompt_no_entry: str, prompt_entry_run: str) -> str:
    """
    Chọn prompt phù hợp dựa trên trạng thái giao dịch hiện tại (có lệnh đang mở hay không).
    """
    prompt_to_use = ""
    has_positions = cfg.mt5_enabled and safe_mt5_data and safe_mt5_data.raw and safe_mt5_data.raw.get("positions")
    
    try:
        if has_positions:
            prompt_path = APP_DIR / "prompt_entry_run_vision.txt"
            prompt_to_use = prompt_path.read_text(encoding="utf-8")
            app.ui_status("Worker: Lệnh đang mở, dùng prompt Vision Quản Lý Lệnh.")
        else:
            prompt_path = APP_DIR / "prompt_no_entry_vision.txt"
            prompt_to_use = prompt_path.read_text(encoding="utf-8")
            app.ui_status("Worker: Không có lệnh mở, dùng prompt Vision Tìm Lệnh Mới.")
    except Exception as e:
        app.ui_status(f"Lỗi đọc prompt từ file: {e}. Sử dụng prompt dự phòng.")
        # Cơ chế dự phòng: sử dụng prompt cũ nếu đọc file lỗi
        prompt_to_use = prompt_entry_run if has_positions else prompt_no_entry
        
    return prompt_to_use

def construct_final_prompt(app: "TradingToolApp", prompt: str, mt5_dict: Dict, safe_mt5_data: SafeMT5Data, context_block: str, mt5_json_full: str, paths: List[str]) -> str:
    """
    Xây dựng nội dung prompt cuối cùng để gửi đến model AI.
    Tích hợp dữ liệu có cấu trúc từ MT5, ngữ cảnh lịch sử và thông tin timeframe.
    """
    # Bắt đầu với thông tin timeframe từ tên file
    tf_section = app._build_timeframe_section([Path(p).name for p in paths]).strip()
    parts_text = []
    if tf_section:
        parts_text.append(f"### Nhãn khung thời gian (tự nhận từ tên tệp)\n{tf_section}\n\n")

    if mt5_dict:
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
        else:
            # Xóa placeholder nếu không có ngữ cảnh
            prompt = prompt.replace(
                "**DỮ LIỆU LỊCH SỬ (NẾU CÓ):**\n[Dữ liệu từ `CONTEXT_COMPOSED` sẽ được chèn vào đây]",
                ""
            )
        parts_text.append(prompt)
    else:
        # Trường hợp không có dữ liệu MT5, chỉ dùng prompt gốc và JSON (nếu có)
        parts_text.append(prompt)
        if mt5_json_full:
            parts_text.append(f"\n\n[PHỤ LỤC_MT5_JSON]\n{mt5_json_full}")

    # Dùng dict.fromkeys để loại bỏ các phần tử trùng lặp và giữ nguyên thứ tự
    return "".join(list(dict.fromkeys(parts_text)))
