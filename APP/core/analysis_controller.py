# -*- coding: utf-8 -*-
"""Facade quản lý vòng đời phiên phân tích sử dụng ThreadingManager."""

from __future__ import annotations

import logging
from collections import deque
from threading import Lock
from typing import Callable, Deque, Dict, Optional, Tuple

from APP.core.analysis_worker import AnalysisWorker
from APP.utils.threading_utils import CancelToken, ThreadingManager

logger = logging.getLogger(__name__)


class AnalysisController:
    """Điều phối TaskGroup `analysis.session` và `analysis.upload`."""

    def __init__(self, threading_manager: ThreadingManager, ui_queue) -> None:
        self._tm = threading_manager
        self._ui_queue = ui_queue
        self._sessions: Dict[str, dict] = {}
        self._lock = Lock()
        self._autorun_queue: Deque[Tuple[str, object, object, Optional[Callable[[str, str], None]]]] = deque()

    def start_session(
        self,
        session_id: str,
        app,
        cfg,
        *,
        priority: str = "user",
        on_start=None,
    ) -> None:
        """Bắt đầu một phiên phân tích mới (ưu tiên thao tác người dùng)."""

        with self._lock:
            if priority == "user":
                self._autorun_queue.clear()
            self._start_session_locked(session_id, app, cfg, priority, on_start)

    def enqueue_autorun(
        self,
        session_id: str,
        app,
        cfg,
        *,
        on_start=None,
    ) -> str:
        """Đưa yêu cầu autorun vào hàng đợi, trả về trạng thái."""

        with self._lock:
            if self._sessions:
                logger.info(
                    "Autorun %s được xếp hàng vì đang có phiên khác chạy.",
                    session_id,
                )
                self._autorun_queue.append((session_id, app, cfg, on_start))
                return "queued"

            self._start_session_locked(session_id, app, cfg, "autorun", on_start)
            return "started"

    def stop_session(self, session_id: str) -> None:
        """Hủy phiên đang chạy theo yêu cầu người dùng."""

        with self._lock:
            session = self._sessions.get(session_id)
        if not session:
            logger.warning("Không tìm thấy session %s để hủy.", session_id)
            return

        token: CancelToken = session["token"]
        token.cancel()
        self._tm.cancel_group("analysis.upload")
        self._tm.cancel_group("analysis.session")
        logger.info("Đã gửi tín hiệu hủy cho session %s", session_id)
        with self._lock:
            self._autorun_queue.clear()

    def get_status(self, session_id: str) -> Optional[str]:
        with self._lock:
            session = self._sessions.get(session_id)
        if not session:
            return None
        future = session["record"].future
        if future.done():
            try:
                result = future.result()
                return result.get("status") if isinstance(result, dict) else "done"
            except Exception as exc:  # pragma: no cover - logging path
                logger.error("Session %s kết thúc với lỗi: %s", session_id, exc)
                return "failed"
        return "running"

    def _on_session_done(self, session_id: str, future) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)
        try:
            payload = future.result()
        except Exception as exc:  # pragma: no cover - logging path
            logger.error("Session %s kết thúc với lỗi: %s", session_id, exc)
            payload = {"status": "failed", "error": str(exc)}

        if isinstance(payload, dict):
            self._ui_queue.put(lambda p=payload: logger.info("Kết thúc session %s: %s", session_id, p))
        self._launch_next_autorun()

    # ------------------------------------------------------------------
    # Nội bộ: xử lý hàng đợi autorun
    # ------------------------------------------------------------------
    def _start_session_locked(self, session_id, app, cfg, priority, on_start) -> None:  # type: ignore[no-untyped-def]
        token = self._tm.new_cancel_token()
        worker = AnalysisWorker(app=app, cfg=cfg, cancel_token=token, session_id=session_id)
        record = self._tm.submit(
            func=worker.run,
            group="analysis.session",
            name=f"analysis.session.{session_id}",
            cancel_token=token,
            metadata={"component": "analysis", "session_id": session_id, "priority": priority},
        )
        self._sessions[session_id] = {
            "token": token,
            "record": record,
            "priority": priority,
        }
        record.future.add_done_callback(lambda fut, sid=session_id: self._on_session_done(sid, fut))
        if on_start:
            self._ui_queue.put(lambda sid=session_id, pri=priority, cb=on_start: cb(sid, pri))
        logger.info("Đã submit phiên phân tích %s (priority=%s)", session_id, priority)

    def _launch_next_autorun(self) -> None:
        with self._lock:
            if self._sessions or not self._autorun_queue:
                return
            session_id, app, cfg, on_start = self._autorun_queue.popleft()
            self._start_session_locked(session_id, app, cfg, "autorun", on_start)
