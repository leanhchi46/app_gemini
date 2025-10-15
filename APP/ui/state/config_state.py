"""Toolkit-agnostic state containers for UI configuration."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Mapping, Sequence

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
    RunConfig,
    TEConfig,
    TelegramConfig,
    UploadConfig,
)


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AutorunState:
    """Represents autorun toggles independent from any UI toolkit."""

    enabled: bool
    interval_secs: int


@dataclass(frozen=True)
class PromptState:
    """Stores prompt management preferences."""

    file_path: str
    auto_load_from_disk: bool


@dataclass(frozen=True)
class UiConfigState:
    """Immutable snapshot of all configuration needed by the application logic."""

    folder: FolderConfig
    upload: UploadConfig
    image_processing: ImageProcessingConfig
    context: ContextConfig
    api: ApiConfig
    telegram: TelegramConfig
    mt5: MT5Config
    mt5_terminal_path: str
    no_run: NoRunConfig
    no_trade: NoTradeConfig
    auto_trade: AutoTradeConfig
    news: NewsConfig
    persistence: PersistenceConfig
    fmp: FMPConfig
    te: TEConfig
    chart: ChartConfig
    model: str
    autorun: AutorunState
    prompt: PromptState

    def to_run_config(self) -> RunConfig:
        """Convert the state snapshot into a RunConfig used by services."""

        return RunConfig(
            folder=self.folder,
            upload=self.upload,
            image_processing=self.image_processing,
            context=self.context,
            telegram=self.telegram,
            mt5=self.mt5,
            no_run=self.no_run,
            no_trade=self.no_trade,
            auto_trade=self.auto_trade,
            news=self.news,
            fmp=self.fmp,
            te=self.te,
            persistence=self.persistence,
            chart=self.chart,
            api=self.api,
        )

    def to_workspace_payload(self) -> Dict[str, Any]:
        """Serialize the state back into the workspace configuration schema."""

        news_priority: Sequence[str] | None = None
        if self.news.priority_keywords:
            news_priority = list(self.news.priority_keywords)

        payload: Dict[str, Any] = {
            "folder": {
                "folder_path": self.folder.folder,
                "delete_after": self.folder.delete_after,
                "max_files": self.folder.max_files,
                "only_generate_if_changed": self.folder.only_generate_if_changed,
            },
            "upload": {
                "upload_workers": self.upload.upload_workers,
                "cache_enabled": self.upload.cache_enabled,
                "optimize_lossless": self.upload.optimize_lossless,
            },
            "image_processing": {
                "max_width": self.image_processing.max_width,
                "jpeg_quality": self.image_processing.jpeg_quality,
            },
            "api": {
                "tries": self.api.tries,
                "delay": self.api.delay,
            },
            "fmp": {
                "enabled": self.fmp.enabled,
                "api_key": self.fmp.api_key,
            },
            "te": {
                "enabled": self.te.enabled,
                "api_key": self.te.api_key,
                "skip_ssl_verify": self.te.skip_ssl_verify,
            },
            "telegram": {
                "enabled": self.telegram.enabled,
                "token": self.telegram.token,
                "chat_id": self.telegram.chat_id,
                "skip_verify": self.telegram.skip_verify,
                "ca_path": self.telegram.ca_path,
                "notify_on_early_exit": self.telegram.notify_on_early_exit,
            },
            "context": {
                "ctx_limit": self.context.ctx_limit,
                "create_ctx_json": self.context.create_ctx_json,
                "prefer_ctx_json": self.context.prefer_ctx_json,
                "ctx_json_n": self.context.ctx_json_n,
                "remember_context": self.context.remember_context,
                "n_reports": self.context.n_reports,
            },
            "mt5": {
                "enabled": self.mt5.enabled,
                "terminal_path": self.mt5_terminal_path,
                "symbol": self.mt5.symbol,
                "n_M1": self.mt5.n_M1,
                "n_M5": self.mt5.n_M5,
                "n_M15": self.mt5.n_M15,
                "n_H1": self.mt5.n_H1,
            },
            "no_run": {
                "weekend_enabled": self.no_run.weekend_enabled,
                "killzone_enabled": self.no_run.killzone_enabled,
                "holiday_check_enabled": self.no_run.holiday_check_enabled,
                "holiday_check_country": self.no_run.holiday_check_country,
                "timezone": self.no_run.timezone,
            },
            "no_trade": {
                "enabled": self.no_trade.enabled,
                "spread_max_pips": self.no_trade.spread_max_pips,
                "min_atr_m5_pips": self.no_trade.min_atr_m5_pips,
                "min_dist_keylvl_pips": self.no_trade.min_dist_keylvl_pips,
                "allow_session_asia": self.no_trade.allow_session_asia,
                "allow_session_london": self.no_trade.allow_session_london,
                "allow_session_ny": self.no_trade.allow_session_ny,
            },
            "auto_trade": {
                "enabled": self.auto_trade.enabled,
                "strict_bias": self.auto_trade.strict_bias,
                "size_mode": self.auto_trade.size_mode,
                "risk_per_trade": self.auto_trade.risk_per_trade,
                "split_tp_ratio": self.auto_trade.split_tp_ratio,
                "split_tp_enabled": self.auto_trade.split_tp_enabled,
                "deviation": self.auto_trade.deviation,
                "magic_number": self.auto_trade.magic_number,
                "comment": self.auto_trade.comment,
                "pending_ttl_min": self.auto_trade.pending_ttl_min,
                "min_rr_tp2": self.auto_trade.min_rr_tp2,
                "cooldown_min": self.auto_trade.cooldown_min,
                "dynamic_pending": self.auto_trade.dynamic_pending,
                "dry_run": self.auto_trade.dry_run,
                "move_to_be_after_tp1": self.auto_trade.move_to_be_after_tp1,
                "trailing_atr_mult": self.auto_trade.trailing_atr_mult,
                "filling_type": self.auto_trade.filling_type,
            },
            "news": {
                "block_enabled": self.news.block_enabled,
                "block_before_min": self.news.block_before_min,
                "block_after_min": self.news.block_after_min,
                "cache_ttl_sec": self.news.cache_ttl_sec,
                "priority_keywords": news_priority,
                "provider_error_threshold": self.news.provider_error_threshold,
                "provider_error_backoff_sec": self.news.provider_error_backoff_sec,
                "surprise_score_threshold": self.news.surprise_score_threshold,
                "currency_country_overrides": _copy_nested_mapping(
                    self.news.currency_country_overrides
                ),
                "symbol_country_overrides": _copy_nested_mapping(
                    self.news.symbol_country_overrides
                ),
            },
            "persistence": {
                "max_md_reports": self.persistence.max_md_reports,
            },
            "prompts": {
                "prompt_file_path": self.prompt.file_path,
                "auto_load_prompt_txt": self.prompt.auto_load_from_disk,
            },
            "model": self.model,
            "autorun": self.autorun.enabled,
            "autorun_secs": self.autorun.interval_secs,
            "chart": {
                "timeframe": self.chart.timeframe,
                "num_candles": self.chart.num_candles,
                "chart_type": self.chart.chart_type,
                "refresh_interval_secs": self.chart.refresh_interval_secs,
            },
        }

        if self.no_run.killzone_summer:
            payload["no_run"]["killzone_summer"] = _copy_nested_mapping(
                self.no_run.killzone_summer
            )
        if self.no_run.killzone_winter:
            payload["no_run"]["killzone_winter"] = _copy_nested_mapping(
                self.no_run.killzone_winter
            )

        return payload


def parse_priority_keywords(raw: str) -> list[str]:
    """Parse user input into a list of keywords."""

    text = (raw or "").strip()
    if not text:
        return []
    try:
        parsed = json_loads_if_list(text)
        if parsed is not None:
            return [kw for kw in (item.strip() for item in parsed) if kw]
    except ValueError:
        pass
    return [kw for kw in (piece.strip() for piece in text.split(",")) if kw]


def parse_mapping_string(raw: str) -> Dict[str, list[str]] | None:
    """Parse JSON mapping strings used for news overrides."""

    text = (raw or "").strip()
    if not text:
        return None
    try:
        parsed = json_loads_if_dict(text)
    except ValueError as exc:
        logger.warning("Không thể parse JSON mapping tin tức: %s", exc)
        return None
    if parsed is None:
        logger.warning("JSON mapping tin tức phải là đối tượng dict, nhận giá trị: %s", text)
        return None
    normalized: Dict[str, list[str]] = {}
    for key, values in parsed.items():
        key_norm = str(key).strip().upper()
        if not key_norm:
            continue
        if isinstance(values, Iterable) and not isinstance(values, (str, bytes)):
            cleaned = [str(item).strip() for item in values if str(item).strip()]
        else:
            cleaned = [str(values).strip()] if str(values).strip() else []
        if cleaned:
            normalized[key_norm] = cleaned
    return normalized or None


def json_loads_if_list(text: str) -> Sequence[str] | None:
    """Attempt to parse JSON arrays while tolerating comma-separated fallbacks."""

    data = json_loads(text)
    if isinstance(data, list):
        return [str(item) for item in data]
    return None


def json_loads_if_dict(text: str) -> Mapping[str, Iterable[str]] | None:
    """Attempt to parse JSON objects into mapping outputs."""

    data = json_loads(text)
    if isinstance(data, dict):
        return data  # type: ignore[return-value]
    raise ValueError("Expected JSON object for mapping string")


def json_loads(text: str) -> Any:
    """Wrapper around json.loads isolated here for easier testing/mocking."""

    import json

    return json.loads(text)


def _copy_nested_mapping(mapping: Mapping[str, Iterable[str]] | None) -> Dict[str, list[str]] | None:
    if mapping is None:
        return None
    return {str(k): [str(v) for v in values] for k, values in mapping.items()}
