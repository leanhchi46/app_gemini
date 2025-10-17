# -*- coding: utf-8 -*-
"""Tiện ích quản lý luồng tập trung cho ứng dụng."""

from __future__ import annotations

import logging
import inspect
from concurrent.futures import (
    CancelledError,
    Future,
    ThreadPoolExecutor,
    TimeoutError,
    as_completed,
)
from dataclasses import dataclass, field
from threading import Event, Lock
from time import monotonic, sleep
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class CancelToken:
    """Đại diện cho tín hiệu hủy bỏ truyền giữa các tác vụ nền."""

    _event: Event = field(default_factory=Event)
    _parent: Optional["CancelToken"] = None

    def cancel(self) -> None:
        """Thiết lập trạng thái hủy."""

        self._event.set()

    def is_cancelled(self) -> bool:
        """Kiểm tra token đã bị hủy chưa (bao gồm cả token cha)."""

        if self._event.is_set():
            return True
        if self._parent:
            return self._parent.is_cancelled()
        return False

    def raise_if_cancelled(self) -> None:
        """Ném CancelledError nếu token đã bị hủy."""

        if self.is_cancelled():
            raise CancelledError()

    def derive(self) -> "CancelToken":
        """Tạo token con chia sẻ trạng thái hủy từ token hiện tại."""

        return CancelToken(_parent=self)


@dataclass
class TaskRecord:
    """Theo dõi trạng thái từng Future trong ThreadingManager."""

    future: Future
    token: CancelToken
    name: str
    group: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=monotonic)


class ThreadingManager:
    """Lớp bao bọc ThreadPoolExecutor với cơ chế quản lý nhóm."""

    def __init__(self, max_workers: int = 10) -> None:
        logger.info("Khởi tạo ThreadPoolExecutor với tối đa %s luồng.", max_workers)
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="AppWorker")
        self._lock = Lock()
        self._groups: Dict[str, List[TaskRecord]] = {}

    # ------------------------------------------------------------------
    # API mới với group/metadata/cancel token
    # ------------------------------------------------------------------
    def submit(
        self,
        *,
        func: Callable[..., Any],
        args: Optional[Tuple[Any, ...]] = None,
        kwargs: Optional[Dict[str, Any]] = None,
        group: str = "default",
        name: Optional[str] = None,
        cancel_token: Optional[CancelToken] = None,
        timeout: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> TaskRecord:
        """Gửi task với khả năng quản lý vòng đời chi tiết."""

        args = args or ()
        kwargs = kwargs or {}
        metadata = metadata or {}
        task_name = name or getattr(func, "__name__", "anonymous")
        token = cancel_token.derive() if cancel_token else CancelToken()

        logger.debug("Gửi task '%s' vào nhóm '%s' (metadata=%s)", task_name, group, metadata)

        def _runner() -> Any:
            start = monotonic()
            try:
                token.raise_if_cancelled()
                call_kwargs = dict(kwargs)
                inject_token = False
                if "cancel_token" not in call_kwargs:
                    try:
                        signature = inspect.signature(func)
                    except (TypeError, ValueError):
                        signature = None

                    if signature and "cancel_token" in signature.parameters:
                        try:
                            bound = signature.bind_partial(*args, **call_kwargs)
                            inject_token = "cancel_token" not in bound.arguments
                        except TypeError:
                            inject_token = True

                if inject_token:
                    call_kwargs["cancel_token"] = token

                result = func(*args, **call_kwargs)
                logger.debug(
                    "Task '%s' (group=%s) hoàn tất sau %.2fs",
                    task_name,
                    group,
                    monotonic() - start,
                )
                return result
            except CancelledError:
                logger.info(
                    "Task '%s' (group=%s) bị hủy sau %.2fs",
                    task_name,
                    group,
                    monotonic() - start,
                )
                raise
            except Exception:
                logger.exception("Task '%s' (group=%s) gặp lỗi.", task_name, group)
                raise

        future = self._executor.submit(_runner)
        record = TaskRecord(
            future=future,
            token=token,
            name=task_name,
            group=group,
            metadata=metadata,
        )

        with self._lock:
            self._groups.setdefault(group, []).append(record)

        future.add_done_callback(lambda _: self._cleanup_record(group, record))

        if timeout:
            self._executor.submit(self._monitor_timeout, record, timeout)

        return record

    def _monitor_timeout(self, record: TaskRecord, timeout: float) -> None:
        """Theo dõi timeout của task và chủ động cancel."""

        deadline = record.created_at + timeout
        while monotonic() < deadline:
            if record.future.done():
                return
            sleep(0.05)
        if record.future.done():
            return
        logger.warning(
            "Task '%s' (group=%s) vượt timeout %.2fs → cancel",
            record.name,
            record.group,
            timeout,
        )
        record.token.cancel()
        record.future.cancel()

    def _cleanup_record(self, group: str, record: TaskRecord) -> None:
        """Dọn danh sách nhóm khi future kết thúc."""

        with self._lock:
            records = self._groups.get(group)
            if not records:
                return
            if record in records:
                records.remove(record)
            if not records:
                self._groups.pop(group, None)

    # ------------------------------------------------------------------
    # API legacy để tương thích các module cũ
    # ------------------------------------------------------------------
    def submit_task(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Future:
        """Hàm tương thích cũ (sẽ bỏ sau khi refactor xong)."""

        logger.debug("[legacy] submit_task gọi trực tiếp executor: %s", getattr(func, "__name__", func))
        return self._executor.submit(func, *args, **kwargs)

    # ------------------------------------------------------------------
    # Điều khiển nhóm tác vụ
    # ------------------------------------------------------------------
    def cancel_group(self, group: str) -> None:
        """Hủy tất cả task thuộc một nhóm."""

        with self._lock:
            records = list(self._groups.get(group, []))
        for record in records:
            logger.info("Cancel group '%s' → task '%s'", group, record.name)
            record.token.cancel()
            record.future.cancel()

    def is_idle(self, group: Optional[str] = None) -> bool:
        """Kiểm tra nhanh xem nhóm task còn đang chạy hay không."""

        with self._lock:
            if group:
                records = list(self._groups.get(group, []))
            else:
                records = [rec for recs in self._groups.values() for rec in recs]
        return all(rec.future.done() for rec in records)

    def await_idle(self, group: Optional[str] = None, timeout: Optional[float] = None) -> bool:
        """Chờ tới khi nhóm (hoặc toàn bộ) task rỗng."""

        deadline = None if timeout is None else monotonic() + timeout
        while True:
            with self._lock:
                if group:
                    pending = [rec.future for rec in self._groups.get(group, []) if not rec.future.done()]
                else:
                    pending = [rec.future for records in self._groups.values() for rec in records if not rec.future.done()]
            if not pending:
                return True
            if deadline is not None and monotonic() > deadline:
                logger.warning("await_idle hết thời gian cho group=%s", group or "<all>")
                return False
            for fut in list(pending):
                try:
                    fut.result(timeout=0.05)
                except TimeoutError:
                    continue
                except CancelledError:
                    continue
                except Exception:
                    logger.exception("Task trong group %s kết thúc với lỗi.", group or "<all>")

    def new_cancel_token(self) -> CancelToken:
        """Tạo CancelToken mới (phục vụ test)."""

        return CancelToken()

    def shutdown(
        self,
        *,
        wait: bool = True,
        timeout: Optional[float] = None,
        force: bool = False,
    ) -> None:
        """Đóng ThreadPoolExecutor và dọn dẹp các nhóm task."""

        logger.info(
            "ThreadingManager.shutdown(wait=%s, timeout=%s, force=%s)",
            wait,
            timeout,
            force,
        )

        if force:
            with self._lock:
                records = [rec for recs in self._groups.values() for rec in recs]
            for record in records:
                record.token.cancel()
                record.future.cancel()
        elif wait:
            self.await_idle(timeout=timeout)

        self._executor.shutdown(wait=wait)


def run_in_parallel(tasks: List[Tuple[Callable[..., Any], Tuple[Any, ...], Dict[str, Any]]]) -> Dict[str, Any]:
    """Giữ nguyên helper cũ để tương thích với pipeline chưa refactor."""

    results: Dict[str, Any] = {}
    with ThreadPoolExecutor(max_workers=len(tasks) or 1) as executor:
        future_to_name = {
            executor.submit(func, *args, **kwargs): getattr(func, "__name__", f"task_{idx}")
            for idx, (func, args, kwargs) in enumerate(tasks)
        }

        for future in as_completed(future_to_name):
            name = future_to_name[future]
            try:
                results[name] = future.result()
                logger.debug("Task song song '%s' hoàn tất thành công.", name)
            except Exception:
                logger.exception("Task song song '%s' gặp lỗi.", name)
                results[name] = None
    return results
