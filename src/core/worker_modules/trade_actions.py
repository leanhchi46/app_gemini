from __future__ import annotations

import hashlib
import time
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, List, Dict, Any, Optional, Tuple

try:
    import MetaTrader5 as mt5  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    mt5 = None  # type: ignore

from src.config.constants import APP_DIR
from src.utils import mt5_utils
from src.core import no_trade # Cần cho no_trade.evaluate
from src.utils import report_parser, ui_utils

if TYPE_CHECKING:
    from scripts.tool import TradingToolApp
    from src.config.config import RunConfig
    from src.utils.safe_data import SafeMT5Data


def _calc_rr(entry: Optional[float], sl: Optional[float], tp: Optional[float]) -> Optional[float]:
    """Tính toán tỷ lệ rủi ro/lợi nhuận."""
    try:
        risk = abs((entry or 0) - (sl or 0))
        reward = abs((tp or 0) - (entry or 0))
        return (reward / risk) if risk > 0 else None
    except Exception:
        return None

def _near_key_levels_too_close(mt5_ctx: Dict, min_pips: float, cp: float) -> bool:
    """Kiểm tra xem giá hiện tại có quá gần các mức key level hay không."""
    try:
        lst = (mt5_ctx.get("key_levels_nearby") or [])
        for lv in lst:
            dist = float(lv.get("distance_pips") or 0.0)
            if dist and dist < float(min_pips):
                return True
    except Exception:
        pass
    return False

def _log_trade_decision(app: "TradingToolApp", data: Dict, folder_override: Optional[str] = None):
    """Ghi lại các quyết định giao dịch vào file log JSONL."""
    try:
        # Sử dụng phương thức _get_reports_dir từ app_logic
        d = app._get_reports_dir(folder_override=folder_override)
        if not d:
            return

        p = d / f"trade_log_{datetime.now().strftime('%Y%m%d')}.jsonl"
        line = (json.dumps(data, ensure_ascii=False, separators=(',', ':')) + "\n").encode("utf-8")

        p.parent.mkdir(parents=True, exist_ok=True)

        with app._trade_log_lock: # Sử dụng lock từ app_logic
            need_leading_newline = False
            if p.exists():
                try:
                    sz = p.stat().st_size
                    if sz > 0:
                        with open(p, "rb") as fr:
                            fr.seek(-1, os.SEEK_END)
                            need_leading_newline = (fr.read(1) != b"\n")
                except Exception:
                    need_leading_newline = False

            with open(p, "ab") as f:
                if need_leading_newline:
                    f.write(b"\n")
                f.write(line)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except Exception:
                    pass
    except Exception:
        pass

def _load_last_trade_state() -> Dict:
    """Tải trạng thái giao dịch cuối cùng từ file."""
    f = APP_DIR / "last_trade_state.json"
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return {}

def _save_last_trade_state(state: Dict):
    """Lưu trạng thái giao dịch hiện tại vào file."""
    f = APP_DIR / "last_trade_state.json"
    try:
        f.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

def _order_send_safe(app: "TradingToolApp", req: Dict, retry: int = 2):
    """Gửi lệnh giao dịch an toàn với cơ chế thử lại và kiểm tra kết nối MT5."""
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
            _log_trade_decision(app, {"stage": "send-account-check", "account_info": acc_dict}, folder_override=(app.mt5_symbol_var.get().strip() if hasattr(app, "mt5_symbol_var") else None))
        else:
            _log_trade_decision(app, {"stage": "send-account-check", "account_info": None, "error": "mt5.account_info() returned None"}, folder_override=(app.mt5_symbol_var.get().strip() if hasattr(app, "mt5_symbol_var") else None))
    except Exception as e:
        _log_trade_decision(app, {"stage": "send-account-check", "error": f"Exception getting account_info: {e}"}, folder_override=(app.mt5_symbol_var.get().strip() if hasattr(app, "mt5_symbol_var") else None))
    
    if mt5.account_info() is None:
        try:
            # Cố gắng tái kết nối MT5 thông qua app_logic
            ok, msg = app._mt5_connect(app)
            if not ok:
                ui_utils.ui_status(app, f"MT5 Re-init failed: {msg}")
                _log_trade_decision(app, {"stage": "send-error", "reason": "mt5_reinit_failed", "error": msg}, folder_override=(app.mt5_symbol_var.get().strip() if hasattr(app, "mt5_symbol_var") else None))
                return None
        except Exception as e:
            ui_utils.ui_status(app, f"MT5 Re-init exception: {e}")
            _log_trade_decision(app, {"stage": "send-error", "reason": "mt5_reinit_exception", "error": str(e)}, folder_override=(app.mt5_symbol_var.get().strip() if hasattr(app, "mt5_symbol_var") else None))
            return None
    
    for i in range(max(1, retry)):
        try:
            req_log = dict(req)
            if 'expiration' in req_log and hasattr(req_log['expiration'], 'timestamp'):
                req_log['expiration'] = int(req_log['expiration'].timestamp())
            _log_trade_decision(app, {"stage": "send-request-raw", "request": req_log}, folder_override=(app.mt5_symbol_var.get().strip() if hasattr(app, "mt5_symbol_var") else None))
        except Exception:
            pass
        
        result = mt5.order_send(req)
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            return result
        last = result
        time.sleep(0.6)
    return last

def _fill_priority(prefer: str) -> List[int]:
    """Trả về thứ tự ưu tiên các chế độ filling lệnh."""
    try:
        IOC = mt5.ORDER_FILLING_IOC
        FOK = mt5.ORDER_FILLING_FOK
        RET = mt5.ORDER_FILLING_RETURN
    except Exception:
        IOC = 1; FOK = 0; RET = 2
    return ([IOC, FOK, RET] if prefer == "market" else [FOK, IOC, RET])

def _fill_name(val: int) -> str:
    """Trả về tên của chế độ filling."""
    names = {
        getattr(mt5, "ORDER_FILLING_IOC", 1): "IOC",
        getattr(mt5, "ORDER_FILLING_FOK", 0): "FOK",
        getattr(mt5, "ORDER_FILLING_RETURN", 2): "RETURN",
    }
    return names.get(val, str(val))

def _order_send_smart(app: "TradingToolApp", req: Dict, prefer: str = "market", retry_per_mode: int = 2):
    """Gửi lệnh thông minh với các chế độ filling khác nhau."""
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
            _log_trade_decision(app, log_data, folder_override=(app.mt5_symbol_var.get().strip() if hasattr(app, "mt5_symbol_var") else None))
        except Exception:
            pass

        if res and res.retcode == mt5.TRADE_RETCODE_DONE:
            if len(tried) > 1:
                ui_utils.ui_status(app, f"Order OK sau khi đổi filling → {tried[-1]}.")
            return res

        last_res = res

    cmt = getattr(last_res, "comment", "unknown") if last_res else "no result"
    ui_utils.ui_status(app, f"Order FAIL với các filling: {', '.join(tried)} — {cmt}")
    return last_res


def auto_trade_if_high_prob(app: "TradingToolApp", combined_text: str, mt5_ctx: Dict, cfg: "RunConfig") -> bool:
    """
    Place market/pending orders when setup qualifies.
    Returns True if a trade action was successfully taken, False otherwise.
    """
    if not cfg.auto_trade_enabled:
        return False
    if not cfg.mt5_enabled or mt5 is None:
        app.ui_status("Auto-Trade: MT5 not enabled or missing.")
        return False

    # NO-TRADE evaluate: hard filters + session + news window
    try:
        ok_nt, reasons_nt, ev, ts, meta = no_trade.evaluate(
            mt5_ctx or {},
            cfg,
            cache_events=getattr(app, "ff_cache_events_local", None),
            cache_fetch_time=getattr(app, "ff_cache_fetch_time", None),
            ttl_sec=int(getattr(cfg, 'news_cache_ttl_sec', 300) or 300),
        )
        # Update app-level news cache
        try:
            app.ff_cache_events_local = ev
            app.ff_cache_fetch_time = ts
        except Exception:
            pass
        # Persist last NO-TRADE evaluation for UI
        try:
            app.last_no_trade_ok = bool(ok_nt)
            app.last_no_trade_reasons = list(reasons_nt or [])
            # Optionally persist meta for other UI components (non-breaking)
            setattr(app, "last_no_trade_meta", meta)
        except Exception:
            pass
        if not ok_nt:
            app.ui_status("Auto-Trade: NO-TRADE filters blocked.\n- " + "\n- ".join(reasons_nt))
            try:
                _log_trade_decision(app, {"stage": "precheck-fail", "reason": "opposite_bias_h1", "bias_h1": "", "dir": ""}, folder_override=(app.mt5_symbol_var.get().strip() if hasattr(app, "mt5_symbol_var") else None))
            except Exception:
                pass
            return False
    except Exception:
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
    except Exception:
        pass # Fallback to text parsing if JSON fails

    # Fallback to parsing the 7-line text summary if JSON parsing fails or is inconclusive
    if not setup:
        # If the text is still short, it's likely streaming is not complete.
        # Avoid parsing incomplete text fragments. A threshold of 200 chars is arbitrary
        # but should be enough to contain a full setup block.
        if len(combined_text) < 200:
            return False
        app.ui_status("Auto-Trade: Vision JSON không kết luận, dùng text parsing.")
        # MODIFICATION: Call the method from the report_parser module
        setup = report_parser.parse_setup_from_report(combined_text) or {}
        # Bias is not available in the simple text parse, this is a limitation of the old method
        bias = ""

    direction = setup.get("direction")
    entry = setup.get("entry")
    sl = setup.get("sl")
    tp1 = setup.get("tp1")
    tp2 = setup.get("tp2")
    # Bias is now handled by the new JSON parsing logic above

    # Resolve MT5 context variables
    try:
        sym = (mt5_ctx.get("symbol") if mt5_ctx else None) or (cfg.mt5_symbol or (app.mt5_symbol_var.get().strip() if hasattr(app, "mt5_symbol_var") else ""))
    except Exception:
        sym = cfg.mt5_symbol or (app.mt5_symbol_var.get().strip() if hasattr(app, "mt5_symbol_var") else "")

    tick = (mt5_ctx.get("tick") if isinstance(mt5_ctx, dict) else {}) or {}
    try:
        ask = float((tick.get("ask") if isinstance(tick, dict) else None) or 0.0)
    except Exception:
        ask = 0.0
    try:
        bid = float((tick.get("bid") if isinstance(tick, dict) else None) or 0.0)
    except Exception:
        bid = 0.0
    try:
        cp = float((tick.get("last") if isinstance(tick, dict) else None) or (bid or ask) or 0.0)
    except Exception:
        cp = 0.0

    info_dict = (mt5_ctx.get("info") if isinstance(mt5_ctx, dict) else {}) or {}
    try:
        digits = int((info_dict.get("digits") if isinstance(info_dict, dict) else None) or 5)
    except Exception:
        digits = 5
    try:
        point = float((info_dict.get("point") if isinstance(info_dict, dict) else None) or 0.0)
    except Exception:
        point = 0.0

    info = None
    acc = None
    if mt5 is not None and sym:
        try:
            info = mt5.symbol_info(sym)
        except Exception:
            info = None
        try:
            acc = mt5.account_info()
        except Exception:
            acc = None
    if not point and info is not None:
        try:
            point = float(getattr(info, "point", 0.0) or 0.0)
        except Exception:
            pass
    if not digits and info is not None:
        try:
            digits = int(getattr(info, "digits", 5) or 5)
        except Exception:
            pass

    if direction not in ("long", "short"):
        # This is a common case when the stream is still in progress, so we don't log it as a failure.
        # ui_utils.ui_status(app, "Auto-Trade: missing direction.")
        return False

    if cfg.trade_strict_bias:
        if (bias == "bullish" and direction == "short") or (bias == "bearish" and direction == "long"):
            app.ui_status("Auto-Trade: opposite to H1 bias.")
            try:
                _log_trade_decision(app, {"stage": "precheck-fail", "reason": "opposite_bias_h1", "bias_h1": bias, "dir": direction}, folder_override=(app.mt5_symbol_var.get().strip() if hasattr(app, "mt5_symbol_var") else None))
            except Exception:
                pass
            return False

    rr2 = _calc_rr(entry, sl, tp2)
    if rr2 is not None and rr2 < float(cfg.trade_min_rr_tp2):
        app.ui_status(f"Auto-Trade: RR TP2 {rr2:.2f} < min.")
        try:
            _log_trade_decision(app, {"stage": "precheck-fail", "reason": "rr_below_min", "sym": sym, "dir": direction, "entry": entry, "sl": sl, "tp2": tp2, "rr_tp2": rr2, "min_rr": float(cfg.trade_min_rr_tp2)}, folder_override=(app.mt5_symbol_var.get().strip() if hasattr(app, "mt5_symbol_var") else None))
        except Exception:
            pass
        return False

    cp0 = cp or ((ask + bid) / 2.0)
    try:
        too_close = _near_key_levels_too_close(mt5_ctx, float(cfg.trade_min_dist_keylvl_pips), cp0)
    except Exception:
        too_close = False
    if mt5_ctx and too_close:
        app.ui_status("Auto-Trade: too close to key level.")
        try:
            _log_trade_decision(app, {"stage": "precheck-fail", "reason": "near_key_level", "sym": sym, "dir": direction, "cp": cp0, "min_dist_pips": float(cfg.trade_min_dist_keylvl_pips)}, folder_override=(app.mt5_symbol_var.get().strip() if hasattr(app, "mt5_symbol_var") else None))
        except Exception:
            pass
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
            _log_trade_decision(app, {"stage": "precheck-fail", "reason": "duplicate_setup", "sym": sym, "dir": direction, "setup_sig": setup_sig, "last_sig": last_sig, "elapsed_s": (now_ts - last_ts), "cooldown_s": cool_s}, folder_override=(app.mt5_symbol_var.get().strip() if hasattr(app, "mt5_symbol_var") else None))
        except Exception:
            pass
        return False

    pending_thr = int(cfg.trade_pending_threshold_points)
    try:
        atr = (((mt5_ctx.get("volatility") or {}).get("ATR") or {}).get("M5"))
        pt = float(((mt5_ctx.get("info") or {}).get("point")) or 0.0)
        if atr and pt and cfg.trade_dynamic_pending:
            atr_pts = atr / pt
            pending_thr = max(pending_thr, int(atr_pts * 0.25))
    except Exception:
        pass

    lots_total = None
    mode = cfg.trade_size_mode
    if mode == "lots":
        lots_total = float(cfg.trade_lots_total)
    else:
        dist_points = abs((entry or 0) - (sl or 0)) / (point or 1)
        if dist_points <= 0:
            app.ui_status("Auto-Trade: zero SL distance.")
            try:
                _log_trade_decision(app, {"stage": "precheck-fail", "reason": "sl_zero", "sym": sym, "dir": direction, "entry": entry, "sl": sl, "point": point}, folder_override=(app.mt5_symbol_var.get().strip() if hasattr(app, "mt5_symbol_var") else None))
            except Exception:
                pass
            return False
        value_per_point = (mt5_utils.value_per_point(sym, info) or 0.0)
        if value_per_point <= 0:
            app.ui_status("Auto-Trade: cannot determine value per point.")
            try:
                _log_trade_decision(app, {"stage": "precheck-fail", "reason": "no_value_per_point", "sym": sym, "dir": direction}, folder_override=(app.mt5_symbol_var.get().strip() if hasattr(app, "mt5_symbol_var") else None))
            except Exception:
                pass
            return False
        if mode == "percent":
            equity = float(getattr(acc, "equity", 0.0))
            risk_money = equity * float(cfg.trade_equity_risk_pct) / 100.0
        else:
            risk_money = float(cfg.trade_money_risk)
        if not risk_money or risk_money <= 0:
            app.ui_status("Auto-Trade: invalid risk.")
            try:
                _log_trade_decision(app, {"stage": "precheck-fail", "reason": "invalid_risk", "sym": sym, "dir": direction, "mode": mode, "equity": float(getattr(acc, "equity", 0.0))}, folder_override=(app.mt5_symbol_var.get().strip() if hasattr(app, "mt5_symbol_var") else None))
            except Exception:
                pass
            return False
        lots_total = risk_money / (dist_points * value_per_point)

    vol_min = getattr(info, "volume_min", 0.01) or 0.01
    vol_max = getattr(info, "volume_max", 100.0) or 100.0
    vol_step = getattr(info, "volume_step", 0.01) or 0.01

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
            _log_trade_decision(app, {"stage": "precheck-fail", "reason": "volume_too_small_after_split", "sym": sym, "dir": direction, "lots_total": lots_total, "vol1": vol1, "vol2": vol2, "vol_min": vol_min}, folder_override=(app.mt5_symbol_var.get().strip() if hasattr(app, "mt5_symbol_var") else None))
        except Exception:
            pass
        return False

    deviation = int(cfg.trade_deviation_points)
    magic = int(cfg.trade_magic)
    comment_prefix = (cfg.trade_comment_prefix or "AI-ICT").strip()

    dist_to_entry_pts = abs((entry or 0) - (cp or 0)) / (point or 1)
    use_pending = dist_to_entry_pts >= pending_thr
    if use_pending and dist_to_entry_pts <= deviation:
        use_pending = False

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
        _log_trade_decision(app, {**log_base, "stage": "pre-check"}, folder_override=(app.mt5_symbol_var.get().strip() if hasattr(app, "mt5_symbol_var") else None))
    except Exception:
        pass

    if cfg.auto_trade_dry_run:
        app.ui_status("Auto-Trade: DRY-RUN - logging only.")
        _save_last_trade_state({"sig": setup_sig, "time": time.time()})
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

    errs = []
    for req in reqs:
        prefer = "pending" if req.get("action") == mt5.TRADE_ACTION_PENDING else "market"
        res = _order_send_smart(app, req, prefer=prefer, retry_per_mode=2)
        if not res or res.retcode != mt5.TRADE_RETCODE_DONE:
            errs.append(f"Result: {res}")

    if errs:
        app.ui_status("Auto-Trade: order errors: " + "; ".join(errs))
        try:
            _log_trade_decision(app, {**log_base, "stage": "send", "errors": errs}, folder_override=(app.mt5_symbol_var.get().strip() if hasattr(app, "mt5_symbol_var") else None))
        except Exception:
            pass
        return False
    else:
        _save_last_trade_state({"sig": setup_sig, "time": time.time()})
        try:
            _log_trade_decision(app, {**log_base, "stage": "send", "ok": True}, folder_override=(app.mt5_symbol_var.get().strip() if hasattr(app, "mt5_symbol_var") else None))
        except Exception:
            pass
        app.ui_status("Auto-Trade: placed TP1/TP2 orders.")
        return True
