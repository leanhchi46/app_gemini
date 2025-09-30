# src/ui/prompt_manager.py
from __future__ import annotations

import json
import ast
from pathlib import Path
from typing import TYPE_CHECKING

from src.config.constants import APP_DIR
from src.utils import ui_utils

if TYPE_CHECKING:
    from src.ui.app_ui import TradingToolApp


def _extract_text_from_obj(obj):
    """
    Trích xuất tất cả các chuỗi văn bản từ một đối tượng Python (dict, list, str)
    một cách đệ quy và nối chúng lại thành một chuỗi duy nhất.
    """
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
    return text or json.dumps(obj, ensure_ascii=False, indent=2)

def _normalize_prompt_text(raw: str) -> str:
    """
    Chuẩn hóa văn bản prompt đầu vào.
    Cố gắng phân tích dưới dạng JSON hoặc đối tượng Python, sau đó trích xuất văn bản.
    Nếu không thành công, trả về văn bản gốc.
    """
    s = raw.strip()
    if not s:
        return ""

    # Cố gắng phân tích văn bản đầu vào theo các định dạng khác nhau.
    # Ưu tiên 1: Phân tích dưới dạng một chuỗi JSON hoàn chỉnh.
    try:
        obj = json.loads(s)
        return _extract_text_from_obj(obj)
    except Exception:
        pass

    # Ưu tiên 2: Phân tích dưới dạng một đối tượng Python (ví dụ: dict, list).
    try:
        obj = ast.literal_eval(s)
        return _extract_text_from_obj(obj)
    except Exception:
        pass

    # Nếu cả hai cách trên đều thất bại, trả về chuỗi văn bản gốc.
    return s

def _reformat_prompt_area(app: "TradingToolApp"):
    """
    Định dạng lại nội dung của khu vực nhập prompt hiện tại (tab "No Entry" hoặc "Entry/Run")
    bằng cách chuẩn hóa văn bản.
    """
    try:
        selected_tab_index = app.prompt_nb.index(app.prompt_nb.select())
        if selected_tab_index == 0:
            widget = app.prompt_no_entry_text
        else:
            widget = app.prompt_entry_run_text
        
        raw = widget.get("1.0", "end")
        pretty = _normalize_prompt_text(raw)
        widget.delete("1.0", "end")
        widget.insert("1.0", pretty)
    except Exception:
        pass

def _load_prompts_from_disk(app: "TradingToolApp", silent=False):
    """
    Tải nội dung các file prompt từ đĩa (`prompt_no_entry.txt` và `prompt_entry_run.txt`)
    và hiển thị chúng trên các tab prompt tương ứng.
    """
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
            elif not silent:
                widget.delete("1.0", "end")
                widget.insert("1.0", f"[LỖI] Không tìm thấy file: {path.name}")
        except Exception as e:
            if not silent:
                ui_utils.ui_message(app, "error", "Prompt", f"Lỗi nạp {path.name}: {e}")
    
    if loaded_count > 0 and not silent:
        ui_utils.ui_status(app, f"Đã nạp {loaded_count} prompt từ file.")

def _save_current_prompt_to_disk(app: "TradingToolApp"):
    """
    Lưu nội dung của prompt hiện tại (trên tab đang chọn) vào file tương ứng trên đĩa.
    """
    try:
        selected_tab_index = app.prompt_nb.index(app.prompt_nb.select())
        if selected_tab_index == 0:
            widget = app.prompt_no_entry_text
            path = APP_DIR / "prompt_no_entry.txt"
        else:
            widget = app.prompt_entry_run_text
            path = APP_DIR / "prompt_entry_run.txt"

        # Lấy nội dung từ widget, "-1c" để loại bỏ ký tự xuống dòng thừa ở cuối
        content = widget.get("1.0", "end-1c") 
        path.write_text(content, encoding="utf-8")
        ui_utils.ui_message(app, "info", "Prompt", f"Đã lưu thành công vào {path.name}")

    except Exception as e:
        ui_utils.ui_message(app, "error", "Prompt", f"Lỗi lưu file: {e}")
