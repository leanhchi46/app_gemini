from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Dict, List, Optional

import MetaTrader5 as mt5

from src.config.constants import APP_DIR
from src.core.worker_modules import no_run_trade_conditions
from src.utils import logging_utils, mt5_utils, report_parser, ui_utils

logger = logging.getLogger(__name__) # Khởi tạo logger

try:
    import MetaTrader5 as mt5  # type: ignore
except Exception as e:  # pragma: no cover - optional dependency
    mt5 = None  # type: ignore
    logger.warning(f"Không thể import MetaTrader5: {e}. Các chức năng MT5 sẽ bị vô hiệu hóa.")

if TYPE_CHECKING:
    from scripts.tool import TradingToolApp
    from src.config.config import RunConfig


def _calc_rr(entry: Optional[float], sl: Optional[float], tp: Optional[float]) -> Optional[float]:
    """Tính toán tỷ lệ rủi ro/lợi nhuận."""
    logger.debug(f"Bắt đầu hàm _calc_rr. Entry: {entry}, SL: {sl}, TP: {tp}")
    try:
        risk = abs((entry or 0) - (sl or 0))
        reward = abs((tp or 0) - (entry or 0))
        result = (reward / risk) if risk > 0 else None
        logger.debug(f"Kết thúc hàm _calc_rr. RR: {result}")
        return result
    except Exception as e:
        logger.error(f"Lỗi khi tính toán RR: {e}")
        logger.debug("Kết thúc hàm _calc_rr (lỗi).")
        return None

def _near_key_levels_too_close(mt5_ctx: Dict, min_pips: float, cp: float) -> bool:
    """Kiểm tra xem giá hiện tại có quá gần các mức key level hay không."""
    logger.debug(f"Bắt đầu hàm _near_key_levels_too_close. Min pips: {min_pips}, Current Price: {cp}")
    try:
        lst = (mt5_ctx.get("key_levels_nearby") or [])
        for lv in lst:
            dist = float(lv.get("distance_pips") or 0.0)
            if dist and dist < float(min_pips):
                logger.debug(f"Giá quá gần key level {lv.get('name')} ({dist} pips).")
                return True
    except Exception as e:
        logger.error(f"Lỗi khi kiểm tra key levels quá gần: {e}")
        pass
    logger.debug("Giá không quá gần bất kỳ key level nào.")
    logger.debug("Kết thúc hàm _near_key_levels_too_close.")
    return False

# Hàm _log_trade_decision đã được di chuyển sang src/utils/logging_utils.py
# và được gọi thông qua app._log_trade_decision hoặc trực tiếp logging_utils.log_trade_decision

def _load_last_trade_state() -> Dict:
    """Tải trạng thái giao dịch cuối cùng từ file."""
    logger.debug("Bắt đầu hàm _load_last_trade_state.")
    f = APP_DIR / "last_trade_state.json"
    try:
        state = json.loads(f.read_text(encoding="utf-8"))
        logger.debug(f"Đã tải last trade state: {state}")
        logger.debug("Kết thúc hàm _load_last_trade_state.")
        return state
    except Exception as e:
        logger.warning(f"Không thể tải last trade state từ {f}: {e}. Trả về rỗng.")
        logger.debug("Kết thúc hàm _load_last_trade_state (lỗi).")
        return {}

def _save_last_trade_state(state: Dict):
    """Lưu trạng thái giao dịch hiện tại vào file."""
    logger.debug(f"Bắt đầu hàm _save_last_trade_state. State: {state}")
    f = APP_DIR / "last_trade_state.json"
    try:
        f.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.debug(f"Đã lưu last trade state vào {f}.")
    except Exception as e:
        logger.error(f"Lỗi khi lưu last trade state vào {f}: {e}")
        pass
    logger.debug("Kết thúc hàm _save_last_trade_state.")

def _order_send_safe(app: "TradingToolApp", req: Dict, retry: int = 2):
    """Gửi lệnh giao dịch an toàn với cơ chế thử lại và kiểm tra kết nối MT5."""
    logger.debug(f"Bắt đầu hàm _order_send_safe. Request: {req}, Retry: {retry}")
    last = None
    # Log account info before sending
    try:
        acc_info = mt5.account_info()
        if acc_info:
            acc_dict = {
                "login": acc_info.login,
                "server": acc_info.server,
                "balance": acc_info.balance,
                "equity": acc_info.equity,
                "profit": acc_info.profit,
            }
            # Gọi hàm _log_trade_decision của app_logic
            app._log_trade_decision({"stage": "send-account-check", "account_info": acc_dict}, folder_override=(app.mt5_symbol_var.get().strip() if hasattr(app, "mt5_symbol_var") else None))
            logger.debug(f"Đã log account info trước khi gửi lệnh: {acc_dict}")
        else:
            app._log_trade_decision({"stage": "send-account-check", "account_info": None, "error": "mt5.account_info() returned None"}, folder_override=(app.mt5_symbol_var.get().strip() if hasattr(app, "mt5_symbol_var") else None))
            logger.warning("Không lấy được account info từ MT5.")
    except Exception as e:
        app._log_trade_decision({"stage": "send-account-check", "error": f"Exception getting account_info: {e}"}, folder_override=(app.mt5_symbol_var.get().strip() if hasattr(app, "mt5_symbol_var") else None))
        logger.error(f"Lỗi khi lấy account info trước khi gửi lệnh: {e}")
    
    if mt5.account_info() is None:
        logger.warning("MT5 account info trống, thử tái kết nối.")
        try:
            # Cố gắng tái kết nối MT5 thông qua app_logic
            ok, msg = app._mt5_connect(app)
            if not ok:
                ui_utils.ui_status(app, f"MT5 Re-init failed: {msg}")
                app._log_trade_decision({"stage": "send-error", "reason": "mt5_reinit_failed", "error": msg}, folder_override=(app.mt5_symbol_var.get().strip() if hasattr(app, "mt5_symbol_var") else None))
                logger.error(f"Tái kết nối MT5 thất bại: {msg}")
                return None
            logger.info("Tái kết nối MT5 thành công.")
        except Exception as e:
            ui_utils.ui_status(app, f"MT5 Re-init exception: {e}")
            app._log_trade_decision({"stage": "send-error", "reason": "mt5_reinit_exception", "error": str(e)}, folder_override=(app.mt5_symbol_var.get().strip() if hasattr(app, "mt5_symbol_var") else None))
            logger.error(f"Lỗi ngoại lệ khi tái kết nối MT5: {e}")
            return None
    
    for i in range(max(1, retry)):
        logger.debug(f"Lần thử gửi lệnh {i+1}/{retry}.")
        try:
            req_log = dict(req)
            if 'expiration' in req_log and hasattr(req_log['expiration'], 'timestamp'):
                req_log['expiration'] = int(req_log['expiration'].timestamp())
            app._log_trade_decision({"stage": "send-request-raw", "request": req_log}, folder_override=(app.mt5_symbol_var.get().strip() if hasattr(app, "mt5_symbol_var") else None))
            logger.debug(f"Đã log raw request: {req_log}")
        except Exception as e:
            logger.warning(f"Lỗi khi log raw request: {e}")
            pass
        
        result = mt5.order_send(req)
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            logger.info(f"Lệnh gửi thành công: {result}")
            return result
        last = result
        logger.warning(f"Lệnh gửi thất bại (lần {i+1}): {result}. Thử lại sau 0.6s.")
        time.sleep(0.6)
    logger.error(f"Tất cả các lần thử gửi lệnh đều thất bại. Kết quả cuối cùng: {last}")
    logger.debug("Kết thúc hàm _order_send_safe (thất bại).")
    return last

def _fill_priority(prefer: str) -> List[int]:
    """Trả về thứ tự ưu tiên các chế độ filling lệnh."""
    logger.debug(f"Bắt đầu hàm _fill_priority cho prefer: {prefer}")
    try:
        IOC = mt5.ORDER_FILLING_IOC
        FOK = mt5.ORDER_FILLING_FOK
        RET = mt5.ORDER_FILLING_RETURN
    except Exception as e:
        logger.warning(f"Không thể lấy ORDER_FILLING constants từ MT5: {e}. Dùng giá trị mặc định.")
        IOC = 1
        FOK = 0
        RET = 2
    result = ([IOC, FOK, RET] if prefer == "market" else [FOK, IOC, RET])
    logger.debug(f"Kết thúc hàm _fill_priority. Priority: {result}")
    return result

def _fill_name(val: int) -> str:
    """Trả về tên của chế độ filling."""
    logger.debug(f"Bắt đầu hàm _fill_name cho value: {val}")
    names = {
        getattr(mt5, "ORDER_FILLING_IOC", 1): "IOC",
        getattr(mt5, "ORDER_FILLING_FOK", 0): "FOK",
        getattr(mt5, "ORDER_FILLING_RETURN", 2): "RETURN",
    }
    result = names.get(val, str(val))
    logger.debug(f"Kết thúc hàm _fill_name. Name: {result}")
    return result

def _order_send_smart(app: "TradingToolApp", req: Dict, prefer: str = "market", retry_per_mode: int = 2):
    """Gửi lệnh thông minh với các chế độ filling khác nhau."""
    logger.debug(f"Bắt đầu hàm _order_send_smart. Prefer: {prefer}, Retry per mode: {retry_per_mode}")
    last_res = None
    tried = []
    for fill in _fill_priority(prefer):
        r = dict(req)
        r["type_filling"] = fill
        res = _order_send_safe(app, r, retry=retry_per_mode)
        tried.append(_fill_name(fill))

        try:
            log_data = {
                "stage": "send-attempt",
                "filling": _fill_name(fill),
                "retcode": getattr(res, "retcode", None),
                "comment": getattr(res, "comment", None),
                "request_id": getattr(res, "request_id", None),
            }
            app._log_trade_decision(log_data, folder_override=(app.mt5_symbol_var.get().strip() if hasattr(app, "mt5_symbol_var") else None))
            logger.debug(f"Đã log send attempt: {log_data}")
        except Exception as e:
            logger.warning(f"Lỗi khi log send attempt: {e}")
            pass

        if res and res.retcode == mt5.TRADE_RETCODE_DONE:
            if len(tried) > 1:
                ui_utils.ui_status(app, f"Order OK sau khi đổi filling → {tried[-1]}.")
                logger.info(f"Order OK sau khi đổi filling → {tried[-1]}.")
            return res

        last_res = res
        logger.warning(f"Order FAIL với filling {tried[-1]}.")

    cmt = getattr(last_res, "comment", "unknown") if last_res else "no result"
    ui_utils.ui_status(app, f"Order FAIL với các filling: {', '.join(tried)} — {cmt}")
    logger.error(f"Tất cả các lần thử gửi lệnh thông minh đều thất bại. Comment: {cmt}")
    logger.debug("Kết thúc hàm _order_send_smart (thất bại).")
    return last_res


def auto_trade_if_high_prob(app: "TradingToolApp", combined_text: str, mt5_ctx: Dict, cfg: "RunConfig") -> bool:
    """
    Place market/pending orders when setup qualifies.
    Returns True if a trade action was successfully taken, False otherwise.
    """
    logger.debug("Bắt đầu hàm auto_trade_if_high_prob.")
    if not cfg.auto_trade_enabled:
        logger.debug("Auto-Trade không được bật.")
        logger.debug("Kết thúc hàm auto_trade_if_high_prob (không được bật).")
        return False
    if not cfg.mt5_enabled or mt5 is None:
        app.ui_status("Auto-Trade: MT5 not enabled or missing.")
        logger.warning("Auto-Trade không thể chạy: MT5 không bật hoặc module MT5 thiếu.")
        logger.debug("Kết thúc hàm auto_trade_if_high_prob (MT5 không được bật).")
        return False

    # NO-TRADE evaluate: hard filters + session + news window
    try:
        ok_nt, reasons_nt, ev, ts, meta = no_run_trade_conditions.evaluate_no_trade_conditions(
            safe_mt5_data=mt5_utils.build_context_from_app(app, plan=None, cfg=cfg), # Cần SafeMT5Data
            cfg=cfg,
            cache_events=getattr(app, "ff_cache_events_local", None),
            cache_fetch_time=getattr(app, "ff_cache_fetch_time", None),
            ttl_sec=int(getattr(cfg, 'news_cache_ttl_sec', 300) or 300),
        )
        logger.debug(f"Kết quả NO-TRADE evaluation: OK={ok_nt}, Reasons={reasons_nt}")
        # Update app-level news cache
        try:
            app.ff_cache_events_local = ev
            app.ff_cache_fetch_time = ts
            logger.debug("Đã cập nhật app-level news cache.")
        except Exception as e:
            logger.warning(f"Lỗi khi cập nhật app-level news cache: {e}")
            pass
        # Persist last NO-TRADE evaluation for UI
        try:
            app.last_no_trade_ok = bool(ok_nt)
            app.last_no_trade_reasons = list(reasons_nt or [])
            # Optionally persist meta for other UI components (non-breaking)
            setattr(app, "last_no_trade_meta", meta)
            logger.debug("Đã persist last NO-TRADE evaluation cho UI.")
        except Exception as e:
            logger.warning(f"Lỗi khi persist last NO-TRADE evaluation: {e}")
            pass
        if not ok_nt:
            app.ui_status("Auto-Trade: NO-TRADE filters blocked.\n- " + "\n- ".join(reasons_nt))
            try:
                app._log_trade_decision({"stage": "precheck-fail", "reason": "no_trade_filters", "reasons_list": reasons_nt}, folder_override=(app.mt5_symbol_var.get().strip() if hasattr(app, "mt5_symbol_var") else None))
            except Exception as e:
                logger.warning(f"Lỗi khi log NO-TRADE precheck-fail: {e}")
                pass
            logger.info("Auto-Trade bị chặn bởi NO-TRADE filters.")
            return False
    except Exception as e:
        logger.error(f"Lỗi trong NO-TRADE evaluation: {e}. Sẽ tiếp tục mà không chặn.")
        # Fail-open: if evaluate crashes, proceed without blocking
        pass

    # --- MODIFIED: Prioritize parsing structured JSON from AI response ---
    setup = {}
    bias = ""
    try:
        ai_json = report_parser.extract_json_block_prefer(combined_text)
        if ai_json and not ai_json.get("error"):
            # Check for a clear "ĐỦ" conclusion from the AI's checklist
            if ai_json.get("conclusions") == "ĐỦ":
                    setup = ai_json.get("proposed_plan", {})
                    bias = str(ai_json.get("bias_H1") or "").lower()
                    app.ui_status("Auto-Trade: Dùng setup từ Vision JSON.")
                    logger.debug("Đã dùng setup từ Vision JSON.")
    except Exception as e:
        logger.warning(f"Lỗi khi parse Vision JSON: {e}. Fallback sang text parsing.")
        pass # Fallback to text parsing if JSON fails

    # Fallback to parsing the 7-line text summary if JSON parsing fails or is inconclusive
    if not setup:
        # If the text is still short, it's likely streaming is not complete.
        # Avoid parsing incomplete text fragments. A threshold of 200 chars is arbitrary
        # but should be enough to contain a full setup block.
        if len(combined_text) < 200:
            logger.debug("Combined text quá ngắn, bỏ qua parsing.")
            logger.debug("Kết thúc hàm auto_trade_if_high_prob (text quá ngắn).")
            return False
        app.ui_status("Auto-Trade: Vision JSON không kết luận, dùng text parsing.")
        logger.debug("Vision JSON không kết luận, dùng text parsing.")
        # MODIFICATION: Call the method from the report_parser module
        setup = report_parser.parse_setup_from_report(combined_text) or {}
        # Bias is not available in the simple text parse, this is a limitation of the old method
        bias = ""

    direction = setup.get("direction")
    entry = setup.get("entry")
    sl = setup.get("sl")
    tp1 = setup.get("tp1")
    tp2 = setup.get("tp2")
    logger.debug(f"Parsed setup: Direction={direction}, Entry={entry}, SL={sl}, TP1={tp1}, TP2={tp2}")
    # Bias is now handled by the new JSON parsing logic above

    # Resolve MT5 context variables
    try:
        sym = (mt5_ctx.get("symbol") if mt5_ctx else None) or (cfg.mt5_symbol or (app.mt5_symbol_var.get().strip() if hasattr(app, "mt5_symbol_var") else ""))
    except Exception as e:
        sym = cfg.mt5_symbol or (app.mt5_symbol_var.get().strip() if hasattr(app, "mt5_symbol_var") else "")
        logger.warning(f"Lỗi khi lấy symbol từ MT5 context/config: {e}. Dùng fallback: {sym}")

    tick = (mt5_ctx.get("tick") if isinstance(mt5_ctx, dict) else {}) or {}
    try:
        ask = float((tick.get("ask") if isinstance(tick, dict) else None) or 0.0)
    except Exception as e:
        ask = 0.0
        logger.warning(f"Lỗi khi lấy ask price: {e}. Dùng fallback: {ask}")
    try:
        bid = float((tick.get("bid") if isinstance(tick, dict) else None) or 0.0)
    except Exception as e:
        bid = 0.0
        logger.warning(f"Lỗi khi lấy bid price: {e}. Dùng fallback: {bid}")
    try:
        cp = float((tick.get("last") if isinstance(tick, dict) else None) or (bid or ask) or 0.0)
    except Exception as e:
        cp = 0.0
        logger.warning(f"Lỗi khi lấy current price: {e}. Dùng fallback: {cp}")
    logger.debug(f"Symbol: {sym}, Ask: {ask}, Bid: {bid}, Current Price: {cp}")

    info_dict = (mt5_ctx.get("info") if isinstance(mt5_ctx, dict) else {}) or {}
    try:
        digits = int((info_dict.get("digits") if isinstance(info_dict, dict) else None) or 5)
    except Exception as e:
        digits = 5
        logger.warning(f"Lỗi khi lấy digits: {e}. Dùng fallback: {digits}")
    try:
        point = float((info_dict.get("point") if isinstance(info_dict, dict) else None) or 0.0)
    except Exception as e:
        point = 0.0
        logger.warning(f"Lỗi khi lấy point: {e}. Dùng fallback: {point}")
    logger.debug(f"Digits: {digits}, Point: {point}")

    info = None
    acc = None
    if mt5 is not None and sym:
        try:
            info = mt5.symbol_info(sym)
        except Exception as e:
            info = None
            logger.warning(f"Lỗi khi lấy symbol_info cho {sym}: {e}")
        try:
            acc = mt5.account_info()
        except Exception as e:
            acc = None
            logger.warning(f"Lỗi khi lấy account_info: {e}")
    if not point and info is not None:
        try:
            point = float(getattr(info, "point", 0.0) or 0.0)
        except Exception as e:
            logger.warning(f"Lỗi khi lấy point từ info object: {e}")
            pass
    if not digits and info is not None:
        try:
            digits = int(getattr(info, "digits", 5) or 5)
        except Exception as e:
            logger.warning(f"Lỗi khi lấy digits từ info object: {e}")
            pass
    logger.debug(f"Symbol info: {info}, Account info: {acc}")

    if direction not in ("long", "short"):
        logger.debug("Hướng lệnh không hợp lệ hoặc chưa có, bỏ qua.")
        # This is a common case when the stream is still in progress, so we don't log it as a failure.
        # ui_utils.ui_status(app, "Auto-Trade: missing direction.")
        logger.debug("Kết thúc hàm auto_trade_if_high_prob (thiếu hướng).")
        return False

    if cfg.trade_strict_bias:
        if (bias == "bullish" and direction == "short") or (bias == "bearish" and direction == "long"):
            app.ui_status("Auto-Trade: opposite to H1 bias.")
            try:
                app._log_trade_decision({"stage": "precheck-fail", "reason": "opposite_bias_h1", "bias_h1": bias, "dir": direction}, folder_override=(app.mt5_symbol_var.get().strip() if hasattr(app, "mt5_symbol_var") else None))
            except Exception as e:
                logger.warning(f"Lỗi khi log opposite_bias_h1 precheck-fail: {e}")
                pass
            logger.info("Auto-Trade bị chặn: ngược bias H1.")
            return False

    rr2 = _calc_rr(entry, sl, tp2)
    if rr2 is not None and rr2 < float(cfg.trade_min_rr_tp2):
        app.ui_status(f"Auto-Trade: RR TP2 {rr2:.2f} < min.")
        try:
            app._log_trade_decision({"stage": "precheck-fail", "reason": "rr_below_min", "sym": sym, "dir": direction, "entry": entry, "sl": sl, "tp2": tp2, "rr_tp2": rr2, "min_rr": float(cfg.trade_min_rr_tp2)}, folder_override=(app.mt5_symbol_var.get().strip() if hasattr(app, "mt5_symbol_var") else None))
        except Exception as e:
            logger.warning(f"Lỗi khi log rr_below_min precheck-fail: {e}")
            pass
        logger.info(f"Auto-Trade bị chặn: RR TP2 ({rr2:.2f}) dưới mức tối thiểu ({cfg.trade_min_rr_tp2}).")
        return False

    cp0 = cp or ((ask + bid) / 2.0)
    try:
        too_close = _near_key_levels_too_close(mt5_ctx, float(cfg.trade_min_dist_keylvl_pips), cp0)
    except Exception as e:
        too_close = False
        logger.error(f"Lỗi khi kiểm tra _near_key_levels_too_close: {e}")
    if mt5_ctx and too_close:
        app.ui_status("Auto-Trade: too close to key level.")
        try:
            app._log_trade_decision({"stage": "precheck-fail", "reason": "near_key_level", "sym": sym, "dir": direction, "cp": cp0, "min_dist_pips": float(cfg.trade_min_dist_keylvl_pips)}, folder_override=(app.mt5_symbol_var.get().strip() if hasattr(app, "mt5_symbol_var") else None))
        except Exception as e:
            logger.warning(f"Lỗi khi log near_key_level precheck-fail: {e}")
            pass
        logger.info("Auto-Trade bị chặn: quá gần key level.")
        return False

    setup_sig = hashlib.sha1(f"{sym}|{direction}|{round(entry or 0,5)}|{round(sl or 0,5)}|{round(tp1 or 0,5)}|{round(tp2 or 0,5)}".encode("utf-8")).hexdigest()
    state = _load_last_trade_state()
    last_sig = (state.get("sig") or "") if isinstance(state, dict) else ""
    last_ts = float((state.get("time") if isinstance(state, dict) else 0.0) or 0.0)
    cool_s = int(cfg.trade_cooldown_min) * 60
    now_ts = time.time()
    if last_sig == setup_sig and (now_ts - last_ts) < cool_s:
        app.ui_status("Auto-Trade: duplicate setup, cooldown active.")
        try:
            app._log_trade_decision({"stage": "precheck-fail", "reason": "duplicate_setup", "sym": sym, "dir": direction, "setup_sig": setup_sig, "last_sig": last_sig, "elapsed_s": (now_ts - last_ts), "cooldown_s": cool_s}, folder_override=(app.mt5_symbol_var.get().strip() if hasattr(app, "mt5_symbol_var") else None))
        except Exception as e:
            logger.warning(f"Lỗi khi log duplicate_setup precheck-fail: {e}")
            pass
        logger.info("Auto-Trade bị chặn: setup trùng lặp, cooldown active.")
        return False

    pending_thr = int(cfg.trade_pending_threshold_points)
    try:
        atr = (((mt5_ctx.get("volatility") or {}).get("ATR") or {}).get("M5"))
        pt = float(((mt5_ctx.get("info") or {}).get("point")) or 0.0)
        if atr and pt and cfg.trade_dynamic_pending:
            atr_pts = atr / pt
            pending_thr = max(pending_thr, int(atr_pts * 0.25))
        logger.debug(f"Pending threshold: {pending_thr} (dynamic: {cfg.trade_dynamic_pending})")
    except Exception as e:
        logger.error(f"Lỗi khi tính pending threshold: {e}")
        pass

    lots_total = None
    mode = cfg.trade_size_mode
    if mode == "lots":
        lots_total = float(cfg.trade_lots_total)
        logger.debug(f"Lots total (fixed): {lots_total}")
    else:
        dist_points = abs((entry or 0) - (sl or 0)) / (point or 1)
        if dist_points <= 0:
            app.ui_status("Auto-Trade: zero SL distance.")
            try:
                app._log_trade_decision({"stage": "precheck-fail", "reason": "sl_zero", "sym": sym, "dir": direction, "entry": entry, "sl": sl, "point": point}, folder_override=(app.mt5_symbol_var.get().strip() if hasattr(app, "mt5_symbol_var") else None))
            except Exception as e:
                logger.warning(f"Lỗi khi log sl_zero precheck-fail: {e}")
                pass
            logger.info("Auto-Trade bị chặn: khoảng cách SL bằng 0.")
            return False
        value_per_point = (mt5_utils.value_per_point(sym, info) or 0.0)
        if value_per_point <= 0:
            app.ui_status("Auto-Trade: cannot determine value per point.")
            try:
                app._log_trade_decision({"stage": "precheck-fail", "reason": "no_value_per_point", "sym": sym, "dir": direction}, folder_override=(app.mt5_symbol_var.get().strip() if hasattr(app, "mt5_symbol_var") else None))
            except Exception as e:
                logger.warning(f"Lỗi khi log no_value_per_point precheck-fail: {e}")
                pass
            logger.info("Auto-Trade bị chặn: không xác định được giá trị mỗi điểm.")
            return False
        if mode == "percent":
            equity = float(getattr(acc, "equity", 0.0))
            risk_money = equity * float(cfg.trade_equity_risk_pct) / 100.0
            logger.debug(f"Risk money (% equity): {risk_money}")
        else:
            risk_money = float(cfg.trade_money_risk)
            logger.debug(f"Risk money (fixed): {risk_money}")
        if not risk_money or risk_money <= 0:
            app.ui_status("Auto-Trade: invalid risk.")
            try:
                app._log_trade_decision({"stage": "precheck-fail", "reason": "invalid_risk", "sym": sym, "dir": direction, "mode": mode, "equity": float(getattr(acc, "equity", 0.0))}, folder_override=(app.mt5_symbol_var.get().strip() if hasattr(app, "mt5_symbol_var") else None))
            except Exception as e:
                logger.warning(f"Lỗi khi log invalid_risk precheck-fail: {e}")
                pass
            logger.info("Auto-Trade bị chặn: rủi ro không hợp lệ.")
            return False
        lots_total = risk_money / (dist_points * value_per_point)
        logger.debug(f"Lots total (calculated): {lots_total}")

    vol_min = getattr(info, "volume_min", 0.01) or 0.01
    vol_max = getattr(info, "volume_max", 100.0) or 100.0
    vol_step = getattr(info, "volume_step", 0.01) or 0.01
    logger.debug(f"Volume min: {vol_min}, max: {vol_max}, step: {vol_step}")

    def _round_step(v: float) -> float:
        k = round(v / vol_step)
        return max(vol_min, min(vol_max, k * vol_step))

    lots_total = _round_step(float(lots_total or 0.0))
    split1 = max(1, min(99, int(cfg.trade_split_tp1_pct))) / 100.0
    vol1 = _round_step(lots_total * split1)
    vol2 = _round_step(lots_total - vol1)
    if vol1 < vol_min or vol2 < vol_min:
        app.ui_status("Auto-Trade: volume too small after split.")
        try:
            app._log_trade_decision({"stage": "precheck-fail", "reason": "volume_too_small_after_split", "sym": sym, "dir": direction, "lots_total": lots_total, "vol1": vol1, "vol2": vol2, "vol_min": vol_min}, folder_override=(app.mt5_symbol_var.get().strip() if hasattr(app, "mt5_symbol_var") else None))
        except Exception as e:
            logger.warning(f"Lỗi khi log volume_too_small_after_split precheck-fail: {e}")
            pass
        logger.info("Auto-Trade bị chặn: khối lượng quá nhỏ sau khi chia.")
        return False

    deviation = int(cfg.trade_deviation_points)
    magic = int(cfg.trade_magic)
    comment_prefix = (cfg.trade_comment_prefix or "AI-ICT").strip()
    logger.debug(f"Deviation: {deviation}, Magic: {magic}, Comment prefix: {comment_prefix}")

    dist_to_entry_pts = abs((entry or 0) - (cp or 0)) / (point or 1)
    use_pending = dist_to_entry_pts >= pending_thr
    if use_pending and dist_to_entry_pts <= deviation:
        use_pending = False
    logger.debug(f"Distance to entry: {dist_to_entry_pts}, Use pending: {use_pending}")

    exp_time = datetime.now() + timedelta(minutes=int(cfg.trade_pending_ttl_min))
    log_base = {
        "t": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "sym": sym, "dir": direction, "entry": entry, "sl": sl, "tp1": tp1, "tp2": tp2,
        "lots_total": lots_total, "vol1": vol1, "vol2": vol2,
        "rr_tp2": rr2, "use_pending": use_pending, "pending_thr": pending_thr,
        "cooldown_s": cool_s, "deviation": deviation, "magic": magic,
        "dry_run": bool(cfg.auto_trade_dry_run),
    }
    try:
        app._log_trade_decision({**log_base, "stage": "pre-check"}, folder_override=(app.mt5_symbol_var.get().strip() if hasattr(app, "mt5_symbol_var") else None))
        logger.debug("Đã log pre-check decision.")
    except Exception as e:
        logger.warning(f"Lỗi khi log pre-check decision: {e}")
        pass

    if cfg.auto_trade_dry_run:
        app.ui_status("Auto-Trade: DRY-RUN - logging only.")
        _save_last_trade_state({"sig": setup_sig, "time": time.time()})
        logger.info("Auto-Trade: DRY-RUN, không gửi lệnh.")
        return True

    if use_pending:
        if direction == "long":
            otype = mt5.ORDER_TYPE_BUY_LIMIT if (entry or 0) < (cp or 0) else mt5.ORDER_TYPE_BUY_STOP
        else:
            otype = mt5.ORDER_TYPE_SELL_LIMIT if (entry or 0) > (cp or 0) else mt5.ORDER_TYPE_SELL_STOP
        common = dict(action=mt5.TRADE_ACTION_PENDING, symbol=sym, type=otype, price=round(entry or 0, digits), sl=round(sl or 0, digits), deviation=deviation, magic=magic, type_time=mt5.ORDER_TIME_SPECIFIED, expiration=exp_time)
        reqs = [
            dict(**common, volume=vol1, tp=round(tp1 or 0, digits), comment=f"{comment_prefix}-TP1"),
            dict(**common, volume=vol2, tp=round(tp2 or 0, digits), comment=f"{comment_prefix}-TP2"),
        ]
        logger.debug(f"Đã tạo {len(reqs)} pending order requests.")
    else:
        if direction == "long":
            otype = mt5.ORDER_TYPE_BUY
            px = round(ask or 0, digits)
        else:
            otype = mt5.ORDER_TYPE_SELL
            px = round(bid or 0, digits)
        common = dict(action=mt5.TRADE_ACTION_DEAL, symbol=sym, type=otype, price=px, sl=round(sl or 0, digits), deviation=deviation, magic=magic, type_time=mt5.ORDER_TIME_GTC)
        reqs = [
            dict(**common, volume=vol1, tp=round(tp1 or 0, digits), comment=f"{comment_prefix}-TP1"),
            dict(**common, volume=vol2, tp=round(tp2 or 0, digits), comment=f"{comment_prefix}-TP2"),
        ]
        logger.debug(f"Đã tạo {len(reqs)} market order requests.")

    errs = []
    for req in reqs:
        prefer = "pending" if req.get("action") == mt5.TRADE_ACTION_PENDING else "market"
        res = _order_send_smart(app, req, prefer=prefer, retry_per_mode=2)
        if not res or res.retcode != mt5.TRADE_RETCODE_DONE:
            errs.append(f"Result: {res}")
            logger.error(f"Lỗi khi gửi lệnh: {res}")

    if errs:
        app.ui_status("Auto-Trade: order errors: " + "; ".join(errs))
        try:
            app._log_trade_decision({**log_base, "stage": "send", "errors": errs}, folder_override=(app.mt5_symbol_var.get().strip() if hasattr(app, "mt5_symbol_var") else None))
        except Exception as e:
            logger.warning(f"Lỗi khi log send errors: {e}")
            pass
        logger.info("Auto-Trade: có lỗi khi gửi lệnh.")
        logger.debug("Kết thúc hàm auto_trade_if_high_prob (lỗi gửi lệnh).")
        return False
    else:
        _save_last_trade_state({"sig": setup_sig, "time": time.time()})
        try:
            app._log_trade_decision({**log_base, "stage": "send", "ok": True}, folder_override=(app.mt5_symbol_var.get().strip() if hasattr(app, "mt5_symbol_var") else None))
        except Exception as e:
            logger.warning(f"Lỗi khi log successful send: {e}")
            pass
        app.ui_status("Auto-Trade: placed TP1/TP2 orders.")
        logger.info("Auto-Trade: đã đặt lệnh TP1/TP2 thành công.")
        logger.debug("Kết thúc hàm auto_trade_if_high_prob (thành công).")
        return True
