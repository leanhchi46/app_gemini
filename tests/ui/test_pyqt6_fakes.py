"""Tests for the PyQt6-native fake gateways and feeds."""

from __future__ import annotations

from typing import Dict, List

import pytest

pytest.importorskip("PyQt6.QtTest")

from PyQt6.QtTest import QSignalSpy


def _wait_for_signal(spy: QSignalSpy, qtbot, timeout: int = 200) -> None:
    qtbot.waitUntil(lambda: len(spy) > 0, timeout=timeout)


def test_mt5_fake_gateway_emits_price(qtbot, mt5_fake_gateway) -> None:
    spy = QSignalSpy(mt5_fake_gateway.price_updated)

    mt5_fake_gateway.publish_price("EURUSD", 1.2345, 1.2347, time_millis=1712345678)

    _wait_for_signal(spy, qtbot)
    assert spy[0][0] == {
        "symbol": "EURUSD",
        "bid": 1.2345,
        "ask": 1.2347,
        "time": 1712345678,
    }


def test_gemini_fake_client_emits_price(qtbot, gemini_fake_client) -> None:
    from tests.ui.pyqt6_fakes import GeminiPrice

    spy = QSignalSpy(gemini_fake_client.price_updated)

    gemini_fake_client.push_price(GeminiPrice(symbol="BTCUSD", price=28500.0, change=100.0))

    _wait_for_signal(spy, qtbot)
    emitted_price = spy[0][0]
    assert emitted_price.symbol == "BTCUSD"
    assert emitted_price.price == 28500.0
    assert emitted_price.change == 100.0


def test_news_fake_feed_emits_refresh(qtbot, news_fake_feed) -> None:
    spy = QSignalSpy(news_fake_feed.news_refreshed)

    payload: List[Dict[str, str]] = [
        {"symbol": "EURUSD", "headline": "ECB maintains rates", "impact": "high"},
        {"symbol": "USDJPY", "headline": "BoJ hints policy shift", "impact": "medium"},
    ]

    news_fake_feed.push_news(payload)

    _wait_for_signal(spy, qtbot)
    assert spy[0][0] == payload
