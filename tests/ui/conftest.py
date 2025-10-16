from __future__ import annotations
import queue
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from APP.configs.app_config import (
    ApiConfig,
    AutoTradeConfig,
    ChartConfig,
    ContextConfig,
    FMPConfig,
    FolderConfig,
    ImageProcessingConfig,
    MT5Config,
    NewsConfig,
    NoRunConfig,
    NoTradeConfig,
    PersistenceConfig,
    TEConfig,
    TelegramConfig,
    UploadConfig,
)
from APP.ui.state import AutorunState, PromptState, UiConfigState
from APP.utils.threading_utils import ThreadingManager


@dataclass
class PyQtThreadingHarness:
    """Helper quản lý Qt threading adapter trong pytest."""

    qtbot: pytest.qt.qtbot.QtBot  # type: ignore[attr-defined]
    adapter: object
    bridge: object
    threading_manager: ThreadingManager

    def pump_events(self) -> None:
        """Xử lý toàn bộ callback đang đợi trong UiQueueBridge."""

        # Cho Qt cơ hội xử lý timer/signal trước khi drain hàng đợi.
        self.qtbot.wait(1)
        while True:
            processed = self.bridge.drain_once()
            if not processed:
                break
            self.qtbot.wait(1)

    def await_idle(self, *, group: str | None = None, timeout: float = 5.0) -> None:
        """Chờ ThreadingManager hoàn tất group và drain hàng đợi UI."""

        self.threading_manager.await_idle(group=group, timeout=timeout)
        self.pump_events()

    def close(self) -> None:
        """Dọn dẹp adapter và executor sau khi test kết thúc."""

        try:
            self.bridge.stop()
        except Exception:
            pass
        self.threading_manager.shutdown(force=True)
        self.pump_events()


@pytest.fixture()
def qapp():
    """Khởi tạo QApplication dùng chung cho các kiểm thử PyQt6."""

    pytest.importorskip("PyQt6")
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])

    try:
        yield app
    finally:
        app.quit()
        app.processEvents()


@pytest.fixture()
def config_state(tmp_path: Path) -> UiConfigState:
    """State cấu hình mặc định dùng cho các kiểm thử UI PyQt6."""

    workspace = tmp_path / "workspace"
    prompt_file = tmp_path / "prompts.json"
    return UiConfigState(
        folder=FolderConfig(folder=str(workspace), delete_after=True, max_files=5, only_generate_if_changed=False),
        upload=UploadConfig(upload_workers=2, cache_enabled=True, optimize_lossless=False),
        image_processing=ImageProcessingConfig(max_width=800, jpeg_quality=90),
        context=ContextConfig(
            ctx_limit=2048,
            create_ctx_json=True,
            prefer_ctx_json=False,
            ctx_json_n=5,
            remember_context=True,
            n_reports=2,
        ),
        api=ApiConfig(tries=3, delay=1.0),
        telegram=TelegramConfig(
            enabled=True,
            token="abc",
            chat_id="123",
            skip_verify=False,
            ca_path="/tmp/ca.pem",
            notify_on_early_exit=True,
        ),
        mt5=MT5Config(enabled=True, symbol="XAUUSD", n_M1=120, n_M5=90, n_M15=60, n_H1=30),
        mt5_terminal_path="/opt/mt5/terminal.exe",
        no_run=NoRunConfig(
            weekend_enabled=True,
            killzone_enabled=False,
            holiday_check_enabled=False,
            holiday_check_country="US",
            timezone="Asia/Ho_Chi_Minh",
            killzone_summer=None,
            killzone_winter=None,
        ),
        no_trade=NoTradeConfig(
            enabled=True,
            spread_max_pips=2.0,
            min_atr_m5_pips=1.5,
            min_dist_keylvl_pips=3.0,
            allow_session_asia=True,
            allow_session_london=True,
            allow_session_ny=False,
        ),
        auto_trade=AutoTradeConfig(
            enabled=False,
            strict_bias=False,
            size_mode="risk_percent",
            risk_per_trade=0.5,
            split_tp_enabled=False,
            split_tp_ratio=50,
            deviation=10,
            magic_number=999,
            comment="demo",
            pending_ttl_min=60,
            min_rr_tp2=1.5,
            cooldown_min=15,
            dynamic_pending=False,
            dry_run=True,
            move_to_be_after_tp1=False,
            trailing_atr_mult=0.5,
            filling_type="IOC",
        ),
        news=NewsConfig(
            block_enabled=True,
            block_before_min=15,
            block_after_min=30,
            cache_ttl_sec=120,
            priority_keywords=("USD",),
            provider_error_threshold=3,
            provider_error_backoff_sec=180,
            surprise_score_threshold=0.5,
            currency_country_overrides=None,
            symbol_country_overrides=None,
        ),
        persistence=PersistenceConfig(max_md_reports=10),
        fmp=FMPConfig(enabled=True, api_key="fmp"),
        te=TEConfig(enabled=False, api_key="", skip_ssl_verify=False),
        chart=ChartConfig(timeframe="M15", num_candles=150, chart_type="Nến", refresh_interval_secs=5),
        model="gemini-pro",
        autorun=AutorunState(enabled=True, interval_secs=300),
        prompt=PromptState(file_path=str(prompt_file), auto_load_from_disk=True),
    )


@pytest.fixture
def mt5_fake_gateway(qapp) -> "Mt5FakeGateway":
    from tests.ui.pyqt6_fakes import Mt5FakeGateway
    gateway = Mt5FakeGateway()
    yield gateway
    gateway.deleteLater()

@pytest.fixture
def gemini_fake_client(qapp) -> "GeminiFakeClient":
    from tests.ui.pyqt6_fakes import GeminiFakeClient
    client = GeminiFakeClient()
    yield client
    client.deleteLater()

@pytest.fixture
def news_fake_feed(qapp) -> "NewsFakeFeed":
    from tests.ui.pyqt6_fakes import NewsFakeFeed
    feed = NewsFakeFeed()
    yield feed
    feed.deleteLater()

@pytest.fixture()
def pyqt_threading_adapter(qtbot) -> PyQtThreadingHarness:
    """Cung cấp Qt threading adapter thật giúp test quan sát signal/queue."""

    pytest.importorskip("PyQt6")
    from PyQt6.QtCore import QCoreApplication
    from APP.ui.pyqt6.event_bridge import QtThreadingAdapter, UiQueueBridge

    if QCoreApplication.instance() is None:
        QCoreApplication([])

    bridge = UiQueueBridge(queue.Queue(), warn_interval_sec=0.0)
    tm = ThreadingManager(max_workers=2)
    adapter = QtThreadingAdapter(tm, bridge)
    harness = PyQtThreadingHarness(qtbot=qtbot, adapter=adapter, bridge=bridge, threading_manager=tm)
    harness.pump_events()
    try:
        yield harness
    finally:
        harness.close()
