# -*- coding: utf-8 -*-
"""Facade điều phối refresh tin tức qua ThreadingManager."""

from __future__ import annotations

import logging
from concurrent.futures import CancelledError, Future
from typing import Callable, Optional

from APP.services.news_service import NewsService
from APP.utils.threading_utils import CancelToken, ThreadingManager

logger = logging.getLogger(__name__)


class NewsController:
    """Điều phối task group `news.polling` cho NewsService."""

    GROUP_NAME = "news.polling"

    def __init__(
        self,
        *,
        threading_manager: ThreadingManager,
        news_service: NewsService,
        ui_queue,
        backlog_limit: int = 50,
    ) -> None:
        self._tm = threading_manager
        self._news_service = news_service
        self._ui_queue = ui_queue
        self._backlog_limit = backlog_limit
        self._token: Optional[CancelToken] = None
        self._on_update: Optional[Callable[[dict], None]] = None
        self._last_payload: Optional[dict] = None

    def start_polling(self, on_update: Callable[[dict], None]) -> None:
        """Khởi động polling tự động."""

        self._on_update = on_update
        self._token = self._tm.new_cancel_token()
        self.trigger_autorun(force=True)

    def trigger_autorun(self, *, force: bool = False) -> None:
        """Gửi request autorun nếu backlog UI cho phép."""

        if not self._on_update:
            logger.debug("Bỏ qua autorun vì chưa đăng ký callback.")
            return
        if self._ui_queue.qsize() > self._backlog_limit and not force:
            logger.warning(
                "Bỏ qua refresh news do backlog UI=%s vượt ngưỡng=%s",
                self._ui_queue.qsize(),
                self._backlog_limit,
            )
            return
        self._submit_refresh(priority="autorun", force=force)

    def refresh_now(self) -> None:
        """Ưu tiên refresh theo thao tác người dùng."""

        logger.info("User yêu cầu refresh tin tức ngay lập tức.")
        self._tm.cancel_group(self.GROUP_NAME)
        if self._token:
            self._token.cancel()
        self._token = self._tm.new_cancel_token()
        self._submit_refresh(priority="user", force=True)

    def stop_polling(self) -> None:
        """Hủy mọi task đang chờ và reset token."""

        if self._token:
            self._token.cancel()
        self._tm.cancel_group(self.GROUP_NAME)
        self._token = None
        self._on_update = None

    def _submit_refresh(self, *, priority: str, force: bool) -> None:
        token = self._token or self._tm.new_cancel_token()
        timeout_sec = self._news_service.get_timeout_sec()
        metadata = {
            "component": "news",
            "priority": priority,
            "timeout_sec": timeout_sec,
        }

        record = self._tm.submit(
            func=self._refresh_worker,
            args=(priority, force),
            group=self.GROUP_NAME,
            name=f"news.refresh.{priority}",
            cancel_token=token,
            timeout=timeout_sec * 2,
            metadata=metadata,
        )
        record.future.add_done_callback(self._on_future_done)

    def _refresh_worker(self, priority: str, force: bool, cancel_token: CancelToken) -> dict:
        """Worker chạy trong ThreadPoolExecutor của ThreadingManager."""

        return self._news_service.refresh(
            threading_manager=self._tm,
            cancel_token=cancel_token,
            priority=priority,
            timeout_sec=self._news_service.get_timeout_sec(),
            force=force,
        )

    def _on_future_done(self, future: Future) -> None:
        try:
            payload = future.result()
        except CancelledError:
            logger.debug("Future news bị cancel, không cập nhật UI.")
            return
        except Exception as exc:  # pragma: no cover - chỉ log
            logger.exception("Refresh tin tức gặp lỗi: %s", exc)
            payload = {"events": [], "source": "error", "priority": "unknown", "ttl": 0, "latency_sec": 0.0}

        self._last_payload = payload
        if self._on_update:
            self._ui_queue.put(lambda p=payload: self._on_update(p))

    @property
    def last_payload(self) -> Optional[dict]:
        """Trả về kết quả refresh gần nhất (để phục vụ debug)."""

        return self._last_payload
