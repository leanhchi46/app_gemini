"""PyQt6-native fake gateways and clients for integration tests.

These helpers replace the old Tkinter ``after()`` callbacks with
``QTimer.singleShot`` to ensure every asynchronous notification is emitted
through native Qt signals.  They are intended to be re-used by integration
tests that exercise the MT5 and Gemini adapters while the UI is running under
PyQt6.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence

import pytest

pytest.importorskip("PyQt6")

from PyQt6 import QtCore


def _single_shot_emit(delay_ms: int, callback: Callable[[], None]) -> None:
    """Schedule ``callback`` on the Qt event loop after ``delay_ms`` milliseconds."""

    QtCore.QTimer.singleShot(delay_ms, callback)


class _AsyncQtEmitter(QtCore.QObject):
    """Mixin that provides a convenient asynchronous ``emit`` helper."""

    def __init__(self, parent: Optional[QtCore.QObject] = None) -> None:
        super().__init__(parent)

    def _emit_async(
        self,
        signal: QtCore.pyqtSignal,  # type: ignore[type-arg]
        *args: Any,
        delay_ms: int = 0,
    ) -> None:
        _single_shot_emit(delay_ms, lambda: signal.emit(*args))


class Mt5FakeGateway(_AsyncQtEmitter):
    """Fake MT5 gateway that reports price ticks through PyQt6 signals."""

    price_updated = QtCore.pyqtSignal(dict)
    status_changed = QtCore.pyqtSignal(str)

    def publish_price(
        self,
        symbol: str,
        bid: float,
        ask: float,
        *,
        time_millis: Optional[int] = None,
        delay_ms: int = 0,
    ) -> None:
        payload: Dict[str, Any] = {
            "symbol": symbol,
            "bid": bid,
            "ask": ask,
        }
        if time_millis is not None:
            payload["time"] = time_millis

        self._emit_async(self.price_updated, payload, delay_ms=delay_ms)

    def notify_status(self, status: str, *, delay_ms: int = 0) -> None:
        self._emit_async(self.status_changed, status, delay_ms=delay_ms)


@dataclass(slots=True)
class GeminiPrice:
    symbol: str
    price: float
    change: float = 0.0
    percent_change: float = 0.0


class GeminiFakeClient(_AsyncQtEmitter):
    """Fake Gemini websocket client emitting updates via Qt signals."""

    price_updated = QtCore.pyqtSignal(object)
    disconnected = QtCore.pyqtSignal()

    def push_price(self, price: GeminiPrice, *, delay_ms: int = 0) -> None:
        self._emit_async(self.price_updated, price, delay_ms=delay_ms)

    def disconnect(self, *, delay_ms: int = 0) -> None:
        self._emit_async(self.disconnected, delay_ms=delay_ms)


class NewsFakeFeed(_AsyncQtEmitter):
    """Fake news feed emitting refresh batches via Qt signals."""

    news_refreshed = QtCore.pyqtSignal(list)

    def push_news(self, items: Sequence[Dict[str, Any]], *, delay_ms: int = 0) -> None:
        self._emit_async(self.news_refreshed, list(items), delay_ms=delay_ms)


@pytest.fixture
def mt5_fake_gateway() -> Mt5FakeGateway:
    """Provide a Qt-driven fake MT5 gateway for PyQt6 UI tests."""

    gateway = Mt5FakeGateway()
    yield gateway
    gateway.deleteLater()


@pytest.fixture
def gemini_fake_client() -> GeminiFakeClient:
    """Provide a Qt-driven fake Gemini client for PyQt6 UI tests."""

    client = GeminiFakeClient()
    yield client
    client.deleteLater()


@pytest.fixture
def news_fake_feed() -> NewsFakeFeed:
    """Provide a Qt-driven fake news feed for PyQt6 UI tests."""

    feed = NewsFakeFeed()
    yield feed
    feed.deleteLater()

