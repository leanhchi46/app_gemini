# -*- coding: utf-8 -*-
"""
Module để xử lý việc lưu và quản lý các file báo cáo Markdown.

Lớp MdSaver đóng gói logic trích xuất nội dung báo cáo và lưu vào file,
đồng thời dọn dẹp các file cũ.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from APP.configs import constants, workspace_config
from APP.utils import general_utils

if TYPE_CHECKING:
    from APP.configs.app_config import RunConfig

logger = logging.getLogger(__name__)


class MdSaver:
    """
    Xử lý việc lưu và quản lý các tệp báo cáo Markdown.

    Cung cấp các phương thức tĩnh để trích xuất nội dung cần thiết từ
    phản hồi của AI và lưu nó vào một tệp .md, cũng như dọn dẹp các báo cáo cũ.
    """

    @staticmethod
    def _extract_human_readable_report(text: str) -> str:
        """
        Trích xuất phần báo cáo mà con người có thể đọc được từ phản hồi đầy đủ của AI.

        Tìm kiếm tiêu đề "NHIỆM VỤ 2" và trả về tất cả nội dung từ đó trở đi.

        Args:
            text: Phản hồi đầy đủ dưới dạng chuỗi từ mô hình AI.

        Returns:
            Chuỗi chứa phần báo cáo có thể đọc được. Trả về toàn bộ văn bản
            nếu không tìm thấy tiêu đề cụ thể.
        """
        logger.debug("Bắt đầu trích xuất báo cáo human-readable.")
        # Sử dụng hằng số từ constants để dễ dàng quản lý
        match = re.search(constants.REPORTS.REPORT_START_MARKER, text, re.IGNORECASE)

        if match:
            human_report = text[match.start():]
            logger.debug(f"Đã trích xuất báo cáo. Độ dài: {len(human_report)}")
            return human_report
        
        logger.warning("Không tìm thấy header 'NHIỆM VỤ 2', trả về toàn bộ nội dung.")
        return text

    @staticmethod
    def save_report(text: str, cfg: RunConfig) -> Path | None:
        """
        Lưu tệp báo cáo markdown và dọn dẹp các báo cáo cũ.

        Phương thức này sẽ trích xuất phần báo cáo mà con người có thể đọc được
        trước khi lưu.

        Args:
            text: Nội dung báo cáo đầy đủ từ AI.
            cfg: Đối tượng RunConfig chứa cấu hình cho lần chạy hiện tại.

        Returns:
            Đối tượng Path trỏ đến tệp đã lưu, hoặc None nếu có lỗi.
        """
        logger.debug("Bắt đầu lưu báo cáo Markdown.")
        try:
            reports_dir = workspace_config.get_reports_dir(cfg.mt5.symbol)
            if not reports_dir:
                logger.error("Không thể xác định thư mục Reports để lưu file .md.")
                return None

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = reports_dir / f"report_{timestamp}.md"
            logger.debug(f"Đường dẫn file báo cáo Markdown: {output_path}")

            human_report = MdSaver._extract_human_readable_report(text)

            output_path.write_text(human_report or "", encoding="utf-8")
            logger.info(f"Đã lưu báo cáo Markdown thành công tại: {output_path.name}")

            # Dọn dẹp các file .md cũ, sử dụng giá trị từ config
            general_utils.cleanup_old_files(
                directory=reports_dir,
                pattern="*.md",
                keep_n=cfg.persistence.max_md_reports,
            )
            
            logger.debug("Kết thúc việc lưu báo cáo Markdown.")
            return output_path

        except Exception:
            logger.exception("Đã xảy ra lỗi không mong muốn khi đang lưu báo cáo Markdown.")
            return None
