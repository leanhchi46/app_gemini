from __future__ import annotations

import json
import ast
import logging
from typing import TYPE_CHECKING, Any

from APP.configs.workspace_config import get_workspace_dir
from APP.ui.utils import ui_builder

if TYPE_CHECKING:
    from APP.ui.app_ui import AppUI

logger = logging.getLogger(__name__)


class PromptManager:
    def __init__(self, app: "AppUI"):
        self.app = app
        self.workspace_dir = get_workspace_dir()

    def _extract_text_from_obj(self, obj: Any) -> str:
        """Trích xuất văn bản từ các đối tượng Python (dict, list, str)."""
        parts = []
        # ... (logic from original _extract_text_from_obj)
        return "\n\n".join(parts)

    def _normalize_prompt_text(self, raw: str) -> str:
        """Chuẩn hóa văn bản prompt, cố gắng phân tích JSON hoặc Python literal."""
        s = raw.strip()
        if not s:
            return ""
        try:
            obj = json.loads(s)
            return self._extract_text_from_obj(obj)
        except json.JSONDecodeError:
            pass
        try:
            obj = ast.literal_eval(s)
            return self._extract_text_from_obj(obj)
        except (ValueError, SyntaxError):
            pass
        return s

    def reformat_prompt_area(self):
        """Định dạng lại nội dung của tab prompt hiện tại."""
        try:
            selected_tab = self.app.prompt_nb.select()
            widget = self.app.prompt_nb.nametowidget(selected_tab)
            
            raw = widget.get("1.0", "end")
            pretty = self._normalize_prompt_text(raw)
            widget.delete("1.0", "end")
            widget.insert("1.0", pretty)
            self.app.status_var.set("Đã định dạng lại prompt.")
        except Exception as e:
            ui_builder.message(self.app, "error", "Prompt", f"Lỗi định dạng: {e}")

    def load_prompts_from_disk(self, silent: bool = False):
        """Tải nội dung prompt từ các tệp văn bản trong workspace."""
        files_to_load = {
            "no_entry": (self.workspace_dir / "prompt_no_entry.txt", self.app.prompt_no_entry_text),
            "entry_run": (self.workspace_dir / "prompt_entry_run.txt", self.app.prompt_entry_run_text),
        }
        # ... (logic from original _load_prompts_from_disk)

    def save_current_prompt_to_disk(self):
        """Lưu nội dung của tab prompt hiện tại vào tệp."""
        try:
            selected_tab = self.app.prompt_nb.select()
            widget = self.app.prompt_nb.nametowidget(selected_tab)
            
            path = None
            if widget == self.app.prompt_no_entry_text:
                path = self.workspace_dir / "prompt_no_entry.txt"
            else:
                path = self.workspace_dir / "prompt_entry_run.txt"

            content = widget.get("1.0", "end-1c")
            path.write_text(content, encoding="utf-8")
            ui_builder.message(self.app, "info", "Prompt", f"Đã lưu vào {path.name}")
        except Exception as e:
            ui_builder.message(self.app, "error", "Prompt", f"Lỗi khi lưu: {e}")
