from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from APP.configs.constants import PATHS
from APP.utils.general_utils import deobfuscate_text, obfuscate_text

logger = logging.getLogger(__name__)

# Nguồn chân lý duy nhất cho các trường cần mã hóa.
# Mỗi mục là một tuple: (tên nhóm config, tên trường chứa secret).
SENSITIVE_KEYS: set[tuple[str, str]] = {
    ("telegram", "token"),
    ("fmp", "api_key"),
    ("te", "api_key"),
}


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


def get_reports_dir(base_folder: str | Path, symbol: str) -> Path:
    """
    Lấy đường dẫn đến thư mục "Reports" cho một symbol cụ thể, tạo nó nếu chưa tồn tại.
    
    Logic chuẩn: `base_folder / symbol / "Reports"`.
    """
    if not base_folder or not symbol:
        logger.warning("Base folder hoặc symbol rỗng, không thể xác định thư mục reports.")
        # Trả về một đường dẫn tạm thời trong thư mục làm việc để tránh lỗi
        fallback_dir = Path.cwd() / "temp_reports"
        fallback_dir.mkdir(exist_ok=True)
        return fallback_dir

    base_path = Path(base_folder)
    # Chuẩn hóa symbol: loại bỏ các ký tự không hợp lệ cho tên thư mục
    safe_symbol = "".join(c for c in symbol if c.isalnum() or c in ('-', '_')).rstrip()
    
    # Sử dụng .resolve() để tạo một đường dẫn tuyệt đối, chuẩn hóa, tránh các lỗi tiềm ẩn
    reports_dir = (base_path / safe_symbol / "Reports").resolve()
    try:
        reports_dir.mkdir(parents=True, exist_ok=True)
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

        # Tái cấu trúc: Tự động giải mã các trường nhạy cảm
        for group, key in SENSITIVE_KEYS:
            encrypted_key = f"{key}_enc"
            salt = f"{group}_{key}_salt"
            
            if group in data and isinstance(data[group], dict) and encrypted_key in data[group]:
                encrypted_value = data[group][encrypted_key]
                if encrypted_value:
                    try:
                        decrypted_value = deobfuscate_text(encrypted_value, salt)
                        data[group][key] = decrypted_value
                        logger.debug(f"Đã giải mã thành công trường '{key}' trong nhóm '{group}'.")
                    except Exception as e:
                        logger.warning(f"Lỗi khi giải mã trường '{key}' trong nhóm '{group}': {e}")

        logger.info("Tải cấu hình từ file thành công.")
        return data
    except json.JSONDecodeError as e:
        logger.error(f"Lỗi giải mã JSON từ file '{config_path}': {e}. File có thể bị hỏng.")
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

    # Tạo một bản sao sâu để tránh thay đổi dictionary gốc
    data_to_save = json.loads(json.dumps(config_data))

    # Tái cấu trúc: Tự động mã hóa các trường nhạy cảm
    for group, key in SENSITIVE_KEYS:
        encrypted_key = f"{key}_enc"
        salt = f"{group}_{key}_salt"

        if group in data_to_save and isinstance(data_to_save[group], dict) and key in data_to_save[group]:
            plain_text_value = data_to_save[group][key]
            
            if plain_text_value:
                try:
                    encrypted_value = obfuscate_text(plain_text_value, salt)
                    data_to_save[group][encrypted_key] = encrypted_value
                    logger.debug(f"Đã mã hóa thành công trường '{key}' trong nhóm '{group}'.")
                except Exception as e:
                    logger.error(f"Lỗi khi mã hóa trường '{key}' trong nhóm '{group}': {e}")
            
            # Luôn xóa key gốc để không lưu vào file JSON
            del data_to_save[group][key]

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
