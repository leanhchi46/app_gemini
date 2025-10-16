import json, queue
from pathlib import Path
from PyQt6.QtWidgets import QApplication
from APP.ui.pyqt6.event_bridge import UiQueueBridge
from APP.ui.pyqt6.main_window import TradingMainWindow
from APP.ui.pyqt6.controller_bridge import ControllerSet
from APP.ui.state import UiConfigState
from APP.configs.app_config import (
    ApiConfig, AutoTradeConfig, ChartConfig, ContextConfig, FMPConfig, FolderConfig,
    ImageProcessingConfig, MT5Config, NewsConfig, NoRunConfig, NoTradeConfig,
    PersistenceConfig, TEConfig, TelegramConfig, UploadConfig,
)
from tests.ui.test_pyqt6_main_window import ImmediateThreadingAdapter, StubIOController, _drain_bridge

app = QApplication.instance() or QApplication([])
prompt_file = Path('temp_prompt.json')
prompt_file.write_text(json.dumps({'no_entry': 'demo', 'entry_run': 'demo'}), encoding='utf-8')
config = UiConfigState(
    folder=FolderConfig(folder='.', delete_after=True, max_files=5, only_generate_if_changed=False),
    upload=UploadConfig(upload_workers=2, cache_enabled=True, optimize_lossless=False),
    image_processing=ImageProcessingConfig(max_width=800, jpeg_quality=90),
    context=ContextConfig(ctx_limit=2048, create_ctx_json=True, prefer_ctx_json=False, ctx_json_n=5, remember_context=True, n_reports=2),
    api=ApiConfig(tries=3, delay=1.0),
    telegram=TelegramConfig(enabled=False, token='', chat_id='', skip_verify=False, ca_path='', notify_on_early_exit=False),
    mt5=MT5Config(enabled=False, symbol='XAUUSD', n_M1=120, n_M5=90, n_M15=60, n_H1=30),
    mt5_terminal_path='',
    no_run=NoRunConfig(weekend_enabled=False, killzone_enabled=False, holiday_check_enabled=False, holiday_check_country='US', timezone='UTC', killzone_summer=None, killzone_winter=None),
    no_trade=NoTradeConfig(enabled=False, spread_max_pips=2.0, min_atr_m5_pips=1.5, min_dist_keylvl_pips=3.0, allow_session_asia=True, allow_session_london=True, allow_session_ny=True),
    auto_trade=AutoTradeConfig(enabled=False, strict_bias=False, size_mode='risk_percent', risk_per_trade=0.5, split_tp_enabled=False, split_tp_ratio=50, deviation=10, magic_number=999, comment='', pending_ttl_min=60, min_rr_tp2=1.5, cooldown_min=15, dynamic_pending=False, dry_run=True, move_to_be_after_tp1=False, trailing_atr_mult=0.5, filling_type='IOC'),
    news=NewsConfig(block_enabled=False, block_before_min=0, block_after_min=0, cache_ttl_sec=60, priority_keywords=(), provider_error_threshold=2, provider_error_backoff_sec=300, surprise_score_threshold=0.5, currency_country_overrides=None, symbol_country_overrides=None),
    persistence=PersistenceConfig(max_md_reports=10),
    fmp=FMPConfig(enabled=False, api_key=''),
    te=TEConfig(enabled=False, api_key='', skip_ssl_verify=False),
    chart=ChartConfig(timeframe='M15', num_candles=150, chart_type='Nen', refresh_interval_secs=5),
    model='gemini-pro',
    autorun=AutorunState(enabled=False, interval_secs=300),
    prompt=PromptState(file_path=str(prompt_file), auto_load_from_disk=True),
)
bridge = UiQueueBridge(queue.Queue())
threading = ImmediateThreadingAdapter(bridge)
stub_io = StubIOController()
window = TradingMainWindow(config, threading, bridge, controllers=ControllerSet(io=stub_io))
window._handle_prompt_load(str(prompt_file))
_drain_bridge(bridge)
print('calls:', stub_io.calls)
bridge.stop()
window.close()
window.deleteLater()
threading.threading_manager.shutdown(force=True)
