"""Gói chứa các thành phần giao diện PyQt6."""

from .application import PyQtApplication, ensure_qapplication
from .controller_bridge import ControllerCoordinator, ControllerSet
from .dialogs import DialogProvider, JsonPreviewDialog, ShutdownDialog
from .event_bridge import QtThreadingAdapter, UiQueueBridge
from .main_window import TradingMainWindow

__all__ = [
    "PyQtApplication",
    "ensure_qapplication",
    "DialogProvider",
    "JsonPreviewDialog",
    "ShutdownDialog",
    "QtThreadingAdapter",
    "UiQueueBridge",
    "TradingMainWindow",
    "ControllerCoordinator",
    "ControllerSet",
]
