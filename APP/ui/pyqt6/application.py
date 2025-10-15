"""Entry point bootstrap cho giao diện PyQt6."""

from __future__ import annotations

import queue
from typing import Any, Optional

from PyQt6.QtWidgets import QApplication

from APP.ui.pyqt6.controller_bridge import ControllerCoordinator
from APP.ui.pyqt6.event_bridge import QtThreadingAdapter, UiQueueBridge
from APP.ui.pyqt6.main_window import TradingMainWindow
from APP.ui.state import UiConfigState
from APP.utils.threading_utils import ThreadingManager


def ensure_qapplication(existing: QApplication | None = None) -> QApplication:
    """Bảo đảm tồn tại một QApplication duy nhất."""

    app = existing or QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


class PyQtApplication:
    """Điều phối QApplication, ThreadingManager và MainWindow."""

    def __init__(
        self,
        *,
        config_state: UiConfigState,
        threading_manager: Optional[ThreadingManager] = None,
        ui_queue: Optional[queue.Queue[Any]] = None,
        qapp: Optional[QApplication] = None,
    ) -> None:
        self._config_state = config_state
        self._threading_manager = threading_manager or ThreadingManager()
        self._ui_queue = ui_queue or queue.Queue()
        self._qapp = ensure_qapplication(qapp)

        self.ui_bridge = UiQueueBridge(self._ui_queue)
        self.threading = QtThreadingAdapter(self._threading_manager, self.ui_bridge)
        self._coordinator = ControllerCoordinator(
            config_state=config_state,
            threading_manager=self._threading_manager,
            ui_queue=self._ui_queue,
        )
        self.window = TradingMainWindow(
            config_state,
            self.threading,
            self.ui_bridge,
            controllers=self._coordinator.controllers,
            apply_config=self._coordinator.apply_config,
        )

    def run(self) -> int:
        """Khởi chạy vòng lặp sự kiện chính của PyQt6."""

        self.ui_bridge.start()
        self.window.show()
        exit_code = self._qapp.exec()
        self.ui_bridge.stop()
        self.threading.shutdown(wait=True)
        return exit_code

    # Các helper để phục vụ test/unit hoặc tích hợp với Tk trong giai đoạn chuyển tiếp
    @property
    def qapplication(self) -> QApplication:
        return self._qapp

    @property
    def threading_manager(self) -> ThreadingManager:
        return self._threading_manager

    @property
    def ui_queue(self) -> queue.Queue[Any]:
        return self._ui_queue
