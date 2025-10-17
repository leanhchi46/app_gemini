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
    FolderConfig,
    ImageProcessingConfig,
    MT5Config,
    NewsConfig,
    NoRunConfig,
    NoTradeConfig,
    PersistenceConfig,
    RunConfig,
    TelegramConfig,
    UploadConfig,
)


from APP.configs.constants import MODELS
from APP.services.mt5_service import DEFAULT_KILLZONE_SUMMER, DEFAULT_KILLZONE_WINTER
from APP.services.news_service import DEFAULT_HIGH_IMPACT_KEYWORDS

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


    @classmethod
    def from_workspace_config(cls, config: Mapping[str, Any] | None) -> "UiConfigState":
        """Build a UiConfigState snapshot from a persisted workspace dictionary."""

        data = dict(config or {})

        def _clean_str(value: Any, default: str = "") -> str:
            if isinstance(value, str):
                return value.strip()
            if value is None:
                return default
            return str(value).strip()

        def _as_bool(value: Any, default: bool) -> bool:
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                lowered = value.strip().lower()
                if lowered in {"true", "1", "yes", "y", "on"}:
                    return True
                if lowered in {"false", "0", "no", "n", "off"}:
                    return False
            return default

        def _as_int(value: Any, default: int) -> int:
            try:
                return int(value)
            except (TypeError, ValueError):
                return default

        def _as_float(value: Any, default: float) -> float:
            try:
                return float(value)
            except (TypeError, ValueError):
                return default

        def _normalize_keywords(raw: Any) -> tuple[str, ...] | None:
            if isinstance(raw, (list, tuple, set)):
                cleaned = tuple(str(item).strip() for item in raw if str(item).strip())
                return cleaned or None
            if isinstance(raw, str):
                pieces = [piece.strip() for piece in raw.split(",")]
                cleaned = tuple(piece for piece in pieces if piece)
                return cleaned or None
            return None

        def _normalize_overrides(raw: Any) -> dict[str, list[str]] | None:
            if not isinstance(raw, Mapping):
                return None
            normalized: dict[str, list[str]] = {}
            for key, values in raw.items():
                if not isinstance(key, str):
                    continue
                items: list[str] = []
                if isinstance(values, (list, tuple, set)):
                    items = [str(item).strip() for item in values if str(item).strip()]
                elif isinstance(values, str):
                    val = values.strip()
                    if val:
                        items = [val]
                if items:
                    normalized[key.strip().upper()] = items
            return normalized or None

        def _clone_killzone(template: Mapping[str, Mapping[str, str]]) -> dict[str, dict[str, str]]:
            cloned: dict[str, dict[str, str]] = {}
            for name, window in template.items():
                if not isinstance(window, Mapping):
                    continue
                start = _clean_str(window.get("start"))
                end = _clean_str(window.get("end"))
                if start and end:
                    cloned[str(name)] = {"start": start, "end": end}
            return cloned

        def _normalize_killzone(raw: Any, fallback: Mapping[str, dict[str, str]]) -> dict[str, dict[str, str]]:
            if isinstance(raw, Mapping):
                cleaned: dict[str, dict[str, str]] = {}
                for name, window in raw.items():
                    if not isinstance(name, str) or not isinstance(window, Mapping):
                        continue
                    start = _clean_str(window.get("start"))
                    end = _clean_str(window.get("end"))
                    if start and end:
                        cleaned[name] = {"start": start, "end": end}
                if cleaned:
                    return cleaned
            return {key: dict(value) for key, value in fallback.items()}

        folder_cfg = data.get("folder") or {}
        folder = FolderConfig(
            folder=_clean_str(folder_cfg.get("folder_path")),
            delete_after=_as_bool(folder_cfg.get("delete_after"), True),
            max_files=_as_int(folder_cfg.get("max_files"), 0),
            only_generate_if_changed=_as_bool(folder_cfg.get("only_generate_if_changed"), False),
        )

        upload_cfg = data.get("upload") or {}
        upload = UploadConfig(
            upload_workers=_as_int(upload_cfg.get("upload_workers"), 4),
            cache_enabled=_as_bool(upload_cfg.get("cache_enabled"), True),
            optimize_lossless=_as_bool(upload_cfg.get("optimize_lossless"), False),
        )

        image_cfg = data.get("image_processing") or {}
        image_processing = ImageProcessingConfig(
            max_width=_as_int(image_cfg.get("max_width"), 1600),
            jpeg_quality=_as_int(image_cfg.get("jpeg_quality"), 85),
        )

        context_cfg = data.get("context") or {}
        context = ContextConfig(
            ctx_limit=_as_int(context_cfg.get("ctx_limit"), 2000),
            create_ctx_json=_as_bool(context_cfg.get("create_ctx_json"), True),
            prefer_ctx_json=_as_bool(context_cfg.get("prefer_ctx_json"), True),
            ctx_json_n=_as_int(context_cfg.get("ctx_json_n"), 5),
            remember_context=_as_bool(context_cfg.get("remember_context"), True),
            n_reports=_as_int(context_cfg.get("n_reports"), 1),
        )

        api_cfg = data.get("api") or {}
        api = ApiConfig(
            tries=_as_int(api_cfg.get("tries"), 5),
            delay=_as_float(api_cfg.get("delay"), 2.0),
        )

        telegram_cfg = data.get("telegram") or {}
        telegram = TelegramConfig(
            enabled=_as_bool(telegram_cfg.get("enabled"), False),
            token=_clean_str(telegram_cfg.get("token")),
            chat_id=_clean_str(telegram_cfg.get("chat_id")),
            skip_verify=_as_bool(telegram_cfg.get("skip_verify"), False),
            ca_path=_clean_str(telegram_cfg.get("ca_path")),
            notify_on_early_exit=_as_bool(telegram_cfg.get("notify_on_early_exit"), True),
        )

        mt5_cfg = data.get("mt5") or {}
        mt5_config = MT5Config(
            enabled=_as_bool(mt5_cfg.get("enabled"), False),
            symbol=_clean_str(mt5_cfg.get("symbol")),
            n_M1=_as_int(mt5_cfg.get("n_M1"), 120),
            n_M5=_as_int(mt5_cfg.get("n_M5"), 180),
            n_M15=_as_int(mt5_cfg.get("n_M15"), 96),
            n_H1=_as_int(mt5_cfg.get("n_H1"), 120),
        )
        mt5_terminal_path = _clean_str(mt5_cfg.get("terminal_path"))

        no_run_cfg = data.get("no_run") or {}
        summer_default = _clone_killzone(DEFAULT_KILLZONE_SUMMER)
        winter_default = _clone_killzone(DEFAULT_KILLZONE_WINTER)
        no_run = NoRunConfig(
            weekend_enabled=_as_bool(no_run_cfg.get("weekend_enabled"), True),
            killzone_enabled=_as_bool(no_run_cfg.get("killzone_enabled"), True),
            holiday_check_enabled=_as_bool(no_run_cfg.get("holiday_check_enabled"), True),
            holiday_check_country=_clean_str(no_run_cfg.get("holiday_check_country"), "US"),
            timezone=_clean_str(no_run_cfg.get("timezone"), "Asia/Ho_Chi_Minh"),
            killzone_summer=_normalize_killzone(no_run_cfg.get("killzone_summer"), summer_default),
            killzone_winter=_normalize_killzone(no_run_cfg.get("killzone_winter"), winter_default),
        )

        no_trade_cfg = data.get("no_trade") or {}
        no_trade = NoTradeConfig(
            enabled=_as_bool(no_trade_cfg.get("enabled"), True),
            spread_max_pips=_as_float(no_trade_cfg.get("spread_max_pips"), 2.5),
            min_atr_m5_pips=_as_float(no_trade_cfg.get("min_atr_m5_pips"), 3.0),
            min_dist_keylvl_pips=_as_float(no_trade_cfg.get("min_dist_keylvl_pips"), 5.0),
            allow_session_asia=_as_bool(no_trade_cfg.get("allow_session_asia"), True),
            allow_session_london=_as_bool(no_trade_cfg.get("allow_session_london"), True),
            allow_session_ny=_as_bool(no_trade_cfg.get("allow_session_ny"), True),
        )

        auto_trade_cfg = data.get("auto_trade") or {}
        split_tp_ratio = _as_int(auto_trade_cfg.get("split_tp_ratio"), 50)
        auto_trade = AutoTradeConfig(
            enabled=_as_bool(auto_trade_cfg.get("enabled"), False),
            strict_bias=_as_bool(auto_trade_cfg.get("strict_bias"), True),
            size_mode=_clean_str(auto_trade_cfg.get("size_mode"), "risk_percent") or "risk_percent",
            risk_per_trade=_as_float(auto_trade_cfg.get("risk_per_trade"), 0.5),
            split_tp_enabled=_as_bool(auto_trade_cfg.get("split_tp_enabled"), split_tp_ratio > 0),
            split_tp_ratio=split_tp_ratio,
            deviation=_as_int(auto_trade_cfg.get("deviation"), 20),
            magic_number=_as_int(auto_trade_cfg.get("magic_number"), 26092025),
            comment=_clean_str(auto_trade_cfg.get("comment"), "AI-ICT"),
            pending_ttl_min=_as_int(auto_trade_cfg.get("pending_ttl_min"), 90),
            min_rr_tp2=_as_float(auto_trade_cfg.get("min_rr_tp2"), 2.0),
            cooldown_min=_as_int(auto_trade_cfg.get("cooldown_min"), 10),
            dynamic_pending=_as_bool(auto_trade_cfg.get("dynamic_pending"), True),
            dry_run=_as_bool(auto_trade_cfg.get("dry_run"), False),
            move_to_be_after_tp1=_as_bool(auto_trade_cfg.get("move_to_be_after_tp1"), True),
            trailing_atr_mult=_as_float(auto_trade_cfg.get("trailing_atr_mult"), 0.5),
            filling_type=_clean_str(auto_trade_cfg.get("filling_type"), "IOC") or "IOC",
        )

        news_cfg = data.get("news") or {}
        keywords = _normalize_keywords(news_cfg.get("priority_keywords"))
        if not keywords:
            keywords = tuple(sorted(DEFAULT_HIGH_IMPACT_KEYWORDS))
        currency_overrides = _normalize_overrides(news_cfg.get("currency_country_overrides"))
        symbol_overrides = _normalize_overrides(news_cfg.get("symbol_country_overrides"))
        news = NewsConfig(
            block_enabled=_as_bool(news_cfg.get("block_enabled"), True),
            block_before_min=_as_int(news_cfg.get("block_before_min"), 15),
            block_after_min=_as_int(news_cfg.get("block_after_min"), 15),
            cache_ttl_sec=_as_int(news_cfg.get("cache_ttl_sec"), 300),
            provider_timeout_sec=_as_int(news_cfg.get("provider_timeout_sec"), 20),
            priority_keywords=keywords,
            provider_error_threshold=_as_int(news_cfg.get("provider_error_threshold"), 2),
            provider_error_backoff_sec=_as_int(news_cfg.get("provider_error_backoff_sec"), 300),
            surprise_score_threshold=_as_float(news_cfg.get("surprise_score_threshold"), 0.5),
            currency_country_overrides=currency_overrides,
            symbol_country_overrides=symbol_overrides,
        )

        persistence_cfg = data.get("persistence") or {}
        persistence = PersistenceConfig(
            max_md_reports=_as_int(persistence_cfg.get("max_md_reports"), 10),
            max_json_reports=_as_int(persistence_cfg.get("max_json_reports"), 10),
        )

        prompts_cfg = data.get("prompts") or {}
        prompt_state = PromptState(
            file_path=_clean_str(prompts_cfg.get("prompt_file_path")),
            auto_load_from_disk=_as_bool(prompts_cfg.get("auto_load_prompt_txt"), True),
        )

        autorun_state = AutorunState(
            enabled=_as_bool(data.get("autorun"), False),
            interval_secs=max(1, _as_int(data.get("autorun_secs"), 60)),
        )

        chart_cfg = data.get("chart") or {}
        chart_defaults = ChartConfig()
        chart = ChartConfig(
            timeframe=_clean_str(chart_cfg.get("timeframe"), chart_defaults.timeframe) or chart_defaults.timeframe,
            num_candles=_as_int(chart_cfg.get("num_candles"), chart_defaults.num_candles),
            chart_type=_clean_str(chart_cfg.get("chart_type"), chart_defaults.chart_type) or chart_defaults.chart_type,
            refresh_interval_secs=_as_int(
                chart_cfg.get("refresh_interval_secs"), chart_defaults.refresh_interval_secs
            ),
        )

        model_name = _clean_str(data.get("model"), MODELS.DEFAULT_VISION) or MODELS.DEFAULT_VISION

        return cls(
            folder=folder,
            upload=upload,
            image_processing=image_processing,
            context=context,
            api=api,
            telegram=telegram,
            mt5=mt5_config,
            mt5_terminal_path=mt5_terminal_path,
            no_run=no_run,
            no_trade=no_trade,
            auto_trade=auto_trade,
            news=news,
            persistence=persistence,
            chart=chart,
            model=model_name,
            autorun=autorun_state,
            prompt=prompt_state,
        )


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
