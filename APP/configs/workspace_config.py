from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from APP.configs.constants import PATHS
from APP.utils.general_utils import deobfuscate_text, obfuscate_text

logger = logging.getLogger(__name__)


def setup_workspace():
    """
    Đảm bảo rằng thư mục ứng dụng (`.gemini_folder_analyze`) tồn tại.
    """
    try:
        PATHS.APP_DIR.mkdir(parents=True, exist_ok=True)
        logger.info(f"Thư mục workspace được đảm bảo tồn tại tại: {PATHS.APP_DIR}")
    except OSError as e:
        logger.critical(f"Không thể tạo thư mục workspace tại '{PATHS.APP_DIR}': {e}")
        raise


def get_workspace_dir() -> Path:
    """Trả về đường dẫn đến thư mục workspace của ứng dụng."""
    return PATHS.APP_DIR


def get_reports_dir(base_folder: str | Path) -> Path:
    """
    Lấy đường dẫn đến thư mục "Reports" bên trong một thư mục gốc, tạo nó nếu chưa tồn tại.
    """
    reports_dir = Path(base_folder) / "Reports"
    try:
        reports_dir.mkdir(exist_ok=True)
    except OSError as e:
        logger.error(f"Không thể tạo thư mục reports tại '{reports_dir}': {e}")
    return reports_dir


def get_upload_cache_path() -> Path:
    """Trả về đường dẫn đến tệp cache upload."""
    return PATHS.UPLOAD_CACHE_JSON


def load_config_from_file(workspace_path: str | Path | None = None) -> dict[str, Any]:
    """
    Tải cấu hình từ một file workspace.json được chỉ định hoặc mặc định.
    Hàm này độc lập với UI và chỉ trả về một dictionary.
    """
    config_path = Path(workspace_path) if workspace_path else PATHS.WORKSPACE_JSON
    logger.info(f"Đang tải cấu hình từ: {config_path}")

    if not config_path.exists():
        logger.warning(f"File cấu hình không tồn tại tại '{config_path}'. Trả về dictionary rỗng.")
        return {}

    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
        logger.debug("Đã đọc và parse file JSON thành công.")

        # Giải mã các thông tin nhạy cảm nếu có
        if "telegram_token_enc" in data:
            data["telegram_token"] = deobfuscate_text(data["telegram_token_enc"])

        logger.info("Tải cấu hình từ file thành công.")
        return data
    except json.JSONDecodeError as e:
        logger.error(f"Lỗi giải mã JSON từ file '{config_path}': {e}. File có thể bị hỏng.")
        # Trong tương lai, có thể thêm logic thông báo cho người dùng tại đây.
        return {}
    except Exception as e:
        logger.error(f"Lỗi không xác định khi đọc file cấu hình '{config_path}': {e}")
        return {}


def save_config_to_file(config_data: dict[str, Any]):
    """
    Lưu một dictionary cấu hình vào file `workspace.json`.
    Hàm này độc lập với UI.
    """
    logger.debug("Bắt đầu lưu cấu hình vào file.")

    # Tạo một bản sao để tránh thay đổi dictionary gốc
    data_to_save = config_data.copy()

    # Mã hóa các thông tin nhạy cảm
    if "telegram_token" in data_to_save:
        token = data_to_save["telegram_token"]
        data_to_save["telegram_token_enc"] = obfuscate_text(token) if token else ""
        del data_to_save["telegram_token"]  # Xóa key gốc để không lưu vào file

    try:
        PATHS.WORKSPACE_JSON.write_text(
            json.dumps(data_to_save, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        logger.info(f"Cấu hình đã được lưu thành công vào {PATHS.WORKSPACE_JSON}")
    except Exception as e:
        logger.error(f"Lỗi khi lưu cấu hình vào {PATHS.WORKSPACE_JSON}: {e}")
    logger.debug("Kết thúc lưu cấu hình vào file.")


def delete_workspace():
    """
    Xóa file `workspace.json` khỏi hệ thống.
    """
    logger.debug("Bắt đầu delete_workspace.")
    try:
        if PATHS.WORKSPACE_JSON.exists():
            PATHS.WORKSPACE_JSON.unlink()
            logger.info(f"Đã xoá workspace thành công từ {PATHS.WORKSPACE_JSON}")
        else:
            logger.info("File workspace.json không tồn tại, không cần xoá.")
    except Exception as e:
        logger.error(f"Lỗi khi xoá file workspace: {e}")
    logger.debug("Kết thúc delete_workspace.")
