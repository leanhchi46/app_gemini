# src/config/workspace_manager.py
from __future__ import annotations

import json
from pathlib import Path
import logging
import os
from typing import TYPE_CHECKING

from src.config.constants import WORKSPACE_JSON, API_KEY_ENC, DEFAULT_MODEL
from src.utils.utils import obfuscate_text, deobfuscate_text
from src.utils import ui_utils
from src.ui import history_manager # Import module mới

if TYPE_CHECKING:
    from src.ui.app_ui import TradingToolApp


def _save_workspace(app: "TradingToolApp"):
    """
    Lưu toàn bộ cấu hình và trạng thái hiện tại của ứng dụng vào file `workspace.json`.
    Các thông tin nhạy cảm như Telegram token được mã hóa trước khi lưu.
    """
    data = {
        "prompt_file_path": app.prompt_file_path_var.get().strip(),
        "auto_load_prompt_txt": bool(app.auto_load_prompt_txt_var.get()),
        "folder_path": app.folder_path.get().strip(),
        "model": app.model_var.get(),
        "delete_after": bool(app.delete_after_var.get()),
        "max_files": int(app.max_files_var.get()),
        "autorun": bool(app.autorun_var.get()),
        "autorun_secs": int(app.autorun_seconds_var.get()),
        "remember_ctx": bool(app.remember_context_var.get()),
        "ctx_n_reports": int(app.context_n_reports_var.get()),
        "ctx_limit_chars": int(app.context_limit_chars_var.get()),
        "create_ctx_json": bool(app.create_ctx_json_var.get()),
        "prefer_ctx_json": bool(app.prefer_ctx_json_var.get()),
        "ctx_json_n": int(app.ctx_json_n_var.get()),

        "telegram_enabled": bool(app.telegram_enabled_var.get()),
        "telegram_token_enc": obfuscate_text(app.telegram_token_var.get().strip())
        if app.telegram_token_var.get().strip()
        else "",
        "telegram_chat_id": app.telegram_chat_id_var.get().strip(),
        "telegram_skip_verify": bool(app.telegram_skip_verify_var.get()),
        "telegram_ca_path": app.telegram_ca_path_var.get().strip(),

        "mt5_enabled": bool(app.mt5_enabled_var.get()),
        "mt5_term_path": app.mt5_term_path_var.get().strip(),
        "mt5_symbol": app.mt5_symbol_var.get().strip(),
        "mt5_n_M1": int(app.mt5_n_M1.get()),
        "mt5_n_M5": int(app.mt5_n_M5.get()),
        "mt5_n_M15": int(app.mt5_n_M15.get()),
        "mt5_n_H1": int(app.mt5_n_H1.get()),

        "no_trade_enabled": bool(app.no_trade_enabled_var.get()),
        "nt_spread_factor": float(app.nt_spread_factor_var.get()),
        "nt_min_atr_m5_pips": float(app.nt_min_atr_m5_pips_var.get()),
        "nt_min_ticks_per_min": int(app.nt_min_ticks_per_min_var.get()),

        "upload_workers": int(app.upload_workers_var.get()),
        "cache_enabled": bool(app.cache_enabled_var.get()),
        "opt_lossless": bool(app.optimize_lossless_var.get()),
        "only_generate_if_changed": bool(app.only_generate_if_changed_var.get()),

        "auto_trade_enabled": bool(app.auto_trade_enabled_var.get()),
        "trade_strict_bias": bool(app.trade_strict_bias_var.get()),
        "trade_size_mode": app.trade_size_mode_var.get(),
        "trade_lots_total": float(app.trade_lots_total_var.get()),
        "trade_equity_risk_pct": float(app.trade_equity_risk_pct_var.get()),
        "trade_money_risk": float(app.trade_money_risk_var.get()),
        "trade_split_tp1_pct": int(app.trade_split_tp1_pct_var.get()),
        "trade_deviation_points": int(app.trade_deviation_points_var.get()),
        "trade_pending_threshold_points": int(app.trade_pending_threshold_points_var.get()),
        "trade_magic": int(app.trade_magic_var.get()),
        "trade_comment_prefix": app.trade_comment_prefix_var.get(),

        "trade_pending_ttl_min": int(app.trade_pending_ttl_min_var.get()),
        "trade_min_rr_tp2": float(app.trade_min_rr_tp2_var.get()),
        "trade_min_dist_keylvl_pips": float(app.trade_min_dist_keylvl_pips_var.get()),
        "trade_cooldown_min": int(app.trade_cooldown_min_var.get()),
        "trade_dynamic_pending": bool(app.trade_dynamic_pending_var.get()),
        "auto_trade_dry_run": bool(app.auto_trade_dry_run_var.get()),
        "trade_move_to_be_after_tp1": bool(app.trade_move_to_be_after_tp1_var.get()),
        "trade_trailing_atr_mult": float(app.trade_trailing_atr_mult_var.get()),
        "trade_allow_session_asia": bool(app.trade_allow_session_asia_var.get()),
        "trade_allow_session_london": bool(app.trade_allow_session_london_var.get()),
        "trade_allow_session_ny": bool(app.trade_allow_session_ny_var.get()),
        "news_block_before_min": int(app.trade_news_block_before_min_var.get()),
        "news_block_after_min": int(app.trade_news_block_after_min_var.get()),

        "norun_weekend": bool(app.norun_weekend_var.get()),
        "norun_killzone": bool(app.norun_killzone_var.get()),
        # Thêm các biến trạng thái MT5 reconnect/check
        "mt5_reconnect_attempts": app.app_logic._mt5_reconnect_attempts,
        "mt5_max_reconnect_attempts": app.app_logic._mt5_max_reconnect_attempts,
        "mt5_reconnect_delay_sec": app.app_logic._mt5_reconnect_delay_sec,
        "mt5_check_interval_sec": app.app_logic._mt5_check_interval_sec,
    }
    try:
        WORKSPACE_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        ui_utils.ui_message(app, "info", "Workspace", "Đã lưu workspace.")
        logging.info("Workspace: Đã lưu workspace thành công.")
    except Exception as e:
        ui_utils.ui_message(app, "error", "Workspace", str(e))
        logging.error(f"Workspace: Lỗi khi lưu workspace: {e}")

def _load_workspace(app: "TradingToolApp"):
    """
    Tải cấu hình và trạng thái ứng dụng từ file `workspace.json` khi khởi động.
    Giải mã các thông tin nhạy cảm đã được mã hóa.
    """
    if not WORKSPACE_JSON.exists():
        logging.info("Workspace: File workspace.json không tồn tại, bỏ qua tải.")
        return
    try:
        data = json.loads(WORKSPACE_JSON.read_text(encoding="utf-8"))
        ui_utils.ui_message(app, "info", "Workspace", "Đã khôi phục workspace.")
        logging.info("Workspace: Đã tải workspace thành công.")
    except json.JSONDecodeError as e:
        ui_utils.ui_message(app, "error", "Workspace", f"Lỗi đọc file workspace.json: {e}")
        logging.error(f"Workspace: Lỗi JSON khi tải workspace: {e}")
        return
    except Exception as e:
        ui_utils.ui_message(app, "error", "Workspace", f"Lỗi không xác định khi tải workspace: {e}")
        logging.error(f"Workspace: Lỗi không xác định khi tải workspace: {e}")
        return

    app.prompt_file_path_var.set(data.get("prompt_file_path", ""))
    app.auto_load_prompt_txt_var.set(bool(data.get("auto_load_prompt_txt", True)))
    folder = data.get("folder_path", "")
    if folder and Path(folder).exists():
        app.folder_path.set(folder)
        app._load_files(folder)
        app._refresh_history_list()
        app._refresh_json_list()

    app.model_var.set(data.get("model", DEFAULT_MODEL))
    app.delete_after_var.set(bool(data.get("delete_after", True)))
    app.max_files_var.set(int(data.get("max_files", 0)))
    app.autorun_var.set(bool(data.get("autorun", False)))
    app.autorun_seconds_var.set(int(data.get("autorun_secs", 60)))

    app.remember_context_var.set(bool(data.get("remember_ctx", True)))
    app.context_n_reports_var.set(int(data.get("ctx_n_reports", 1)))
    app.context_limit_chars_var.set(int(data.get("ctx_limit_chars", 2000)))
    app.create_ctx_json_var.set(bool(data.get("create_ctx_json", True)))
    app.prefer_ctx_json_var.set(bool(data.get("prefer_ctx_json", True)))
    app.ctx_json_n_var.set(int(data.get("ctx_json_n", 5)))

    app.telegram_enabled_var.set(bool(data.get("telegram_enabled", False)))
    app.telegram_token_var.set(deobfuscate_text(data.get("telegram_token_enc", "")))
    app.telegram_chat_id_var.set(data.get("telegram_chat_id", ""))
    app.telegram_skip_verify_var.set(bool(data.get("telegram_skip_verify", False)))
    app.telegram_ca_path_var.set(data.get("telegram_ca_path", ""))

    # Cấu hình Gemini API và cập nhật UI sau khi tải API key từ workspace
    app.app_logic._configure_gemini_api_and_update_ui(app)

    app.mt5_enabled_var.set(bool(data.get("mt5_enabled", False)))
    app.mt5_term_path_var.set(data.get("mt5_term_path", ""))
    app.mt5_symbol_var.set(data.get("mt5_symbol", ""))
    app.mt5_n_M1.set(int(data.get("mt5_n_M1", 120)))
    app.mt5_n_M5.set(int(data.get("mt5_n_M5", 180)))
    app.mt5_n_M15.set(int(data.get("mt5_n_M15", 96)))
    app.mt5_n_H1.set(int(data.get("mt5_n_H1", 120)))

    app.no_trade_enabled_var.set(bool(data.get("no_trade_enabled", True)))
    app.nt_spread_factor_var.set(float(data.get("nt_spread_factor", 1.2)))
    app.nt_min_atr_m5_pips_var.set(float(data.get("nt_min_atr_m5_pips", 3.0)))
    app.nt_min_ticks_per_min_var.set(int(data.get("nt_min_ticks_per_min", 5)))

    app.upload_workers_var.set(int(data.get("upload_workers", 4)))
    app.cache_enabled_var.set(bool(data.get("cache_enabled", True)))
    app.optimize_lossless_var.set(bool(data.get("opt_lossless", False)))
    app.only_generate_if_changed_var.set(bool(data.get("only_generate_if_changed", False)))

    app.auto_trade_enabled_var.set(bool(data.get("auto_trade_enabled", False)))
    app.trade_strict_bias_var.set(bool(data.get("trade_strict_bias", True)))
    app.trade_size_mode_var.set(data.get("trade_size_mode", "lots"))
    app.trade_lots_total_var.set(float(data.get("trade_lots_total", 0.10)))
    app.trade_equity_risk_pct_var.set(float(data.get("trade_equity_risk_pct", 1.0)))
    app.trade_money_risk_var.set(float(data.get("trade_money_risk", 10.0)))
    app.trade_split_tp1_pct_var.set(int(data.get("trade_split_tp1_pct", 50)))
    app.trade_deviation_points_var.set(int(data.get("trade_deviation_points", 20)))
    app.trade_pending_threshold_points_var.set(int(data.get("trade_pending_threshold_points", 60)))
    app.trade_magic_var.set(int(data.get("trade_magic", 26092025)))
    app.trade_comment_prefix_var.set(data.get("trade_comment_prefix", "AI-ICT"))

    app.trade_pending_ttl_min_var.set(int(data.get("trade_pending_ttl_min", 90)))
    app.trade_min_rr_tp2_var.set(float(data.get("trade_min_rr_tp2", 2.0)))
    app.trade_min_dist_keylvl_pips_var.set(float(data.get("trade_min_dist_keylvl_pips", 5.0)))
    app.trade_cooldown_min_var.set(int(data.get("trade_cooldown_min", 10)))
    app.trade_dynamic_pending_var.set(bool(data.get("trade_dynamic_pending", True)))
    app.auto_trade_dry_run_var.set(bool(data.get("auto_trade_dry_run", False)))
    app.trade_move_to_be_after_tp1_var.set(bool(data.get("trade_move_to_be_after_tp1", True)))
    app.trade_trailing_atr_mult_var.set(float(data.get("trade_trailing_atr_mult", 0.5)))
    app.trade_allow_session_asia_var.set(bool(data.get("trade_allow_session_asia", True)))
    app.trade_allow_session_london_var.set(bool(data.get("trade_allow_session_london", True)))
    app.trade_allow_session_ny_var.set(bool(data.get("trade_allow_session_ny", True)))
    app.trade_news_block_before_min_var.set(int(data.get("news_block_before_min", 15)))
    app.trade_news_block_after_min_var.set(int(data.get("news_block_after_min", 15)))

    app.norun_weekend_var.set(bool(data.get("norun_weekend", True)))
    app.norun_killzone_var.set(bool(data.get("norun_killzone", True)))

    # Tải các biến trạng thái MT5 reconnect/check
    app.app_logic._mt5_reconnect_attempts = int(data.get("mt5_reconnect_attempts", 0))
    app.app_logic._mt5_max_reconnect_attempts = int(data.get("mt5_max_reconnect_attempts", 5))
    app.app_logic._mt5_reconnect_delay_sec = int(data.get("mt5_reconnect_delay_sec", 5))
    app.app_logic._mt5_check_interval_sec = int(data.get("mt5_check_interval_sec", 30))

def _delete_workspace(app: "TradingToolApp"):
    """
    Xóa file `workspace.json` khỏi hệ thống.
    """
    try:
        if WORKSPACE_JSON.exists():
            WORKSPACE_JSON.unlink()
        ui_utils.ui_message(app, "info", "Workspace", "Đã xoá workspace.")
    except Exception as e:
        ui_utils.ui_message(app, "error", "Workspace", str(e))
