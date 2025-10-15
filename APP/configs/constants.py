from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from APP.utils.env_loader import load_dotenv

# Tải các biến môi trường từ file .env ở thư mục gốc của dự án
# Điều này cho phép cấu hình linh hoạt mà không cần sửa code.
load_dotenv()

logger = logging.getLogger(__name__)
logger.debug("Đang tải module constants và các biến môi trường.")


@dataclass(frozen=True)
class Models:
    """Lớp chứa các hằng số liên quan đến model AI."""

    # Tải tên model mặc định từ biến môi trường,
    # nếu không có thì sử dụng "gemini-pro-vision".
    DEFAULT_VISION: str = os.getenv("DEFAULT_MODEL", "gemini-pro-vision")


@dataclass(frozen=True)
class Paths:
    """Lớp chứa các hằng số đường dẫn cốt lõi của ứng dụng."""

    # Thư mục gốc của ứng dụng trong thư mục home của người dùng
    APP_DIR: Path = Path.home() / ".gemini_folder_analyze"
    PROMPTS_DIR: Path = Path.cwd() / "APP" / "prompts"

    # Các file cấu hình và cache quan trọng
    WORKSPACE_JSON: Path = APP_DIR / "workspace.json"
    API_KEY_ENC: Path = APP_DIR / "api_key.enc"  # DEPRECATED: Sẽ bị thay thế bởi ALL_API_KEYS_ENC
    ALL_API_KEYS_ENC: Path = APP_DIR / "api_keys.json.enc"
    UPLOAD_CACHE_JSON: Path = APP_DIR / "upload_cache.json"


@dataclass(frozen=True)
class Files:
    """Lớp chứa các hằng số liên quan đến file."""

    SUPPORTED_EXTS: frozenset[str] = frozenset(
        {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tiff", ".tif"}
    )


@dataclass(frozen=True)
class Reports:
    """Lớp chứa các hằng số liên quan đến việc xử lý báo cáo."""

    # Mẫu regex để tìm điểm bắt đầu của báo cáo dành cho người đọc.
    # Tìm kiếm một tiêu đề Markdown (###) theo sau là một trong các từ khóa
    # chính, giúp hệ thống linh hoạt hơn với các thay đổi nhỏ trong định dạng phản hồi.
    REPORT_START_MARKER: str = r"###\s+(PHÂN TÍCH|TÓM TẮT|KẾ HOẠCH|NHIỆM VỤ|PHÂN TÍCH CHI TIẾT)"


# Tạo các instance bất biến của các lớp cấu hình
# Các module khác sẽ import các instance này để sử dụng.
MODELS = Models()
PATHS = Paths()
FILES = Files()
REPORTS = Reports()

# Ghi log các đường dẫn quan trọng để dễ dàng gỡ lỗi
logger.debug(f"APP_DIR: {PATHS.APP_DIR}")
logger.debug(f"WORKSPACE_JSON: {PATHS.WORKSPACE_JSON}")
logger.debug(f"DEFAULT_MODEL (từ .env): {MODELS.DEFAULT_VISION}")
