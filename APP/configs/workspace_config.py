from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)
logger.debug("Đang tải module workspace_config.")

# Thư mục gốc của ứng dụng, nơi lưu trữ tất cả dữ liệu và cấu hình người dùng.
APP_DATA_DIR = Path.home() / ".trading_app_gemini"


def setup_workspace() -> None:
    """
    Khởi tạo cấu trúc thư mục cần thiết cho không gian làm việc của ứng dụng.
    Tạo thư mục chính và các thư mục con nếu chúng chưa tồn tại.
    """
    logger.debug("Bắt đầu thiết lập không gian làm việc.")
    try:
        APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
        reports_dir = get_reports_dir()
        reports_dir.mkdir(exist_ok=True)
        logger.info(f"Không gian làm việc đã được thiết lập tại: {APP_DATA_DIR}")
    except OSError as e:
        logger.error(f"Lỗi khi thiết lập không gian làm việc: {e}", exc_info=True)
        raise


def get_workspace_dir() -> Path:
    """
    Trả về đường dẫn đến thư mục không gian làm việc chính của ứng dụng.

    Returns:
        Path: Đối tượng Path trỏ đến thư mục không gian làm việc.
    """
    return APP_DATA_DIR


def get_reports_dir(workspace_path: Path | None = None) -> Path:
    """
    Trả về đường dẫn đến thư mục chứa các báo cáo.

    Args:
        workspace_path: Đường dẫn tùy chọn đến một không gian làm việc cụ thể.
                        Nếu là None, sử dụng không gian làm việc mặc định.

    Returns:
        Path: Đối tượng Path trỏ đến thư mục báo cáo.
    """
    base_path = workspace_path or get_workspace_dir()
    return base_path / "Reports"


def get_workspace_json_path() -> Path:
    """Trả về đường dẫn đến tệp workspace.json."""
    return get_workspace_dir() / "workspace.json"


def get_api_key_path() -> Path:
    """Trả về đường dẫn đến tệp api_key.enc."""
    return get_workspace_dir() / "api_key.enc"


def get_upload_cache_path() -> Path:
    """Trả về đường dẫn đến tệp upload_cache.json."""
    return get_workspace_dir() / "upload_cache.json"
