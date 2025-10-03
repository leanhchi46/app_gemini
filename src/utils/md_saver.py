from __future__ import annotations
from datetime import datetime
from typing import TYPE_CHECKING
from src.utils import utils
import re
import logging # Thêm import logging

logger = logging.getLogger(__name__) # Khởi tạo logger

if TYPE_CHECKING:
    from scripts.tool import TradingToolApp
    from src.config.config import RunConfig
    from pathlib import Path

def extract_human_readable_report(text: str) -> str:
    """
    Extracts the human-readable parts (Task 2 and 3) from the AI's full response.
    """
    logger.debug("Bắt đầu extract_human_readable_report.")
    # Find the start of the human-readable summary (Task 2)
    # We use regex to be more flexible with potential whitespace or minor variations.
    match = re.search(r"###\s+NHIỆM VỤ 2", text, re.IGNORECASE)
    
    if match:
        # Return everything from the start of Task 2 to the end of the string
        human_report = text[match.start():]
        logger.debug(f"Đã trích xuất báo cáo human-readable. Độ dài: {len(human_report)}")
        return human_report
    else:
        # Fallback: if the specific header isn't found, return the original text
        # to avoid saving an empty file.
        logger.debug("Không tìm thấy header 'NHIỆM VỤ 2', trả về toàn bộ text.")
        return text

def save_md_report(app: "TradingToolApp", text: str, cfg: "RunConfig") -> "Path":
    """
    Saves the markdown report file and cleans up old reports.
    Now extracts only the human-readable part of the report.
    """
    logger.debug("Bắt đầu save_md_report.")
    d = app._get_reports_dir(cfg.folder)
    if not d:
        logger.error("Không thể xác định thư mục Reports để lưu .md.")
        return None
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = d / f"report_{ts}.md"
    logger.debug(f"Đường dẫn file báo cáo Markdown: {out}")
    
    # Extract only the human-readable part before saving
    human_report = extract_human_readable_report(text)
    
    try:
        out.write_text(human_report or "", encoding="utf-8")
        logger.info(f"Đã lưu báo cáo Markdown thành công tại: {out.name}")
    except Exception as e:
        logger.exception(f"Lỗi khi ghi báo cáo Markdown vào {out.name}: {e}") # Sử dụng logger.exception
        return None
    
    # Cleanup old .md files
    utils.cleanup_old_files(d, "report_*.md", 10)
    logger.debug("Đã dọn dẹp các file Markdown cũ.")
    
    logger.debug("Kết thúc save_md_report.")
    return out
