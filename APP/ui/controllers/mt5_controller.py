# -*- coding: utf-8 -*-
"""Facade chuyên trách các tác vụ nền liên quan đến MT5."""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Sequence

from APP.utils.threading_utils import TaskRecord, ThreadingManager

logger = logging.getLogger(__name__)


class MT5Controller:
    """Điều phối connect/check/snapshot cho dịch vụ MT5."""

    GROUP_CONNECT = "mt5.connect"
    GROUP_CHECK = "mt5.check"
    GROUP_SNAPSHOT = "mt5.snapshot"

    def __init__(
        self,
        threading_manager: ThreadingManager,
        *,
        enabled: bool = True,
    ) -> None:
        self._tm = threading_manager
        self._enabled = enabled

    def _submit(
        self,
        *,
        worker: Callable[..., Any],
        args: Sequence[Any] | None = None,
        name: str,
        group: str,
        metadata: Dict[str, Any] | None = None,
        timeout: float | None = None,
        cancel_previous: bool = False,
    ) -> TaskRecord | None:
        args = tuple(args or ())
        metadata = dict(metadata or {})

        if not self._enabled:
            logger.debug("[MT5Controller] Feature flag tắt → submit_task legacy (%s)", name)
            self._tm.submit_task(worker, *args)
            return None

        if cancel_previous:
            self._tm.cancel_group(group)

        def _runner(*, cancel_token) -> Any:  # type: ignore[no-untyped-def]
            return worker(*args)

        record = self._tm.submit(
            func=_runner,
            group=group,
            name=name,
            metadata=metadata,
            timeout=timeout,
        )
        logger.info(
            "Đã gửi tác vụ MT5 %s (group=%s, metadata=%s)",
            name,
            group,
            metadata,
        )
        return record

    def connect(self, path: str, worker: Callable[[str], Any]) -> TaskRecord | None:
        """Yêu cầu kết nối MT5 trong nền."""

        return self._submit(
            worker=lambda p=path: worker(p),
            name="mt5.connect",
            group=self.GROUP_CONNECT,
            metadata={"component": "mt5", "operation": "connect"},
            timeout=30.0,
            cancel_previous=True,
        )

    def check_status(self, worker: Callable[[], Any]) -> TaskRecord | None:
        """Kiểm tra trạng thái kết nối định kỳ."""

        return self._submit(
            worker=worker,
            name="mt5.check",
            group=self.GROUP_CHECK,
            metadata={"component": "mt5", "operation": "check"},
            timeout=10.0,
        )

    def snapshot(self, worker: Callable[[], Any]) -> TaskRecord | None:
        """Chụp snapshot dữ liệu MT5."""

        return self._submit(
            worker=worker,
            name="mt5.snapshot",
            group=self.GROUP_SNAPSHOT,
            metadata={"component": "mt5", "operation": "snapshot"},
            timeout=60.0,
            cancel_previous=True,
        )
