from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RunConfig:
    """
    Snapshot cấu hình cho một lần chạy phân tích (worker thread sử dụng).
    """
    logger.debug("Khởi tạo RunConfig.")

    # Folder & basic options
    folder: str
    delete_after: bool
    max_files: int

    # Upload/cache
    upload_workers: int
    cache_enabled: bool
    optimize_lossless: bool
    only_generate_if_changed: bool

    # Context JSON / prompt memory
    ctx_limit: int
    create_ctx_json: bool
    prefer_ctx_json: bool
    ctx_json_n: int

    # Telegram
    telegram_enabled: bool
    telegram_token: str
    telegram_chat_id: str
    telegram_skip_verify: bool
    telegram_ca_path: str

    # MT5
    mt5_enabled: bool
    mt5_symbol: str
    mt5_n_M1: int
    mt5_n_M5: int
    mt5_n_M15: int
    mt5_n_H1: int

    # NO-TRADE rules
    nt_enabled: bool
    nt_spread_factor: float
    nt_min_atr_m5_pips: float
    nt_min_ticks_per_min: int

    # Auto-trade
    auto_trade_enabled: bool
    trade_strict_bias: bool
    trade_size_mode: str
    trade_lots_total: float
    trade_equity_risk_pct: float
    trade_money_risk: float
    trade_split_tp1_pct: int
    trade_deviation_points: int
    trade_pending_threshold_points: int
    trade_magic: int
    trade_comment_prefix: str
    trade_pending_ttl_min: int
    trade_min_rr_tp2: float
    trade_min_dist_keylvl_pips: float
    trade_cooldown_min: int
    trade_dynamic_pending: bool
    auto_trade_dry_run: bool
    trade_move_to_be_after_tp1: bool
    trade_trailing_atr_mult: float
    trade_allow_session_asia: bool
    trade_allow_session_london: bool
    trade_allow_session_ny: bool
    trade_news_block_before_min: int
    trade_news_block_after_min: int
    # News controls
    trade_news_block_enabled: bool
    news_cache_ttl_sec: int
    no_run_weekend_enabled: bool
    no_run_killzone_enabled: bool

    def __post_init__(self):
        """
        Ghi log debug sau khi một đối tượng RunConfig được khởi tạo.
        """
        logger.debug(f"RunConfig được khởi tạo: {self}")
