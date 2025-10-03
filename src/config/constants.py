from pathlib import Path
import logging # Thêm import logging

logger = logging.getLogger(__name__) # Khởi tạo logger

# Supported image extensions and default model name
SUPPORTED_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tiff", ".tif"}
DEFAULT_MODEL = "gemini-pro-vision"

# App directory and common files
APP_DIR = Path.home() / ".gemini_folder_analyze"
APP_DIR.mkdir(parents=True, exist_ok=True)
WORKSPACE_JSON = APP_DIR / "workspace.json"
API_KEY_ENC = APP_DIR / "api_key.enc"
UPLOAD_CACHE_JSON = APP_DIR / "upload_cache.json"

logger.debug(f"APP_DIR: {APP_DIR}")
logger.debug(f"WORKSPACE_JSON: {WORKSPACE_JSON}")
logger.debug(f"API_KEY_ENC: {API_KEY_ENC}")
logger.debug(f"UPLOAD_CACHE_JSON: {UPLOAD_CACHE_JSON}")
