"""Cầu nối khởi tạo và cập nhật bộ controller cho giao diện PyQt6."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from APP.services.news_service import NewsService
from APP.ui.controllers import (
    AnalysisController,
    ChartController,
    IOController,
    MT5Controller,
    NewsController,
)
from APP.ui.state import UiConfigState
from APP.utils.threading_utils import ThreadingManager


@dataclass
class ControllerSet:
    """Gom nhóm các controller logic dùng chung cho PyQt6."""

    analysis: Optional[AnalysisController] = None
    io: Optional[IOController] = None
    chart: Optional[ChartController] = None
    news: Optional[NewsController] = None
    mt5: Optional[MT5Controller] = None
    news_service: Optional[NewsService] = None


class ControllerCoordinator:
    """Tạo và cập nhật controller dựa trên ThreadingManager chia sẻ."""

    def __init__(
        self,
        *,
        config_state: UiConfigState,
        threading_manager: ThreadingManager,
        ui_queue,
        news_service: Optional[NewsService] = None,
    ) -> None:
        self._threading_manager = threading_manager
        self._ui_queue = ui_queue
        self._news_service = news_service or NewsService()

        self.controllers = ControllerSet(
            analysis=AnalysisController(threading_manager, ui_queue),
            io=IOController(threading_manager),
            chart=ChartController(threading_manager=threading_manager, ui_queue=ui_queue),
            news=NewsController(
                threading_manager=threading_manager,
                news_service=self._news_service,
                ui_queue=ui_queue,
            ),
            mt5=MT5Controller(threading_manager),
            news_service=self._news_service,
        )

        self.apply_config(config_state)

    # ------------------------------------------------------------------
    def apply_config(self, state: UiConfigState):
        """Đồng bộ cấu hình controller/service với state UI hiện tại."""

        run_config = state.to_run_config()
        if self._news_service:
            self._news_service.update_config(run_config)
        return run_config

    # ------------------------------------------------------------------
    @property
    def news_service(self) -> Optional[NewsService]:
        return self._news_service

    @property
    def threading_manager(self) -> ThreadingManager:
        return self._threading_manager

