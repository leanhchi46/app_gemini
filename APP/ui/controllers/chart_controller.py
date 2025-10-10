# -*- coding: utf-8 -*-
"""Facade quản lý luồng dữ liệu biểu đồ cho ChartTab."""

from __future__ import annotations

import logging
from concurrent.futures import CancelledError, Future
from dataclasses import dataclass
from typing import Callable, Optional

from APP.utils.threading_utils import CancelToken, TaskRecord, ThreadingManager

logger = logging.getLogger(__name__)


@dataclass
class ChartStreamConfig:
    """Cấu hình hiện hành cho luồng dữ liệu biểu đồ."""

    symbol: str
    timeframe: str
    candles: int
    chart_type: str


class ChartController:
    """Điều phối tác vụ nền của ChartTab thông qua ThreadingManager."""

    GROUP_NAME = "chart.refresh"

    def __init__(
        self,
        *,
        threading_manager: ThreadingManager,
        ui_queue,
        backlog_limit: int = 50,
    ) -> None:
        self._tm = threading_manager
        self._ui_queue = ui_queue
        self._backlog_limit = backlog_limit
        self._current_config: Optional[ChartStreamConfig] = None
        self._token: Optional[CancelToken] = None
        self._info_record: Optional[TaskRecord] = None
        self._chart_record: Optional[TaskRecord] = None
        self._on_info: Optional[Callable[[dict], None]] = None
        self._on_chart: Optional[Callable[[dict], None]] = None
        self._info_worker: Optional[Callable[..., dict]] = None
        self._chart_worker: Optional[Callable[..., dict]] = None

    # ------------------------------------------------------------------
    # Vòng đời stream
    # ------------------------------------------------------------------
    def start_stream(
        self,
        *,
        config: ChartStreamConfig,
        info_worker: Callable[..., dict],
        chart_worker: Callable[..., dict],
        on_info_done: Callable[[dict], None],
        on_chart_done: Callable[[dict], None],
    ) -> None:
        """Bắt đầu stream dữ liệu biểu đồ mới."""

        logger.info("Khởi động ChartController cho symbol=%s", config.symbol)
        self._current_config = config
        self._info_worker = info_worker
        self._chart_worker = chart_worker
        self._on_info = on_info_done
        self._on_chart = on_chart_done
        self._token = self._tm.new_cancel_token()
        self.trigger_refresh(force=True)

    def update_config(self, config: ChartStreamConfig) -> None:
        """Cập nhật cấu hình hiện tại cho stream."""

        logger.debug("Cập nhật config chart stream: %s", config)
        self._current_config = config

    def stop_stream(self) -> None:
        """Dừng stream và hủy tất cả tác vụ nền liên quan."""

        logger.info("Dừng ChartController stream hiện tại.")
        if self._token:
            self._token.cancel()
        self._tm.cancel_group(self.GROUP_NAME)
        self._token = None
        self._info_record = None
        self._chart_record = None

    # ------------------------------------------------------------------
    # Điều phối refresh
    # ------------------------------------------------------------------
    def trigger_refresh(self, *, force: bool = False) -> None:
        """Thực hiện refresh nếu không vượt quá backlog UI."""

        if not self._current_config or not self._token:
            logger.debug("Bỏ qua trigger_refresh vì chưa có config/token.")
            return
        if self._ui_queue.qsize() > self._backlog_limit and not force:
            logger.warning(
                "Bỏ qua refresh chart do backlog UI=%s vượt ngưỡng=%s",
                self._ui_queue.qsize(),
                self._backlog_limit,
            )
            return

        if force or not self._info_record or self._info_record.future.done():
            self._info_record = self._submit_task(
                worker=self._info_worker,
                name="chart.info",
            )
        if force or not self._chart_record or self._chart_record.future.done():
            self._chart_record = self._submit_task(
                worker=self._chart_worker,
                name="chart.draw",
            )

    def request_snapshot(self) -> None:
        """Buộc refresh ngay lập tức (ưu tiên thao tác người dùng)."""

        logger.debug("User yêu cầu snapshot chart ngay lập tức.")
        self.trigger_refresh(force=True)

    # ------------------------------------------------------------------
    # Nội bộ: submit và xử lý callback
    # ------------------------------------------------------------------
    def _submit_task(self, worker: Optional[Callable[..., dict]], name: str) -> Optional[TaskRecord]:
        if not worker or not self._current_config or not self._token:
            logger.debug("Không submit task %s vì thiếu worker/config/token.", name)
            return None

        metadata = {
            "symbol": self._current_config.symbol,
            "timeframe": self._current_config.timeframe,
            "candles": self._current_config.candles,
            "chart_type": self._current_config.chart_type,
            "component": "chart",
        }

        record = self._tm.submit(
            func=worker,
            args=(self._current_config,),
            group=self.GROUP_NAME,
            name=name,
            cancel_token=self._token,
            timeout=10.0,
            metadata=metadata,
        )

        record.future.add_done_callback(lambda fut, task=name: self._on_future_done(task, fut))
        return record

    def _on_future_done(self, task: str, future: Future) -> None:  # type: ignore[name-defined]
        """Chuyển kết quả future về UI thread."""

        try:
            payload = future.result()
        except CancelledError:
            logger.debug("Future %s bị cancel, không cập nhật UI.", task)
            return
        except Exception as exc:  # pragma: no cover - logging pathway
            logger.error("Future %s gặp lỗi: %s", task, exc)
            payload = {"success": False, "message": str(exc)}

        if task == "chart.info" and self._on_info:
            self._ui_queue.put(lambda p=payload: self._on_info(p))
        elif task == "chart.draw" and self._on_chart:
            self._ui_queue.put(lambda p=payload: self._on_chart(p))

