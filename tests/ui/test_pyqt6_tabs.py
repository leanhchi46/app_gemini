from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

PyQt6 = pytest.importorskip("PyQt6")
from PyQt6.QtWidgets import QApplication  # type: ignore[attr-defined]

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
from APP.ui.pyqt6.tabs import (
    ChartTabWidget,
    HistoryEntry,
    HistoryTabWidget,
    NewsTabWidget,
    OptionsTabWidget,
    OverviewTab,
    PromptTabWidget,
    ReportEntry,
    ReportTabWidget,
)
from APP.ui.state import AutorunState, PromptState, UiConfigState


@pytest.fixture()
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture()
def sample_state(tmp_path: Path) -> UiConfigState:
    prompt_file = tmp_path / "prompts.json"
    return UiConfigState(
        folder=FolderConfig(folder="/tmp/data", delete_after=True, max_files=5, only_generate_if_changed=False),
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


def test_overview_tab_emits_signals(qapp, sample_state: UiConfigState) -> None:
    tab = OverviewTab(sample_state)
    triggered: list[str] = []

    tab.start_analysis_requested.connect(lambda: triggered.append("start"))
    tab.cancel_analysis_requested.connect(lambda: triggered.append("cancel"))
    tab.autorun_toggled.connect(lambda state: triggered.append(f"autorun:{state}"))

    tab.start_button.click()
    tab.cancel_button.click()
    tab._autorun_checkbox.setChecked(False)

    assert "start" in triggered
    assert "cancel" in triggered
    assert "autorun:False" in triggered

    tab.set_status("Đang chạy", running=True)
    assert not tab.start_button.isEnabled()
    assert tab.cancel_button.isEnabled()

    autorun_state = tab.autorun_state()
    assert autorun_state.enabled is sample_state.autorun.enabled
    assert autorun_state.interval_secs == sample_state.autorun.interval_secs


def test_chart_tab_current_config_and_signals(qapp, sample_state: UiConfigState) -> None:
    tab = ChartTabWidget(sample_state)
    configs: list[str] = []
    tab.settings_changed.connect(lambda cfg: configs.append(cfg.symbol))

    tab.symbol_input.setText("EURUSD")
    tab.timeframe_combo.setCurrentText("H1")
    tab.candle_spin.setValue(200)

    cfg = tab.current_config()
    assert cfg.symbol == "EURUSD"
    assert cfg.timeframe == "H1"
    assert cfg.candles == 200
    assert configs[-1] == "EURUSD"

    tab.set_snapshot_text("Snapshot demo")
    tab.set_metrics_text("Metrics demo")
    assert "Snapshot" in tab.chart_output.toPlainText()
    assert "Metrics" in tab.metrics_output.toPlainText()


def test_news_tab_update_events(qapp, sample_state: UiConfigState) -> None:
    tab = NewsTabWidget(sample_state)
    events = [
        {
            "when_local": datetime(2025, 1, 1, 8, 30),
            "country": "US",
            "title": "Nonfarm Payrolls",
            "impact": "high",
            "actual": 250.0,
            "forecast": 230.0,
            "previous": 220.0,
            "surprise_score": 0.5,
            "surprise_direction": "positive",
        }
    ]

    tab.update_events(events, source="FMP", latency_sec=0.7)
    assert tab.table.rowCount() == 1
    assert "FMP" in tab.status_label.text()
    assert "250.00" in tab.table.item(0, 4).text()

    tab.set_loading(True)
    assert not tab.refresh_button.isEnabled()


def test_prompt_tab_signals_and_state(qapp, sample_state: UiConfigState) -> None:
    tab = PromptTabWidget(sample_state)
    triggered: list[tuple] = []

    tab.load_requested.connect(lambda path: triggered.append(("load", path)))
    tab.save_requested.connect(lambda path, payload: triggered.append(("save", path, payload["auto_load"])))
    tab.reformat_requested.connect(lambda mode, text: triggered.append(("reformat", mode, text)))

    tab.path_edit.setText("/tmp/custom_prompts.json")
    tab.autoload_checkbox.setChecked(False)
    tab.no_entry_editor.setPlainText("No entry prompt")
    tab.entry_editor.setPlainText("Entry prompt")

    tab.load_button.click()
    tab.save_button.click()
    tab.reformat_button.click()

    assert ("load", "/tmp/custom_prompts.json") in triggered
    assert ("save", "/tmp/custom_prompts.json", False) in triggered
    assert any(event[0] == "reformat" and event[1] == "no_entry" for event in triggered)

    tab.set_loading(True)
    assert not tab.load_button.isEnabled()
    tab.set_loading(False)
    assert tab.save_button.isEnabled()

    prompt_state = tab.prompt_state()
    assert prompt_state.file_path == "/tmp/custom_prompts.json"
    assert prompt_state.auto_load_from_disk is False

    texts = tab.prompt_texts()
    assert texts["no_entry"].startswith("No entry")
    assert texts["entry_run"].startswith("Entry")


def test_history_tab_selection_and_preview_signal(qapp) -> None:
    tab = HistoryTabWidget()
    captured: list[str] = []
    tab.preview_requested.connect(lambda path: captured.append(path))

    entry_path = Path("/tmp/workspace/XAUUSD/Reports/report_1.md")
    tab.set_files("reports", [HistoryEntry(path=entry_path, display_name="XAUUSD/report_1.md")])
    tab.reports_list.setCurrentRow(0)

    assert str(entry_path) in captured

    tab.set_loading("reports", True)
    assert not tab.refresh_reports_button.isEnabled()
    tab.set_loading("reports", False)
    assert tab.refresh_reports_button.isEnabled()


def test_report_tab_signals_and_state(qapp, tmp_path: Path) -> None:
    reports_dir = tmp_path / "Reports"
    reports_dir.mkdir()
    report_path = reports_dir / "report_demo.md"
    report_path.write_text("Nội dung báo cáo", encoding="utf-8")

    tab = ReportTabWidget(tmp_path)
    opened: list[str] = []
    deleted: list[str] = []
    tab.open_requested.connect(lambda path: opened.append(path))
    tab.delete_requested.connect(lambda path: deleted.append(path))

    entry = ReportEntry(path=report_path, display_name="Reports/report_demo.md", status="Hoàn tất")
    tab.set_entries([entry])
    tab.table.selectRow(0)
    tab.open_button.click()
    tab.delete_button.click()

    assert opened and opened[0].endswith("report_demo.md")
    assert deleted and deleted[0].endswith("report_demo.md")
    tab.set_loading(True)
    assert not tab.open_button.isEnabled()


def test_options_tab_collect_payload_and_emit(qapp, sample_state: UiConfigState) -> None:
    tab = OptionsTabWidget(sample_state)
    payload = tab.collect_payload()
    assert payload["folder"]["max_files"] == sample_state.folder.max_files
    assert payload["news"]["block_enabled"] is sample_state.news.block_enabled
    assert payload["persistence"]["max_md_reports"] == sample_state.persistence.max_md_reports

    emitted: list[dict[str, object]] = []
    tab.config_changed.connect(lambda data: emitted.append(data))
    tab.max_files_spin.setValue(sample_state.folder.max_files + 1)
    assert emitted
    assert emitted[-1]["folder"]["max_files"] == sample_state.folder.max_files + 1
