from __future__ import annotations

import logging
logger = logging.getLogger(__name__)
logger.debug("Đang tải module constants.")

# Supported image extensions and default model name
SUPPORTED_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tiff", ".tif"}
DEFAULT_MODEL = "gemini-pro-vision"
