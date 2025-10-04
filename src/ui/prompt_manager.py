from __future__ import annotations

import json
import ast
from typing import TYPE_CHECKING
import logging # Thêm import logging

from src.config.constants import APP_DIR
from src.utils import ui_utils

logger = logging.getLogger(__name__) # Khởi tạo logger

if TYPE_CHECKING:
    from src.ui.app_ui import TradingToolApp


def _extract_text_from_obj(obj):
    """
    Trích xuất tất cả các chuỗi văn bản từ một đối tượng Python (dict, list, str)
    một cách đệ quy và nối chúng lại thành một chuỗi duy nhất.
    """
    logger.debug(f"Bắt đầu hàm _extract_text_from_obj cho đối tượng kiểu: {type(obj)}")
    parts = []

    def walk(x):
        if isinstance(x, str):
            parts.append(x)
            return
        if isinstance(x, dict):

            for k in ("text", "content", "prompt", "body", "value"):
                v = x.get(k)
                if isinstance(v, str) and v.strip():
                    parts.append(v)
            for v in x.values():
                if v is not None and not isinstance(v, str):
                    walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    walk(obj)
    text = "\n\n".join(t.strip() for t in parts if t and t.strip())

    if text and text.count("") > 0 and text.count("\n") <= text.count(""):
        text = (text.replace("", "\n")
                    .replace("\\t", "\t")
                    .replace('\\"', '"')
                    .replace("\\'", "'"))
    logger.debug(f"Kết thúc hàm _extract_text_from_obj. Độ dài văn bản: {len(text)}")
    return text or json.dumps(obj, ensure_ascii=False, indent=2)

def _normalize_prompt_text(raw: str) -> str:
    """
    Chuẩn hóa văn bản prompt đầu vào.
    Cố gắng phân tích dưới dạng JSON hoặc đối tượng Python, sau đó trích xuất văn bản.
    Nếu không thành công, trả về văn bản gốc.
    """
    logger.debug(f"Bắt đầu hàm _normalize_prompt_text. Độ dài raw text: {len(raw)}")
    s = raw.strip()
    if not s:
        logger.debug("Raw text trống, trả về rỗng.")
        logger.debug("Kết thúc hàm _normalize_prompt_text (raw text trống).")
        return ""

    # Cố gắng phân tích văn bản đầu vào theo các định dạng khác nhau.
    # Ưu tiên 1: Phân tích dưới dạng một chuỗi JSON hoàn chỉnh.
    try:
        obj = json.loads(s)
        normalized_text = _extract_text_from_obj(obj)
        logger.debug("Đã normalize prompt từ JSON.")
        return normalized_text
    except Exception as e:
        logger.debug(f"Không thể parse raw text thành JSON: {e}")
        pass

    # Ưu tiên 2: Phân tích dưới dạng một đối tượng Python (ví dụ: dict, list).
    try:
        obj = ast.literal_eval(s)
        normalized_text = _extract_text_from_obj(obj)
        logger.debug("Đã normalize prompt từ Python literal.")
        return normalized_text
    except Exception as e:
        logger.debug(f"Không thể parse raw text thành Python literal: {e}")
        pass

    # Nếu cả hai cách trên đều thất bại, trả về chuỗi văn bản gốc.
    logger.debug("Không thể normalize prompt, trả về raw text.")
    logger.debug("Kết thúc hàm _normalize_prompt_text.")
    return s

def _reformat_prompt_area(app: "TradingToolApp"):
    """
    Định dạng lại nội dung của khu vực nhập prompt hiện tại (tab "No Entry" hoặc "Entry/Run")
    bằng cách chuẩn hóa văn bản.
    """
    logger.debug("Bắt đầu hàm _reformat_prompt_area.")
    try:
        selected_tab_index = app.prompt_nb.index(app.prompt_nb.select())
        if selected_tab_index == 0:
            widget = app.prompt_no_entry_text
            logger.debug("Định dạng lại tab 'No Entry'.")
        else:
            widget = app.prompt_entry_run_text
            logger.debug("Định dạng lại tab 'Entry/Run'.")
        
        raw = widget.get("1.0", "end")
        pretty = _normalize_prompt_text(raw)
        widget.delete("1.0", "end")
        widget.insert("1.0", pretty)
        ui_utils.ui_status(app, "Đã định dạng lại prompt.")
        logger.debug("Đã định dạng lại prompt area thành công.")
    except Exception as e:
        ui_utils.ui_message(app, "error", "Prompt", f"Lỗi định dạng prompt: {e}")
        logger.error(f"Lỗi khi định dạng lại prompt area: {e}")
    finally:
        logger.debug("Kết thúc _reformat_prompt_area.")

def _load_prompts_from_disk(app: "TradingToolApp", silent=False):
    """
    Tải nội dung các file prompt từ đĩa (`prompt_no_entry.txt` và `prompt_entry_run.txt`)
    và hiển thị chúng trên các tab prompt tương ứng.
    """
    logger.debug(f"Bắt đầu hàm _load_prompts_from_disk. Silent: {silent}")
    files_to_load = {
        "no_entry": (APP_DIR / "prompt_no_entry.txt", app.prompt_no_entry_text),
        "entry_run": (APP_DIR / "prompt_entry_run.txt", app.prompt_entry_run_text),
    }
    loaded_count = 0
    for key, (path, widget) in files_to_load.items():
        try:
            if path.exists():
                raw = path.read_text(encoding="utf-8", errors="ignore")
                text = _normalize_prompt_text(raw)
                widget.delete("1.0", "end")
                widget.insert("1.0", text)
                loaded_count += 1
                logger.debug(f"Đã nạp prompt từ file: {path.name}")
            elif not silent:
                widget.delete("1.0", "end")
                widget.insert("1.0", f"[LỖI] Không tìm thấy file: {path.name}")
                logger.warning(f"Không tìm thấy file prompt: {path.name}")
        except Exception as e:
            if not silent:
                ui_utils.ui_message(app, "error", "Prompt", f"Lỗi nạp {path.name}: {e}")
                logger.error(f"Lỗi khi nạp prompt từ file '{path.name}': {e}")
    
    if loaded_count > 0 and not silent:
        ui_utils.ui_status(app, f"Đã nạp {loaded_count} prompt từ file.")
        logger.info(f"Đã nạp {loaded_count} prompt từ file.")
    logger.debug("Kết thúc hàm _load_prompts_from_disk.")

def _save_current_prompt_to_disk(app: "TradingToolApp"):
    """
    Lưu nội dung của prompt hiện tại (trên tab đang chọn) vào file tương ứng trên đĩa.
    """
    logger.debug("Bắt đầu hàm _save_current_prompt_to_disk.")
    try:
        selected_tab_index = app.prompt_nb.index(app.prompt_nb.select())
        if selected_tab_index == 0:
            widget = app.prompt_no_entry_text
            path = APP_DIR / "prompt_no_entry.txt"
            logger.debug("Lưu prompt từ tab 'No Entry'.")
        else:
            widget = app.prompt_entry_run_text
            path = APP_DIR / "prompt_entry_run.txt"
            logger.debug("Lưu prompt từ tab 'Entry/Run'.")

        # Lấy nội dung từ widget, "-1c" để loại bỏ ký tự xuống dòng thừa ở cuối
        content = widget.get("1.0", "end-1c") 
        path.write_text(content, encoding="utf-8")
        ui_utils.ui_message(app, "info", "Prompt", f"Đã lưu thành công vào {path.name}")
        logger.info(f"Đã lưu prompt thành công vào: {path.name}")

    except Exception as e:
        ui_utils.ui_message(app, "error", "Prompt", f"Lỗi lưu file: {e}")
        logger.error(f"Lỗi khi lưu prompt vào file: {e}")
    finally:
        logger.debug("Kết thúc _save_current_prompt_to_disk.")
