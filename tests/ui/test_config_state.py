import pytest

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
from APP.ui.state import (
    AutorunState,
    PromptState,
    UiConfigState,
    parse_mapping_string,
    parse_priority_keywords,
)


@pytest.fixture()
def sample_state() -> UiConfigState:
    return UiConfigState(
        folder=FolderConfig(folder="/tmp/data", delete_after=True, max_files=25, only_generate_if_changed=False),
        upload=UploadConfig(upload_workers=3, cache_enabled=True, optimize_lossless=False),
        image_processing=ImageProcessingConfig(max_width=1200, jpeg_quality=90),
        context=ContextConfig(
            ctx_limit=4096,
            create_ctx_json=True,
            prefer_ctx_json=False,
            ctx_json_n=7,
            remember_context=True,
            n_reports=2,
        ),
        api=ApiConfig(tries=4, delay=1.5),
        telegram=TelegramConfig(
            enabled=True,
            token="abc",
            chat_id="123",
            skip_verify=False,
            ca_path="/tmp/ca.pem",
            notify_on_early_exit=True,
        ),
        mt5=MT5Config(enabled=True, symbol="EURUSD", n_M1=120, n_M5=180, n_M15=96, n_H1=60),
        mt5_terminal_path="/opt/mt5/terminal.exe",
        no_run=NoRunConfig(
            weekend_enabled=True,
            killzone_enabled=False,
            holiday_check_enabled=True,
            holiday_check_country="US",
            timezone="Asia/Ho_Chi_Minh",
            killzone_summer=None,
            killzone_winter=None,
        ),
        no_trade=NoTradeConfig(
            enabled=True,
            spread_max_pips=2.1,
            min_atr_m5_pips=3.3,
            min_dist_keylvl_pips=4.4,
            allow_session_asia=True,
            allow_session_london=False,
            allow_session_ny=True,
        ),
        auto_trade=AutoTradeConfig(
            enabled=True,
            strict_bias=True,
            size_mode="risk_percent",
            risk_per_trade=0.5,
            split_tp_enabled=True,
            split_tp_ratio=60,
            deviation=15,
            magic_number=1234,
            comment="demo",
            pending_ttl_min=90,
            min_rr_tp2=2.2,
            cooldown_min=10,
            dynamic_pending=False,
            dry_run=False,
            move_to_be_after_tp1=True,
            trailing_atr_mult=0.7,
            filling_type="IOC",
        ),
        news=NewsConfig(
            block_enabled=True,
            block_before_min=10,
            block_after_min=20,
            cache_ttl_sec=120,
            priority_keywords=("USD", "EUR"),
            provider_error_threshold=3,
            provider_error_backoff_sec=180,
            surprise_score_threshold=0.8,
            currency_country_overrides={"USD": ["US"]},
            symbol_country_overrides={"EURUSD": ["EU", "US"]},
        ),
        persistence=PersistenceConfig(max_md_reports=12),
        fmp=FMPConfig(enabled=True, api_key="fmp-key"),
        te=TEConfig(enabled=False, api_key="te-key", skip_ssl_verify=True),
        chart=ChartConfig(timeframe="H1", num_candles=100, chart_type="Line", refresh_interval_secs=15),
        model="gemini-pro",
        autorun=AutorunState(enabled=True, interval_secs=300),
        prompt=PromptState(file_path="/tmp/prompt.txt", auto_load_from_disk=True),
    )


def test_to_run_config_keeps_dataclasses(sample_state: UiConfigState) -> None:
    run_config = sample_state.to_run_config()
    assert run_config.folder.folder == "/tmp/data"
    assert run_config.news.priority_keywords == ("USD", "EUR")
    assert run_config.auto_trade.split_tp_enabled is True


def test_to_workspace_payload_round_trip(sample_state: UiConfigState) -> None:
    payload = sample_state.to_workspace_payload()
    assert payload["folder"]["folder_path"] == "/tmp/data"
    assert payload["mt5"]["terminal_path"] == "/opt/mt5/terminal.exe"
    assert payload["autorun_secs"] == 300
    assert payload["news"]["priority_keywords"] == ["USD", "EUR"]
    assert payload["news"]["symbol_country_overrides"]["EURUSD"] == ["EU", "US"]


def test_parse_priority_keywords_handles_json_and_csv() -> None:
    assert parse_priority_keywords("[\"USD\", \"EUR\"]") == ["USD", "EUR"]
    assert parse_priority_keywords(" usd , eur , ") == ["usd", "eur"]


def test_parse_mapping_string_normalizes_keys() -> None:
    mapping = parse_mapping_string('{"usd": ["US", "VN"]}')
    assert mapping == {"USD": ["US", "VN"]}
    assert parse_mapping_string("not-json") is None
