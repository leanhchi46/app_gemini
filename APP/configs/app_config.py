from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FolderConfig:
    """Cấu hình liên quan đến thư mục và file."""
    folder: str
    delete_after: bool
    max_files: int
    only_generate_if_changed: bool


@dataclass(frozen=True)
class UploadConfig:
    """Cấu hình cho việc upload file."""
    upload_workers: int
    cache_enabled: bool
    optimize_lossless: bool


@dataclass(frozen=True)
class ImageProcessingConfig:
    """Cấu hình cho việc xử lý và tối ưu hóa hình ảnh."""
    max_width: int = 1600
    jpeg_quality: int = 85


@dataclass(frozen=True)
class ContextConfig:
    """Cấu hình cho việc xây dựng ngữ cảnh."""
    ctx_limit: int
    create_ctx_json: bool
    prefer_ctx_json: bool
    ctx_json_n: int
    remember_context: bool
    n_reports: int


@dataclass(frozen=True)
class TelegramConfig:
    """Cấu hình cho thông báo Telegram."""
    enabled: bool
    token: str
    chat_id: str
    skip_verify: bool
    ca_path: str
    notify_on_early_exit: bool = False


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
class NoRunConfig:
    """Cấu hình cho các quy tắc không cho phép chạy (NO-RUN)."""
    weekend_enabled: bool
    killzone_enabled: bool
    holiday_check_enabled: bool
    holiday_check_country: str = "US"
    timezone: str = "Asia/Ho_Chi_Minh"
    killzone_summer: dict[str, dict[str, str]] | None = None
    killzone_winter: dict[str, dict[str, str]] | None = None


@dataclass(frozen=True)
class NoTradeConfig:
    """Cấu hình cho các quy tắc không giao dịch (NO-TRADE)."""
    enabled: bool
    spread_max_pips: float
    min_atr_m5_pips: float
    min_dist_keylvl_pips: float
    allow_session_asia: bool
    allow_session_london: bool
    allow_session_ny: bool


@dataclass(frozen=True)
class AutoTradeConfig:
    """Cấu hình cho tự động giao dịch."""
    enabled: bool
    strict_bias: bool
    size_mode: str
    risk_per_trade: float  # Thay thế cho equity_risk_pct và money_risk
    split_tp_enabled: bool
    split_tp_ratio: int
    deviation: int
    magic_number: int
    comment: str
    pending_ttl_min: int
    min_rr_tp2: float
    cooldown_min: int
    dynamic_pending: bool
    dry_run: bool
    move_to_be_after_tp1: bool
    trailing_atr_mult: float
    filling_type: str = "IOC"  # Thêm filling_type


@dataclass(frozen=True)
class NewsConfig:
    """Cấu hình liên quan đến tin tức."""

    block_enabled: bool
    block_before_min: int
    block_after_min: int
    cache_ttl_sec: int
    provider_timeout_sec: int = 20
    priority_keywords: tuple[str, ...] | None = None
    provider_error_threshold: int = 2
    provider_error_backoff_sec: int = 300
    surprise_score_threshold: float = 0.5
    currency_country_overrides: dict[str, list[str]] | None = None
    symbol_country_overrides: dict[str, list[str]] | None = None


@dataclass(frozen=True)
class PersistenceConfig:
    """Cấu hình liên quan đến việc lưu trữ dữ liệu."""
    max_md_reports: int = 10
    max_json_reports: int = 10


@dataclass(frozen=True)
class LoggingConfig:
    """Cấu hình cho hệ thống logging."""
    log_dir: str = "Log"
    log_file_name: str = "app_debug.log"
    log_rotation_size_mb: int = 5
    log_rotation_backup_count: int = 5


@dataclass(frozen=True)
class ApiConfig:
    """Cấu hình cho các cuộc gọi API."""
    tries: int = 5
    delay: float = 2.0


@dataclass(frozen=True)
class ChartConfig:
    """Cấu hình cho tab biểu đồ."""
    timeframe: str = "M15"
    num_candles: int = 150
    chart_type: str = "Nến"
    refresh_interval_secs: int = 5


@dataclass(frozen=True)
class RunConfig:
    """
    Snapshot cấu hình đã được nhóm lại cho một lần chạy phân tích.
    """
    folder: FolderConfig
    upload: UploadConfig
    image_processing: ImageProcessingConfig
    context: ContextConfig
    telegram: TelegramConfig
    mt5: MT5Config
    no_run: NoRunConfig
    no_trade: NoTradeConfig
    auto_trade: AutoTradeConfig
    news: NewsConfig
    persistence: PersistenceConfig
    chart: ChartConfig = field(default_factory=ChartConfig)
    api: ApiConfig = field(default_factory=ApiConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)

    def __post_init__(self):
        """
        Ghi log debug sau khi một đối tượng RunConfig được khởi tạo.
        """
        logger.debug("Bắt đầu hàm __post_init__ của RunConfig.")
        logger.debug(f"RunConfig được khởi tạo: {self}")
        logger.debug("Kết thúc hàm __post_init__ của RunConfig.")
