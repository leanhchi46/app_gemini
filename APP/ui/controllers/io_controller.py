# -*- coding: utf-8 -*-
"""Facade điều phối các tác vụ I/O nền cho AppUI."""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Sequence

from APP.utils.threading_utils import TaskRecord, ThreadingManager

logger = logging.getLogger(__name__)


class IOController:
    """Bao bọc việc submit tác vụ nền liên quan tới I/O."""

    def __init__(
        self,
        threading_manager: ThreadingManager,
        *,
        enabled: bool = True,
    ) -> None:
        self._tm = threading_manager
        self._enabled = enabled

    def run(
        self,
        *,
        worker: Callable[..., Any],
        args: Sequence[Any] | None = None,
        kwargs: Dict[str, Any] | None = None,
        group: str,
        name: str,
        metadata: Dict[str, Any] | None = None,
        timeout: float | None = None,
        cancel_previous: bool = False,
    ) -> TaskRecord | None:
        """Submit worker I/O với metadata chuẩn hoá."""

        args = tuple(args or ())
        kwargs = dict(kwargs or {})
        metadata = dict(metadata or {})

        if not self._enabled:
            logger.debug("[IOController] Feature flag tắt → dùng submit_task legacy (%s)", name)
            self._tm.submit_task(worker, *args, **kwargs)
            return None

        if cancel_previous:
            self._tm.cancel_group(group)

        def _runner(*, cancel_token) -> Any:  # type: ignore[no-untyped-def]
            return worker(*args, **kwargs)

        record = self._tm.submit(
            func=_runner,
            group=group,
            name=name,
            metadata=metadata,
            timeout=timeout,
        )
        logger.info(
            "Đã gửi worker I/O %s vào group %s (metadata=%s)",
            name,
            group,
            metadata,
        )
        return record
