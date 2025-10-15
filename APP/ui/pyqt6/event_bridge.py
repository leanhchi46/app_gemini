"""Cầu nối tín hiệu PyQt6 cho các callback cập nhật UI."""

from __future__ import annotations

import logging
import queue
from typing import Any, Callable, Optional

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from APP.utils.threading_utils import TaskRecord, ThreadingManager

logger = logging.getLogger(__name__)


class UiQueueBridge(QObject):
    """Chuyển queue callback kiểu Tkinter sang signal/slot của PyQt6."""

    callback_received = pyqtSignal(object)

    def __init__(
        self,
        ui_queue: queue.Queue[Any],
        *,
        interval_ms: int = 50,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._queue = ui_queue
        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self._drain_once)
        self.callback_received.connect(self._execute_callback)

    def start(self) -> None:
        """Bắt đầu polling queue để phát tín hiệu trên thread UI."""

        if not self._timer.isActive():
            logger.debug("Bắt đầu timer chuyển queue → signal (interval=%sms)", self._timer.interval())
            self._timer.start()

    def stop(self) -> None:
        """Dừng polling queue."""

        if self._timer.isActive():
            logger.debug("Dừng timer chuyển queue → signal")
            self._timer.stop()

    def post(self, callback: Callable[[], Any]) -> None:
        """Đưa callback mới vào queue và xử lý trên thread UI."""

        self._queue.put(callback)

    @property
    def queue(self) -> queue.Queue[Any]:
        """Truy cập queue gốc phục vụ cho các adapter tương thích Tkinter."""

        return self._queue

    def drain_once(self) -> int:
        """Xử lý các callback có sẵn (phục vụ test hoặc xử lý tức thời)."""

        return self._drain_once()

    def _drain_once(self) -> int:
        processed = 0
        while True:
            try:
                callback = self._queue.get_nowait()
            except queue.Empty:
                break
            processed += 1
            self.callback_received.emit(callback)
        return processed

    def _execute_callback(self, callback: Callable[[], Any]) -> None:
        try:
            callback()
        except Exception:  # pragma: no cover - ghi log lỗi để dễ debug
            logger.exception("Lỗi khi thực thi callback trên thread UI")


class QtThreadingAdapter(QObject):
    """Adapter đưa kết quả ThreadingManager lên PyQt thông qua UiQueueBridge."""

    def __init__(
        self,
        threading_manager: ThreadingManager,
        ui_bridge: UiQueueBridge,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._threading_manager = threading_manager
        self._ui_bridge = ui_bridge

    def submit(
        self,
        *,
        func: Callable[..., Any],
        args: Optional[tuple[Any, ...]] = None,
        kwargs: Optional[dict[str, Any]] = None,
        group: str = "default",
        name: Optional[str] = None,
        cancel_token=None,
        timeout: Optional[float] = None,
        metadata: Optional[dict[str, Any]] = None,
        on_result: Optional[Callable[[Any], None]] = None,
        on_error: Optional[Callable[[BaseException], None]] = None,
    ) -> TaskRecord:
        """Submit task và ánh xạ callback kết quả lên thread UI."""

        record = self._threading_manager.submit(
            func=func,
            args=args,
            kwargs=kwargs,
            group=group,
            name=name,
            cancel_token=cancel_token,
            timeout=timeout,
            metadata=metadata,
        )

        if on_result or on_error:
            def _notify(future: Any) -> None:
                try:
                    result = future.result()
                except Exception as exc:  # pragma: no cover - logic kiểm thử trong on_error
                    if on_error:
                        self._ui_bridge.post(lambda exc=exc: on_error(exc))
                else:
                    if on_result:
                        self._ui_bridge.post(lambda result=result: on_result(result))

            record.future.add_done_callback(_notify)

        return record

    def cancel_group(self, group: str) -> None:
        """Proxy sang ThreadingManager để tiện dùng trong UI."""

        self._threading_manager.cancel_group(group)

    @property
    def threading_manager(self) -> ThreadingManager:
        """Trả về ThreadingManager nền để phục vụ các adapter chuyên dụng."""

        return self._threading_manager

    def await_idle(self, group: str | None = None, timeout: Optional[float] = None) -> bool:
        """Chờ các task hoàn tất (tái sử dụng logic hiện có)."""

        return self._threading_manager.await_idle(group=group, timeout=timeout)

    def shutdown(self, *, wait: bool = True, timeout: Optional[float] = None, force: bool = False) -> None:
        """Đóng ThreadingManager khi UI PyQt6 thoát."""

        self._threading_manager.shutdown(wait=wait, timeout=timeout, force=force)
