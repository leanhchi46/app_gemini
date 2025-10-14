from __future__ import annotations

from datetime import datetime, timedelta, timezone
from dataclasses import replace
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[2]))

import pytest

from APP.configs.app_config import (
    ApiConfig,
    AutoTradeConfig,
    ChartConfig,
    ContextConfig,
    FolderConfig,
    FMPConfig,
    ImageProcessingConfig,
    LoggingConfig,
    MT5Config,
    NewsConfig,
    NoRunConfig,
    NoTradeConfig,
    PersistenceConfig,
    RunConfig,
    TEConfig,
    TelegramConfig,
    UploadConfig,
)
from APP.core.trading import conditions
from APP.utils.safe_data import SafeData


class FakeNewsService:
    def __init__(self, *, blackout: bool = False, reason: str | None = None, events: list[dict] | None = None):
        self._blackout = blackout
        self._reason = reason
        self._events = events or []

    def is_in_news_blackout(self, symbol: str):
        return self._blackout, self._reason

    def get_upcoming_events(self, symbol: str, now: datetime | None = None):
        return list(self._events)


def make_run_config(*, no_trade: NoTradeConfig | None = None, news: NewsConfig | None = None) -> RunConfig:
    base_cfg = RunConfig(
        folder=FolderConfig(folder="/tmp", delete_after=False, max_files=0, only_generate_if_changed=False),
        upload=UploadConfig(upload_workers=1, cache_enabled=False, optimize_lossless=False),
        image_processing=ImageProcessingConfig(max_width=800, jpeg_quality=80),
        context=ContextConfig(
            ctx_limit=1024,
            create_ctx_json=False,
            prefer_ctx_json=False,
            ctx_json_n=1,
            remember_context=False,
            n_reports=1,
        ),
        telegram=TelegramConfig(
            enabled=False,
            token="",
            chat_id="",
            skip_verify=False,
            ca_path="",
            notify_on_early_exit=False,
        ),
        mt5=MT5Config(enabled=True, symbol="XAUUSD", n_M1=120, n_M5=120, n_M15=120, n_H1=120),
        no_run=NoRunConfig(weekend_enabled=False, killzone_enabled=False, holiday_check_enabled=False),
        no_trade=no_trade
        or NoTradeConfig(
            enabled=True,
            spread_max_pips=2.5,
            min_atr_m5_pips=2.0,
            min_dist_keylvl_pips=5.0,
            allow_session_asia=True,
            allow_session_london=True,
            allow_session_ny=True,
        ),
        auto_trade=AutoTradeConfig(
            enabled=False,
            strict_bias=False,
            size_mode="fixed",
            risk_per_trade=1.0,
            split_tp_enabled=False,
            split_tp_ratio=50,
            deviation=0,
            magic_number=1,
            comment="",
            pending_ttl_min=1,
            min_rr_tp2=1.0,
            cooldown_min=0,
            dynamic_pending=False,
            dry_run=True,
            move_to_be_after_tp1=False,
            trailing_atr_mult=0.0,
        ),
        news=news
        or NewsConfig(
            block_enabled=True,
            block_before_min=5,
            block_after_min=5,
            cache_ttl_sec=600,
        ),
        fmp=FMPConfig(enabled=False, api_key=""),
        te=TEConfig(enabled=False, api_key=""),
        persistence=PersistenceConfig(),
        chart=ChartConfig(),
        api=ApiConfig(),
        logging=LoggingConfig(),
    )
    return base_cfg


def make_safe_mt5_data(extra: dict | None = None) -> SafeData:
    base = {
        "symbol": "XAUUSD",
        "tick": {"bid": 2000.0, "ask": 2000.1},
        "info": {"spread_current": 1.0, "point": 0.01, "digits": 1},
        "volatility": {"ATR": {"M5": 0.05}},
    }
    if extra:
        base.update(extra)
    return SafeData(base)


def test_disabled_returns_empty_result():
    cfg = make_run_config(
        no_trade=NoTradeConfig(
            enabled=False,
            spread_max_pips=0.0,
            min_atr_m5_pips=0.0,
            min_dist_keylvl_pips=0.0,
            allow_session_asia=True,
            allow_session_london=True,
            allow_session_ny=True,
        )
    )

    result = conditions.check_no_trade_conditions(None, cfg, FakeNewsService())

    assert isinstance(result, conditions.NoTradeCheckResult)
    assert not result.has_blockers()
    assert result.to_messages() == []


def test_news_blackout_blocks_trade():
    cfg = make_run_config()
    safe_data = make_safe_mt5_data()

    result = conditions.check_no_trade_conditions(
        safe_data,
        cfg,
        FakeNewsService(blackout=True, reason="FOMC Statement"),
    )

    assert result.has_blockers()
    assert any(v.condition_id == "news_blackout" for v in result.blocking)


def test_spread_condition_blocks_when_exceeds_threshold(monkeypatch):
    base_cfg = make_run_config()
    cfg = replace(
        base_cfg,
        no_trade=replace(base_cfg.no_trade, spread_max_pips=1.0),
    )
    safe_data = make_safe_mt5_data()

    monkeypatch.setattr(conditions.mt5_service, "get_spread_pips", lambda info, tick: 2.0)

    result = conditions.check_no_trade_conditions(safe_data, cfg, FakeNewsService())

    assert result.has_blockers()
    assert result.blocking[0].condition_id == "spread"
    assert result.blocking[0].data["current_spread_pips"] == 2.0


def test_spread_condition_warns_when_threshold_too_tight(monkeypatch):
    base_cfg = make_run_config()
    cfg = replace(
        base_cfg,
        no_trade=replace(base_cfg.no_trade, spread_max_pips=1.0),
    )
    safe_data = make_safe_mt5_data(
        {
            "tick_stats_5m": {"median_spread": 1, "p90_spread": 2},
            "tick_stats_30m": {"median_spread": 1, "p90_spread": 2},
        }
    )

    monkeypatch.setattr(conditions.mt5_service, "get_spread_pips", lambda info, tick: 0.8)

    result = conditions.check_no_trade_conditions(safe_data, cfg, FakeNewsService())

    assert not result.has_blockers()
    assert any(v.condition_id == "spread" and not v.blocking for v in result.warnings)


def test_atr_condition_blocks_when_volatility_too_low(monkeypatch):
    base_cfg = make_run_config()
    cfg = replace(
        base_cfg,
        no_trade=replace(base_cfg.no_trade, min_atr_m5_pips=3.0),
    )
    safe_data = make_safe_mt5_data(
        {
            "volatility": {"ATR": {"M5": 0.015}},
        }
    )

    monkeypatch.setattr(conditions.mt5_service, "get_spread_pips", lambda info, tick: 0.5)

    result = conditions.check_no_trade_conditions(safe_data, cfg, FakeNewsService())

    assert result.has_blockers()
    assert result.blocking[0].condition_id == "atr"
    assert result.blocking[0].data["atr_m5_pips"] == pytest.approx(1.5)


def test_atr_condition_warns_when_threshold_above_adr():
    base_cfg = make_run_config()
    cfg = replace(
        base_cfg,
        no_trade=replace(base_cfg.no_trade, min_atr_m5_pips=50.0),
    )
    safe_data = make_safe_mt5_data(
        {
            "volatility": {"ATR": {"M5": 0.6}},
            "adr": {"d20": 0.1},
        }
    )

    result = conditions.check_no_trade_conditions(safe_data, cfg, FakeNewsService())

    assert any(v.condition_id == "atr" and not v.blocking for v in result.warnings)


def test_session_condition_blocks_when_session_disallowed():
    base_cfg = make_run_config()
    cfg = replace(
        base_cfg,
        no_trade=replace(
            base_cfg.no_trade,
            allow_session_london=False,
        ),
    )
    safe_data = make_safe_mt5_data({"killzone_active": "london"})

    result = conditions.check_no_trade_conditions(safe_data, cfg, FakeNewsService())

    assert result.has_blockers()
    assert result.blocking[0].condition_id == "session"


def test_key_level_condition_blocks_when_price_too_close():
    base_cfg = make_run_config()
    cfg = replace(
        base_cfg,
        no_trade=replace(base_cfg.no_trade, min_dist_keylvl_pips=10.0),
    )
    safe_data = make_safe_mt5_data(
        {
            "key_levels_nearby": [
                {"name": "Daily High", "distance_pips": 5.0},
            ]
        }
    )

    result = conditions.check_no_trade_conditions(safe_data, cfg, FakeNewsService())

    assert result.has_blockers()
    assert result.blocking[0].condition_id == "key_level"


def test_key_level_condition_warns_when_missing_data():
    base_cfg = make_run_config()
    cfg = replace(
        base_cfg,
        no_trade=replace(base_cfg.no_trade, min_dist_keylvl_pips=5.0),
    )
    safe_data = make_safe_mt5_data({"key_levels_nearby": []})

    result = conditions.check_no_trade_conditions(safe_data, cfg, FakeNewsService())

    assert any(v.condition_id == "key_level" and not v.blocking for v in result.warnings)


def test_upcoming_news_only_warns_not_block(monkeypatch):
    cfg = make_run_config()
    now = datetime.now(timezone.utc)
    event_time = now + timedelta(minutes=12)
    events = [
        {
            "title": "CPI",
            "country": "US",
            "when_utc": event_time,
            "when_local": event_time,
        }
    ]
    safe_data = make_safe_mt5_data()

    result = conditions.check_no_trade_conditions(
        safe_data,
        cfg,
        FakeNewsService(events=events),
        now_utc=now,
    )

    assert not result.has_blockers()
    assert result.warnings
    assert any(v.condition_id == "upcoming_news" for v in result.warnings)
    assert any(msg.startswith("⚠️ [upcoming_news]") for msg in result.to_messages())


def test_metrics_attached_to_result():
    cfg = make_run_config()
    safe_data = make_safe_mt5_data(
        {
            "tick_stats_5m": {"median_spread": 1, "p90_spread": 2},
            "key_levels_nearby": [
                {"name": "PDH", "distance_pips": 10.0, "price": 2010.0, "relation": "ABOVE"}
            ],
            "adr": {"d20": 0.2},
        }
    )

    result = conditions.check_no_trade_conditions(safe_data, cfg, FakeNewsService())

    assert result.metrics is not None
    assert result.metrics.spread.current_pips is not None


def test_no_trade_result_to_dict_includes_serialized_fields(monkeypatch):
    base_cfg = make_run_config()
    cfg = replace(
        base_cfg,
        no_trade=replace(
            base_cfg.no_trade,
            spread_max_pips=1.0,
            min_dist_keylvl_pips=5.0,
        ),
    )

    safe_data = make_safe_mt5_data(
        {
            "key_levels_nearby": [],
            "tick_stats_5m": {"median_spread": 1, "p90_spread": 2},
            "tick_stats_30m": {"median_spread": 1, "p90_spread": 2},
        }
    )

    monkeypatch.setattr(conditions.mt5_service, "get_spread_pips", lambda info, tick: 2.0)

    result = conditions.check_no_trade_conditions(safe_data, cfg, FakeNewsService())
    payload = result.to_dict(include_messages=True)

    assert payload["status"] == "blocked"
    assert payload["blocking"][0]["condition_id"] == "spread"
    assert payload["warnings"][0]["condition_id"] == "key_level"
    assert payload["messages"]
    assert "metrics" in payload
