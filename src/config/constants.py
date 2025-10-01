from pathlib import Path

# Supported image extensions and default model name
SUPPORTED_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tiff", ".tif"}
DEFAULT_MODEL = "gemini-pro-vision"

# App directory and common files
APP_DIR = Path.home() / ".gemini_folder_analyze"
APP_DIR.mkdir(parents=True, exist_ok=True)
WORKSPACE_JSON = APP_DIR / "workspace.json"
API_KEY_ENC = APP_DIR / "api_key.enc"
UPLOAD_CACHE_JSON = APP_DIR / "upload_cache.json"
