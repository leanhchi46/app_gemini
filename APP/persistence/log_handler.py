# -*- coding: utf-8 -*-
"""
Module để xử lý ghi log, bao gồm log debug của ứng dụng và log quyết định giao dịch.
"""

from __future__ import annotations

import io
import json
import logging
import os
import sys
import threading
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Optional, TextIO

# Thêm import từ cấu trúc mới
from APP.configs import workspace_config

if TYPE_CHECKING:
    # Tránh import vòng lặp nhưng vẫn cho phép type hinting
    from APP.configs.app_config import LoggingConfig, RunConfig

logger = logging.getLogger(__name__)

# Khóa riêng để ghi log giao dịch an toàn trong môi trường đa luồng
_trade_log_lock = threading.Lock()


def _configure_stdio_encoding(encoding: str = "utf-8") -> None:
    """Ensure stdout/stderr use UTF-8 to avoid UnicodeEncodeError."""
    for stream_name in ("stdout", "stderr"):
        stream: Optional[TextIO] = getattr(sys, stream_name, None)
        if stream is None:
            continue

        current_encoding = getattr(stream, "encoding", None)
        if current_encoding and current_encoding.lower() == encoding.lower():
            continue

        try:
            stream.reconfigure(encoding=encoding, errors="backslashreplace")
        except AttributeError:
            buffer = getattr(stream, "buffer", None)
            if buffer is None:
                continue
            wrapped_stream = io.TextIOWrapper(
                buffer,
                encoding=encoding,
                errors="backslashreplace",
                line_buffering=True,
            )
            setattr(sys, stream_name, wrapped_stream)



def setup_logging(config: Optional[LoggingConfig] = None) -> None:
    """
    Cấu hình hệ thống logging với file xoay vòng (rotating file).

    Args:
        config: Đối tượng cấu hình logging. Nếu None, sử dụng giá trị mặc định.
    """
    from APP.configs.app_config import LoggingConfig

    # Sử dụng config được truyền vào hoặc tạo một config mặc định
    cfg = config or LoggingConfig()

    logger.debug("Bắt đầu thiết lập logging cho ứng dụng.")
    try:
        log_dir = Path(cfg.log_dir)
        _configure_stdio_encoding()
        log_dir.mkdir(exist_ok=True)
        log_file = log_dir / cfg.log_file_name

        # Chuyển đổi MB sang bytes
        max_bytes = cfg.log_rotation_size_mb * 1024 * 1024

        # Tạo handler xoay vòng
        rotating_handler = RotatingFileHandler(
            log_file,
            mode="w",
            maxBytes=max_bytes,
            backupCount=cfg.log_rotation_backup_count,
            encoding="utf-8",
        )

        # Gỡ bỏ các handler hiện có để tránh ghi log trùng lặp
        root_logger = logging.getLogger()
        if root_logger.hasHandlers():
            for handler in root_logger.handlers[:]:
                root_logger.removeHandler(handler)

        console_handler = logging.StreamHandler(sys.stdout)


        logging.basicConfig(
            level=logging.DEBUG,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            handlers=[rotating_handler, console_handler],
        )

        # Ẩn các log không cần thiết từ các thư viện bên thứ ba
        logging.getLogger("matplotlib.font_manager").setLevel(logging.INFO)
        logging.getLogger("PIL.PngImagePlugin").setLevel(logging.INFO)
        logger.info(
            f"Đã cấu hình logging xoay vòng. File log: {log_file}, "
            f"Size: {cfg.log_rotation_size_mb}MB, Backups: {cfg.log_rotation_backup_count}"
        )
    except Exception:
        logger.exception("Đã xảy ra lỗi trong quá trình thiết lập logging.")
        # Chuyển về cấu hình cơ bản nếu thiết lập thất bại
        logging.basicConfig(level=logging.INFO)
        logger.error("Đã chuyển về cấu hình logging cơ bản.")
    logger.debug("Hoàn tất thiết lập logging cho ứng dụng.")


def log_trade(
    run_config: RunConfig,
    trade_data: Dict[str, Any],
    folder_override: Optional[str] = None,
) -> None:
    """
    Ghi lại các quyết định giao dịch vào file JSONL trong thư mục reports tương ứng.

    Hàm này an toàn khi chạy trong môi trường đa luồng (thread-safe).

    Args:
        run_config: Đối tượng cấu hình đang chạy của ứng dụng.
        trade_data: Một dictionary chứa dữ liệu về quyết định giao dịch.
        folder_override: Một thư mục con tùy chọn bên trong thư mục reports.
    """
    logger.debug(
        f"Đang chuẩn bị ghi log giao dịch. Giai đoạn: {trade_data.get('stage')}, "
        f"Thư mục con: {folder_override}"
    )
    try:
        # Sử dụng workspace_config để lấy đúng thư mục reports
        reports_dir = workspace_config.get_reports_dir(
            base_folder=run_config.folder.folder, symbol=run_config.mt5.symbol
        )
        if folder_override:
            target_dir = reports_dir / folder_override
        else:
            target_dir = reports_dir

        # Đảm bảo thư mục đích tồn tại
        target_dir.mkdir(parents=True, exist_ok=True)

        # Xác định tên file log từ timestamp trong dữ liệu
        timestamp_str = trade_data.get("t", datetime.now().isoformat())
        log_date = datetime.fromisoformat(timestamp_str).strftime("%Y%m%d")
        log_file_path = target_dir / f"trade_log_{log_date}.jsonl"

        # Chuyển đổi dữ liệu thành chuỗi JSON
        log_line = (
            json.dumps(trade_data, ensure_ascii=False, separators=(",", ":")) + "\n"
        )
        encoded_line = log_line.encode("utf-8")

        with _trade_log_lock:
            # Kiểm tra xem có cần thêm một dòng mới trước khi ghi không
            needs_newline = False
            if log_file_path.exists() and log_file_path.stat().st_size > 0:
                try:
                    with open(log_file_path, "rb") as f:
                        f.seek(-1, os.SEEK_END)
                        if f.read(1) != b"\n":
                            needs_newline = True
                except OSError:
                    # Xử lý trường hợp seek thất bại (ví dụ: file trống)
                    pass

            with open(log_file_path, "ab") as f:
                if needs_newline:
                    f.write(b"\n")
                f.write(encoded_line)
                f.flush()
                # Đảm bảo dữ liệu được ghi xuống đĩa
                try:
                    os.fsync(f.fileno())
                except OSError:
                    # fsync có thể không khả dụng trên mọi hệ điều hành
                    pass
        logger.debug(f"Đã ghi log giao dịch thành công vào {log_file_path.name}.")

    except Exception:
        logger.exception("Không thể ghi log quyết định giao dịch.")
    logger.debug("Kết thúc hàm log_trade.")
