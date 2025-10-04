from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FolderConfig:
    """Cấu hình liên quan đến thư mục và file."""
    folder: str
    delete_after: bool
    max_files: int


@dataclass(frozen=True)
class UploadConfig:
    """Cấu hình cho việc upload file."""
    upload_workers: int
    cache_enabled: bool
    optimize_lossless: bool
    only_generate_if_changed: bool


@dataclass(frozen=True)
class ContextConfig:
    """Cấu hình cho việc xây dựng ngữ cảnh."""
    ctx_limit: int
    create_ctx_json: bool
    prefer_ctx_json: bool
    ctx_json_n: int


@dataclass(frozen=True)
class TelegramConfig:
    """Cấu hình cho thông báo Telegram."""
    enabled: bool
    token: str
    chat_id: str
    skip_verify: bool
    ca_path: str


@dataclass(frozen=True)
class MT5Config:
    """Cấu hình cho kết nối MetaTrader 5."""
    enabled: bool
    symbol: str
    n_M1: int
    n_M5: int
    n_M15: int
    n_H1: int


@dataclass(frozen=True)
class NoTradeConfig:
    """Cấu hình cho các quy tắc không giao dịch (NO-TRADE)."""
    enabled: bool
    spread_factor: float
    min_atr_m5_pips: float
    min_ticks_per_min: int


@dataclass(frozen=True)
class AutoTradeConfig:
    """Cấu hình cho tự động giao dịch."""
    enabled: bool
    strict_bias: bool
    size_mode: str
    lots_total: float
    equity_risk_pct: float
    money_risk: float
    split_tp1_pct: int
    deviation_points: int
    pending_threshold_points: int
    magic: int
    comment_prefix: str
    pending_ttl_min: int
    min_rr_tp2: float
    min_dist_keylvl_pips: float
    cooldown_min: int
    dynamic_pending: bool
    dry_run: bool
    move_to_be_after_tp1: bool
    trailing_atr_mult: float
    allow_session_asia: bool
    allow_session_london: bool
    allow_session_ny: bool


@dataclass(frozen=True)
class NewsConfig:
    """Cấu hình liên quan đến tin tức."""
    block_enabled: bool
    block_before_min: int
    block_after_min: int
    cache_ttl_sec: int


@dataclass(frozen=True)
class ScheduleConfig:
    """Cấu hình cho các quy tắc lập lịch chạy."""
    no_run_weekend_enabled: bool
    no_run_killzone_enabled: bool


@dataclass(frozen=True)
class RunConfig:
    """
    Snapshot cấu hình đã được nhóm lại cho một lần chạy phân tích.
    """
    folder: FolderConfig
    upload: UploadConfig
    context: ContextConfig
    telegram: TelegramConfig
    mt5: MT5Config
    no_trade: NoTradeConfig
    auto_trade: AutoTradeConfig
    news: NewsConfig
    schedule: ScheduleConfig

    def __post_init__(self):
        """
        Ghi log debug sau khi một đối tượng RunConfig được khởi tạo.
        """
        logger.debug("Bắt đầu hàm __post_init__ của RunConfig.")
        logger.debug(f"RunConfig được khởi tạo: {self}")
        logger.debug("Kết thúc hàm __post_init__ của RunConfig.")
