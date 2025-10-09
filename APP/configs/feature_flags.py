# -*- coding: utf-8 -*-
"""Định nghĩa các feature flag phục vụ rollout đa luồng."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Final


def _env_bool(name: str, default: bool) -> bool:
    """Đọc biến môi trường và chuyển về bool (hỗ trợ rollback nhanh)."""

    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class FeatureFlags:
    """Tập trung các cờ bật/tắt kiến trúc mới."""

    use_new_threading_stack: bool = True


FEATURE_FLAGS: Final[FeatureFlags] = FeatureFlags(
    use_new_threading_stack=_env_bool("USE_NEW_THREADING_STACK", True)
)
