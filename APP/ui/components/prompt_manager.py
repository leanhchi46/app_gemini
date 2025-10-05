# -*- coding: utf-8 -*-
"""
Quản lý các thành phần UI liên quan đến việc nhập và chỉnh sửa prompt.

Lớp PromptManager đóng gói logic để tải, lưu, định dạng và quản lý
nội dung của các ô nhập liệu prompt trong giao diện người dùng.
"""

from __future__ import annotations

import ast
import json
import logging
from typing import TYPE_CHECKING

# Sắp xếp import theo quy tắc
from APP.configs.constants import PATHS
from APP.ui.utils import ui_builder

if TYPE_CHECKING:
    from APP.ui.app_ui import AppUI

logger = logging.getLogger(__name__)


class PromptManager:
    """
    Quản lý các hoạt động liên quan đến các ô nhập prompt trong UI.

    Bao gồm tải từ file, lưu vào file, và định dạng lại nội dung.
    """
    # Cải tiến: Hằng số hóa các key thường dùng để trích xuất văn bản.
    # Điều này giúp dễ dàng quản lý và mở rộng khi có thêm các định dạng dữ liệu mới.
    _TEXT_KEYS = ("text", "content", "prompt", "body", "value")

    def __init__(self, app: "AppUI") -> None:
        """
        Khởi tạo PromptManager.

        Args:
            app (AppUI): Instance của ứng dụng UI chính.
        """
        self.app = app
        self.prompt_no_entry_path = PATHS.PROMPTS_DIR / "prompt_no_entry_vision.txt"
        self.prompt_entry_run_path = PATHS.PROMPTS_DIR / "prompt_entry_run_vision.txt"

    def _extract_text_from_obj(self, obj: object) -> str:
        """
        Trích xuất đệ quy tất cả văn bản từ một đối tượng Python.

        Args:
            obj: Đối tượng cần trích xuất (dict, list, str).

        Returns:
            Một chuỗi duy nhất chứa toàn bộ văn bản được tìm thấy.
        """
        logger.debug(f"Bắt đầu trích xuất văn bản từ đối tượng kiểu: {type(obj)}")
        parts = []

        def walk(x):
            if isinstance(x, str):
                parts.append(x)
                return
            if isinstance(x, dict):
                for k in self._TEXT_KEYS:
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

        # Cải tiến: Thêm comment giải thích logic đặc thù.
        # Logic này xử lý trường hợp người dùng dán một chuỗi JSON chứa các chuỗi con
        # được đặt trong dấu ngoặc kép. Nó cố gắng chuyển đổi các dấu ngoặc kép này
        # thành các dòng mới để cải thiện khả năng đọc của prompt.
        if text and text.count('"') > 0 and text.count('\n') <= text.count('"'):
            text = (text.replace('"', '\n')
                        .replace("\\t", "\t")
                        .replace('\\"', '"')
                        .replace("\\'", "'"))
        logger.debug(f"Kết thúc trích xuất văn bản. Độ dài: {len(text)}")
        return text or json.dumps(obj, ensure_ascii=False, indent=2)

    def _normalize_prompt_text(self, raw: str) -> str:
        """
        Chuẩn hóa văn bản prompt, cố gắng phân tích dưới dạng JSON hoặc Python literal.

        Args:
            raw: Chuỗi văn bản thô.

        Returns:
            Chuỗi văn bản đã được chuẩn hóa.
        """
        logger.debug(f"Bắt đầu chuẩn hóa prompt. Độ dài raw: {len(raw)}")
        s = raw.strip()
        if not s:
            logger.debug("Văn bản thô trống, trả về chuỗi rỗng.")
            return ""

        try:
            obj = json.loads(s)
            return self._extract_text_from_obj(obj)
        except Exception:
            logger.debug("Không thể phân tích raw text thành JSON.")

        try:
            obj = ast.literal_eval(s)
            return self._extract_text_from_obj(obj)
        except Exception:
            logger.debug("Không thể phân tích raw text thành Python literal.")

        logger.debug("Không thể chuẩn hóa, trả về văn bản thô.")
        return s

    def reformat_prompt_area(self) -> None:
        """
        Định dạng lại nội dung của khu vực nhập prompt đang được chọn.
        """
        logger.debug("Bắt đầu định dạng lại prompt area.")
        try:
            if not self.app.prompt_nb:
                return
            selected_tab_index = self.app.prompt_nb.index(self.app.prompt_nb.select())
            if selected_tab_index == 0:
                widget = self.app.prompt_no_entry_text
                logger.debug("Định dạng lại tab 'No Entry'.")
            else:
                widget = self.app.prompt_entry_run_text
                logger.debug("Định dạng lại tab 'Entry/Run'.")

            if widget:
                raw = widget.get("1.0", "end")
                pretty = self._normalize_prompt_text(raw)
                widget.delete("1.0", "end")
                widget.insert("1.0", pretty)
                self.app.ui_status("Đã định dạng lại prompt.")
            logger.debug("Định dạng lại prompt area thành công.")
        except Exception as e:
            ui_builder.show_message(title="Lỗi định dạng prompt", message=f"Đã xảy ra lỗi: {e}")
            logger.exception("Lỗi khi định dạng lại prompt area.")

    def load_prompts_from_disk(self, silent: bool = False) -> None:
        """
        Tải nội dung các file prompt từ đĩa và hiển thị trên UI.

        Args:
            silent: Nếu True, không hiển thị thông báo lỗi.
        """
        logger.debug(f"Bắt đầu tải prompts từ đĩa. Silent: {silent}")
        files_to_load = {
            "no_entry": (self.prompt_no_entry_path, self.app.prompt_no_entry_text),
            "entry_run": (self.prompt_entry_run_path, self.app.prompt_entry_run_text),
        }
        loaded_count = 0
        for key, (path, widget) in files_to_load.items():
            if not widget:
                continue
            try:
                if path.exists():
                    raw = path.read_text(encoding="utf-8", errors="ignore")
                    text = self._normalize_prompt_text(raw)
                    widget.delete("1.0", "end")
                    widget.insert("1.0", text)
                    loaded_count += 1
                    logger.debug(f"Đã tải prompt từ file: {path.name}")
                elif not silent:
                    widget.delete("1.0", "end")
                    widget.insert("1.0", f"[LỖI] Không tìm thấy file: {path.name}")
                    logger.warning(f"Không tìm thấy file prompt: {path.name}")
            except Exception as e:
                if not silent:
                    ui_builder.show_message(title=f"Lỗi tải {path.name}", message=f"Đã xảy ra lỗi: {e}")
                logger.exception(f"Lỗi khi tải prompt từ file '{path.name}'.")

        if loaded_count > 0 and not silent:
            self.app.ui_status(f"Đã tải {loaded_count} prompt từ file.")
        logger.debug("Kết thúc tải prompts từ đĩa.")

    def save_current_prompt_to_disk(self) -> None:
        """
        Lưu nội dung của prompt trên tab đang được chọn vào file tương ứng.
        """
        logger.debug("Bắt đầu lưu prompt hiện tại vào đĩa.")
        try:
            if not self.app.prompt_nb:
                return
            selected_tab_index = self.app.prompt_nb.index(self.app.prompt_nb.select())
            if selected_tab_index == 0:
                widget = self.app.prompt_no_entry_text
                path = self.prompt_no_entry_path
                logger.debug("Lưu prompt từ tab 'No Entry'.")
            else:
                widget = self.app.prompt_entry_run_text
                path = self.prompt_entry_run_path
                logger.debug("Lưu prompt từ tab 'Entry/Run'.")

            if widget:
                content = widget.get("1.0", "end-1c")  # -1c để bỏ qua newline cuối cùng
                path.write_text(content, encoding="utf-8")
                ui_builder.show_message(title="Lưu thành công", message=f"Đã lưu prompt vào {path.name}")
            logger.info(f"Đã lưu prompt thành công vào: {path.name}")
        except Exception as e:
            ui_builder.show_message(title="Lỗi lưu file", message=f"Đã xảy ra lỗi: {e}")
            logger.exception("Lỗi khi lưu prompt vào file.")

    def get_prompts(self) -> dict[str, str]:
        """
        Lấy nội dung văn bản hiện tại từ các ô nhập prompt.

        Returns:
            Một dictionary chứa prompt 'no_entry' và 'entry_run'.
        """
        logger.debug("Đang lấy nội dung prompts từ UI.")
        no_entry_prompt = ""
        if self.app.prompt_no_entry_text:
            no_entry_prompt = self.app.prompt_no_entry_text.get("1.0", "end-1c")
        
        entry_run_prompt = ""
        if self.app.prompt_entry_run_text:
            entry_run_prompt = self.app.prompt_entry_run_text.get("1.0", "end-1c")

        return {
            "no_entry": no_entry_prompt,
            "entry_run": entry_run_prompt,
        }
