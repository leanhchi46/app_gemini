from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from APP.utils import general_utils

if TYPE_CHECKING:
    from APP.configs.app_config import RunConfig
    from APP.ui.app_ui import AppUI

logger = logging.getLogger(__name__)


class MdSaver:
    def __init__(self, app: AppUI):
        self.app = app

    def _extract_human_readable_report(self, text: str) -> str:
        """Trích xuất phần báo cáo mà con người có thể đọc được (Nhiệm vụ 2 & 3)."""
        match = re.search(r"###\s+NHIỆM VỤ 2", text, re.IGNORECASE)
        if match:
            return text[match.start():]
        return text

    def save_report(self, text: str, cfg: RunConfig) -> Path | None:
        """
        Lưu phần báo cáo mà con người có thể đọc được vào một tệp markdown.
        """
        reports_dir = self.app.get_reports_dir(folder_override=cfg.folder)
        if not reports_dir:
            logger.error("Không thể xác định thư mục Reports để lưu .md.")
            return None

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = reports_dir / f"report_{ts}.md"
        
        human_report = self._extract_human_readable_report(text)
        
        try:
            out_path.write_text(human_report or "", encoding="utf-8")
            logger.info(f"Đã lưu báo cáo Markdown thành công tại: {out_path.name}")
        except IOError as e:
            logger.exception(f"Lỗi khi ghi báo cáo Markdown vào {out_path.name}")
            return None
        
        general_utils.cleanup_old_files(reports_dir, "report_*.md", 10)
        
        return out_path
