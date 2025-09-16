from __future__ import annotations

import hashlib
import time
from datetime import datetime, timedelta

try:
    import MetaTrader5 as mt5  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    mt5 = None  # type: ignore

from .config import RunConfig
from . import mt5_utils
from . import no_trade


def auto_trade_if_high_prob(app, combined_text: str, mt5_ctx: dict, cfg: RunConfig):
    """Place market/pending orders when setup qualifies (behavior unchanged).

    Delegates UI/logging/helpers to `app` where needed.
    """
    if not cfg.auto_trade_enabled:
        return
    if not cfg.mt5_enabled or mt5 is None:
        app.ui_status("Auto-Trade: MT5 not enabled or missing.")
        return

    # NO-TRADE evaluate: hard filters + session + news window
    try:
        ok_nt, reasons_nt, ev, ts = no_trade.evaluate(
            mt5_ctx or {},
            cfg,
            cache_events=getattr(app, "ff_cache_events_local", None),
            cache_fetch_time=getattr(app, "ff_cache_fetch_time", None),
            ttl_sec=300,
        )
        # Update app-level news cache
        try:
            app.ff_cache_events_local = ev
            app.ff_cache_fetch_time = ts
        except Exception:
            pass
        if not ok_nt:
            app.ui_status("Auto-Trade: NO-TRADE filters blocked.\n- " + "\n- ".join(reasons_nt))
            try:
                app._log_trade_decision(
                    {"stage": "no-trade", "reasons": reasons_nt},
                    folder_override=(app.mt5_symbol_var.get().strip() if hasattr(app, "mt5_symbol_var") else None),
                )
            except Exception:
                pass
            return
    except Exception:
        # Fail-open: if evaluate crashes, proceed without blocking
        pass

    setup = app._parse_setup_from_report(combined_text)
    direction = setup.get("direction")
    entry = setup.get("entry")
    sl = setup.get("sl")
    tp1 = setup.get("tp1")
    tp2 = setup.get("tp2")
    bias = str(setup.get("bias_h1") or "").lower()

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
        app.ui_status("Auto-Trade: missing direction.")
        try:
            app._log_trade_decision({"stage": "precheck-fail", "reason": "no_setup"}, folder_override=(app.mt5_symbol_var.get().strip() if hasattr(app, "mt5_symbol_var") else None))
        except Exception:
            pass
        return

    if cfg.trade_strict_bias:
        if (bias == "bullish" and direction == "short") or (bias == "bearish" and direction == "long"):
            app.ui_status("Auto-Trade: opposite to H1 bias.")
            try:
                app._log_trade_decision({"stage": "precheck-fail", "reason": "opposite_bias_h1", "bias_h1": bias, "dir": direction}, folder_override=(app.mt5_symbol_var.get().strip() if hasattr(app, "mt5_symbol_var") else None))
            except Exception:
                pass
            return

    rr2 = app._calc_rr(entry, sl, tp2)
    if rr2 is not None and rr2 < float(cfg.trade_min_rr_tp2):
        app.ui_status(f"Auto-Trade: RR TP2 {rr2:.2f} < min.")
        try:
            app._log_trade_decision({"stage": "precheck-fail", "reason": "rr_below_min", "sym": sym, "dir": direction, "entry": entry, "sl": sl, "tp2": tp2, "rr_tp2": rr2, "min_rr": float(cfg.trade_min_rr_tp2)}, folder_override=(app.mt5_symbol_var.get().strip() if hasattr(app, "mt5_symbol_var") else None))
        except Exception:
            pass
        return

    cp0 = cp or ((ask + bid) / 2.0)
    try:
        too_close = app._near_key_levels_too_close(mt5_ctx, float(cfg.trade_min_dist_keylvl_pips), cp0)
    except Exception:
        too_close = False
    if mt5_ctx and too_close:
        app.ui_status("Auto-Trade: too close to key level.")
        try:
            app._log_trade_decision({"stage": "precheck-fail", "reason": "near_key_level", "sym": sym, "dir": direction, "cp": cp0, "min_dist_pips": float(cfg.trade_min_dist_keylvl_pips)}, folder_override=(app.mt5_symbol_var.get().strip() if hasattr(app, "mt5_symbol_var") else None))
        except Exception:
            pass
        return

    setup_sig = hashlib.sha1(f"{sym}|{direction}|{round(entry or 0,5)}|{round(sl or 0,5)}|{round(tp1 or 0,5)}|{round(tp2 or 0,5)}".encode("utf-8")).hexdigest()
    state = app._load_last_trade_state()
    last_sig = (state.get("sig") or "") if isinstance(state, dict) else ""
    last_ts = float((state.get("time") if isinstance(state, dict) else 0.0) or 0.0)
    cool_s = int(cfg.trade_cooldown_min) * 60
    now_ts = time.time()
    if last_sig == setup_sig and (now_ts - last_ts) < cool_s:
        app.ui_status("Auto-Trade: duplicate setup, cooldown active.")
        try:
            app._log_trade_decision({"stage": "precheck-fail", "reason": "duplicate_setup", "sym": sym, "dir": direction, "setup_sig": setup_sig, "last_sig": last_sig, "elapsed_s": (now_ts - last_ts), "cooldown_s": cool_s}, folder_override=(app.mt5_symbol_var.get().strip() if hasattr(app, "mt5_symbol_var") else None))
        except Exception:
            pass
        return

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
                app._log_trade_decision({"stage": "precheck-fail", "reason": "sl_zero", "sym": sym, "dir": direction, "entry": entry, "sl": sl, "point": point}, folder_override=(app.mt5_symbol_var.get().strip() if hasattr(app, "mt5_symbol_var") else None))
            except Exception:
                pass
            return
        value_per_point = (mt5_utils.value_per_point(sym, info) or 0.0)
        if value_per_point <= 0:
            app.ui_status("Auto-Trade: cannot determine value per point.")
            try:
                app._log_trade_decision({"stage": "precheck-fail", "reason": "no_value_per_point", "sym": sym, "dir": direction}, folder_override=(app.mt5_symbol_var.get().strip() if hasattr(app, "mt5_symbol_var") else None))
            except Exception:
                pass
            return
        if mode == "percent":
            equity = float(getattr(acc, "equity", 0.0))
            risk_money = equity * float(cfg.trade_equity_risk_pct) / 100.0
        else:
            risk_money = float(cfg.trade_money_risk)
        if not risk_money or risk_money <= 0:
            app.ui_status("Auto-Trade: invalid risk.")
            try:
                app._log_trade_decision({"stage": "precheck-fail", "reason": "invalid_risk", "sym": sym, "dir": direction, "mode": mode, "equity": float(getattr(acc, "equity", 0.0))}, folder_override=(app.mt5_symbol_var.get().strip() if hasattr(app, "mt5_symbol_var") else None))
            except Exception:
                pass
            return
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
            app._log_trade_decision({"stage": "precheck-fail", "reason": "volume_too_small_after_split", "sym": sym, "dir": direction, "lots_total": lots_total, "vol1": vol1, "vol2": vol2, "vol_min": vol_min}, folder_override=(app.mt5_symbol_var.get().strip() if hasattr(app, "mt5_symbol_var") else None))
        except Exception:
            pass
        return

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
        app._log_trade_decision({**log_base, "stage": "pre-check"}, folder_override=(app.mt5_symbol_var.get().strip() if hasattr(app, "mt5_symbol_var") else None))
    except Exception:
        pass

    if cfg.auto_trade_dry_run:
        app.ui_status("Auto-Trade: DRY-RUN - logging only.")
        app._save_last_trade_state({"sig": setup_sig, "time": time.time()})
        return

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
        res = app._order_send_smart(req, prefer=prefer, retry_per_mode=2)
        if not res or res.retcode != mt5.TRADE_RETCODE_DONE:
            errs.append(str(getattr(res, "comment", "unknown")))

    if errs:
        app.ui_status("Auto-Trade: order errors: " + "; ".join(errs))
        try:
            app._log_trade_decision({**log_base, "stage": "send", "errors": errs}, folder_override=(app.mt5_symbol_var.get().strip() if hasattr(app, "mt5_symbol_var") else None))
        except Exception:
            pass
    else:
        app._save_last_trade_state({"sig": setup_sig, "time": time.time()})
        try:
            app._log_trade_decision({**log_base, "stage": "send", "ok": True}, folder_override=(app.mt5_symbol_var.get().strip() if hasattr(app, "mt5_symbol_var") else None))
        except Exception:
            pass
        app.ui_status("Auto-Trade: placed TP1/TP2 orders.")


def mt5_manage_be_trailing(app, mt5_ctx: dict, cfg: RunConfig):
    """Move SL to BE after TP1 and apply ATR trailing for TP2 legs."""
    if not (cfg.mt5_enabled and mt5 and cfg.auto_trade_enabled):
        return
    try:
        if mt5.account_info() is None:
            return
        magic = int(cfg.trade_magic)
        # Inputs for trailing
        try:
            point = float(((mt5_ctx.get("info") or {}).get("point")) or 0.0)
            atr = (((mt5_ctx.get("volatility") or {}).get("ATR") or {}).get("M5"))
        except Exception:
            point = 0.0
            atr = None
        atr_pts = (atr / point) if (atr and point) else None
        atr_mult = float(cfg.trade_trailing_atr_mult or 0.0)

        positions = mt5.positions_get() or []
        if not positions:
            return

        now = datetime.now()
        deals = mt5.history_deals_get(now - timedelta(days=2), now) or []
        tp1_closed = set()
        for d in deals:
            try:
                if int(getattr(d, "magic", 0)) == magic and "-TP1" in str(getattr(d, "comment", "")):
                    tp1_closed.add((getattr(d, "symbol", ""), int(getattr(d, "position_id", 0))))
            except Exception:
                pass

        for p in positions:
            try:
                if int(getattr(p, "magic", 0)) != magic:
                    continue
                cmt = str(getattr(p, "comment", ""))
                if "-TP2" not in cmt:
                    continue
                sym = getattr(p, "symbol", "")
                entry = float(getattr(p, "price_open", 0.0))
                sl = float(getattr(p, "sl", 0.0)) if getattr(p, "sl", 0.0) else None
                pos_id = int(getattr(p, "ticket", 0))

                tick = mt5.symbol_info_tick(sym)
                if not tick:
                    continue
                bid = float(getattr(tick, "bid", 0.0))
                ask = float(getattr(tick, "ask", 0.0))
                cur = ask if int(getattr(p, "type", 0)) == getattr(mt5, 'POSITION_TYPE_BUY', 0) else bid
                if not cur:
                    continue

                move_to_be = False
                if cfg.trade_move_to_be_after_tp1:
                    if (sym, pos_id) in tp1_closed:
                        move_to_be = True
                    elif sl is not None and point:
                        half = abs(entry - sl) * 0.5
                        is_buy = int(getattr(p, "type", 0)) == getattr(mt5, 'POSITION_TYPE_BUY', 0)
                        if (is_buy and cur - entry >= half) or ((not is_buy) and entry - cur >= half):
                            move_to_be = True

                new_sl = sl
                if move_to_be and point:
                    buf = (point * 2)
                    is_buy = int(getattr(p, "type", 0)) == getattr(mt5, 'POSITION_TYPE_BUY', 0)
                    new_sl = entry - buf if is_buy else entry + buf

                if atr_pts and atr_mult > 0 and point:
                    trail = atr_pts * atr_mult * point
                    is_buy = int(getattr(p, "type", 0)) == getattr(mt5, 'POSITION_TYPE_BUY', 0)
                    cand = (cur - trail) if is_buy else (cur + trail)
                    if new_sl is None or (is_buy and cand > new_sl) or ((not is_buy) and cand < new_sl):
                        new_sl = cand

                if new_sl and (sl is None or abs(new_sl - sl) > (point * 1.5)):
                    req = dict(action=mt5.TRADE_ACTION_SLTP, position=pos_id, symbol=sym, sl=round(new_sl, mt5.symbol_info(sym).digits), tp=getattr(p, 'tp', None))
                    _ = app._order_send_safe(req, retry=2)
            except Exception:
                continue
    except Exception:
        pass
