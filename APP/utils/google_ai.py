"""Compatibility helpers for Google Generative AI SDK imports.

The production application depends on ``google-generativeai`` and
``google-api-core``.  These packages are not available in the execution
environment used for automated evaluation which caused the application to abort
at import time.  This module centralises optional imports and exposes a minimal
API that the rest of the codebase can rely on without crashing.  When the real
packages are installed the functions and classes simply proxy to them; when they
are missing we provide lightweight fallbacks together with a ``GEMINI_AVAILABLE``
flag so that callers can disable features gracefully.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


try:  # pragma: no cover - executed when dependencies are available
    from google.generativeai.client import configure as _configure  # type: ignore
    from google.generativeai.generative_models import (  # type: ignore
        GenerativeModel as _GenerativeModel,
    )
    from google.generativeai.models import list_models as _list_models  # type: ignore
    from google.api_core import exceptions  # type: ignore

    GEMINI_AVAILABLE = True
except ModuleNotFoundError:  # pragma: no cover - fallback path for sandbox
    _configure = None
    _list_models = None
    GEMINI_AVAILABLE = False

    class exceptions:  # type: ignore[override]
        """Subset của google.api_core.exceptions dùng trong dự án."""

        class PermissionDenied(Exception):
            pass

        class ResourceExhausted(Exception):
            pass

    class _GenerativeModel:  # type: ignore[too-many-ancestors]
        def __init__(self, *args, **kwargs):
            raise RuntimeError(
                "Google Generative AI SDK không khả dụng trong môi trường hiện tại."
            )

    def _stubbed(*_, **__):
        raise RuntimeError(
            "google-generativeai chưa được cài đặt. "
            "Vui lòng cài đặt gói để sử dụng các tính năng Gemini."
        )

    def _configure(*args, **kwargs):  # type: ignore[no-redef]
        return _stubbed(*args, **kwargs)

    def _list_models(*args, **kwargs):  # type: ignore[no-redef]
        _stubbed(*args, **kwargs)
        return []

    logger.warning(
        "Không tìm thấy google-generativeai. Các tính năng liên quan đến Gemini sẽ bị vô hiệu."
    )


GenerativeModel = _GenerativeModel


def configure(*args, **kwargs):
    if _configure is None:
        raise RuntimeError(
            "google-generativeai không khả dụng. Không thể cấu hình API key."
        )
    return _configure(*args, **kwargs)


def list_models(*args, **kwargs):
    if _list_models is None:
        raise RuntimeError(
            "google-generativeai không khả dụng. Không thể lấy danh sách model."
        )
    return _list_models(*args, **kwargs)

