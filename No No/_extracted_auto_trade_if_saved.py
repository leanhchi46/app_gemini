    def auto_trade.auto_trade_if_high_prob(self,self, combined_text: str, mt5_ctx: dict, cfg: RunConfig):
        """
        Mục đích: Tự động hóa xử lý lệnh: tính khối lượng, đặt/huỷ lệnh, trailing/BE, kiểm soát RR.
        Tham số:
          - combined_text: str — (tự suy luận theo ngữ cảnh sử dụng).
          - mt5_ctx: dict — (tự suy luận theo ngữ cảnh sử dụng).
          - cfg: RunConfig — (tự suy luận theo ngữ cảnh sử dụng).
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        if not cfg.auto_trade_enabled:
            return
        if not cfg.mt5_enabled or mt5 is None:
            self.ui_status("Auto-Trade: MT5 chưa bật/cài.")
            return

        setup = self._parse_setup_from_report(combined_text)
        direction = setup["direction"]
        entry = setup["entry"]; sl = setup["sl"]; tp1 = setup["tp1"]; tp2 = setup["tp2"]
        bias = (setup["bias_h1"] or "").lower()
        enough = bool(setup["enough"])

        # Resolve MT5 context variables used below
        try:
            sym = (mt5_ctx.get("symbol") if mt5_ctx else None) or (
                (cfg.mt5_symbol if cfg else None) or (self.mt5_symbol_var.get().strip() if hasattr(self, "mt5_symbol_var") else "")
            )
        except Exception:
            sym = (cfg.mt5_symbol if cfg else (self.mt5_symbol_var.get().strip() if hasattr(self, "mt5_symbol_var") else ""))

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
        if mt5 is not None:
            try:
                info = mt5.symbol_info(sym) if sym else None
            except Exception:
                info = None
            try:
                acc = mt5.account_info()
            except Exception:
                acc = None
        # Fallback enrich for digits/point if missing
        try:
            if (not point) and info is not None:
                point = float(getattr(info, "point", 0.0) or 0.0)
        except Exception:
            pass
        try:
            if (not digits) and info is not None:
                digits = int(getattr(info, "digits", 5) or 5)
        except Exception:
            pass

        if direction not in ("long", "short"):
            self.ui_status("Auto-Trade: thiếu hướng lệnh.")
            try:
                self._log_trade_decision({"stage":"Kiểm_tra_trước-fail","reason":"Chưa có setup"},
                                         folder_override=(self.mt5_symbol_var.get().strip() or None))
            except Exception: pass
            return
        if cfg.trade_strict_bias:
            if (bias == "bullish" and direction == "short") or (bias == "bearish" and direction == "long"):
                self.ui_status("Auto-Trade: bỏ qua vì NGƯỢC bias H1.")
                try:
                    self._log_trade_decision({
                        "stage":"Ki?m_tra_tru?c-fail","reason":"Ngu?c_bias_h1",
                        "bias_h1": bias, "dir": direction
                    }, folder_override=(self.mt5_symbol_var.get().strip() or None))
                except Exception:
                    pass
                return
        rr2 = self._calc_rr(entry, sl, tp2)
        if rr2 is not None and rr2 < float(cfg.trade_min_rr_tp2):
            self.ui_status(f"Auto-Trade: RR TP2 {rr2:.2f} < min.")
            try:
                self._log_trade_decision({
                    "stage": "Kiểm_tra_trước-fail", "reason": "RR_dưới_min",
                    "sym": sym, "dir": direction, "entry": entry, "sl": sl, "tp2": tp2,
                    "rr_tp2": rr2, "min_rr": float(cfg.trade_min_rr_tp2)
                }, folder_override=(self.mt5_symbol_var.get().strip() or None))
            except Exception: pass
            return
        cp0 = cp or ((ask+bid)/2.0)
        if mt5_ctx and self._near_key_levels_too_close(mt5_ctx, float(cfg.trade_min_dist_keylvl_pips), cp0):
            self.ui_status("Auto-Trade: quá gần key level — bỏ qua.")
            try:
                self._log_trade_decision({
                    "stage": "Kiểm_tra_trước-fail", "reason": "Quá_gần_key_level",
                    "sym": sym, "dir": direction, "cp": cp0,
                    "min_dist_pips": float(cfg.trade_min_dist_keylvl_pips)
                }, folder_override=(self.mt5_symbol_var.get().strip() or None))
            except Exception: pass
            return

        setup_sig = hashlib.sha1(f"{sym}|{direction}|{round(entry,5)}|{round(sl,5)}|{round(tp1,5)}|{round(tp2,5)}".encode("utf-8")).hexdigest()
        state = self._load_last_trade_state()
        last_sig = (state.get("sig") or "")
        last_ts  = float(state.get("time", 0.0))
        cool_s   = int(cfg.trade_cooldown_min) * 60
        now_ts   = time.time()
        if last_sig == setup_sig and (now_ts - last_ts) < cool_s:
            self.ui_status("Auto-Trade: bỏ qua — trùng setup & còn cooldown.")
            try:
                self._log_trade_decision({
                    "stage": "Kiểm_tra_trước-fail", "reason": "Trùng_setup",
                    "sym": sym, "dir": direction, "setup_sig": setup_sig,
                    "last_sig": last_sig, "elapsed_s": (now_ts - last_ts), "cooldown_s": cool_s
                }, folder_override=(self.mt5_symbol_var.get().strip() or None))
            except Exception: pass
            return

        pending_thr = int(cfg.trade_pending_threshold_points)
        try:
            atr = (((mt5_ctx.get("volatility") or {}).get("ATR") or {}).get("M5"))
            pt  = float(((mt5_ctx.get("info") or {}).get("point")) or 0.0)
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
            dist_points = abs(entry - sl) / point
            if dist_points <= 0:
                self.ui_status("Auto-Trade: khoảng SL=0.")
                try:
                    self._log_trade_decision({
                        "stage": "Kiểm_tra_trước-fail", "reason": "sl_bằng_zero",
                        "sym": sym, "dir": direction, "entry": entry, "sl": sl, "point": point
                    }, folder_override=(self.mt5_symbol_var.get().strip() or None))
                except Exception: pass
                return
            # Use centralized MT5 helper for value per point
            value_per_point = (mt5_utils.value_per_point(sym, info) or 0.0)
            if value_per_point <= 0:
                self.ui_status("Auto-Trade: không xác định được value per point — bỏ qua.")
                try:
                    self._log_trade_decision({
                        "stage": "Kiểm_tra_trước-fail", "reason": "Không_xác_định_được_giá_trị_mỗi_point",
                        "sym": sym, "dir": direction
                    }, folder_override=(self.mt5_symbol_var.get().strip() or None))
                except Exception: pass
                return

            if mode == "percent":
                equity = float(getattr(acc, "equity", 0.0))
                risk_money = equity * float(cfg.trade_equity_risk_pct) / 100.0
            else:
                risk_money = float(cfg.trade_money_risk)
            if not risk_money or risk_money <= 0:
                self.ui_status("Auto-Trade: rủi ro không hợp lệ.")
                try:
                    self._log_trade_decision({
                        "stage": "Kiểm_tra_trước-fail", "reason": "Rủi_ro_không_hợp_lệ",
                        "sym": sym, "dir": direction, "mode": mode,
                        "equity": float(getattr(acc, "equity", 0.0))
                    }, folder_override=(self.mt5_symbol_var.get().strip() or None))
                except Exception: pass
                return
            lots_total = risk_money / (dist_points * value_per_point)

        vol_min = getattr(info, "volume_min", 0.01) or 0.01
        vol_max = getattr(info, "volume_max", 100.0) or 100.0
        vol_step = getattr(info, "volume_step", 0.01) or 0.01
        def _round_step(v):
            """
            Mục đích: Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
            Tham số:
              - v — (tự suy luận theo ngữ cảnh sử dụng).
            Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
            Ghi chú:
              - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
            """
            k = round(v / vol_step)
            return max(vol_min, min(vol_max, k * vol_step))
        lots_total = _round_step(lots_total)
        split1 = max(1, min(99, int(cfg.trade_split_tp1_pct))) / 100.0
        vol1 = _round_step(lots_total * split1)
        vol2 = _round_step(lots_total - vol1)
        if vol1 < vol_min or vol2 < vol_min:
            self.ui_status("Auto-Trade: khối lượng quá nhỏ sau chia TP.")
            try:
                self._log_trade_decision({
                    "stage": "Kiểm_tra_trước-fail", "reason": "Khối_lượng_quá_nhỏ_sau_chia_TP",
                    "sym": sym, "dir": direction, "lots_total": lots_total,
                    "vol1": vol1, "vol2": vol2, "vol_min": vol_min
                }, folder_override=(self.mt5_symbol_var.get().strip() or None))
            except Exception: pass
            return

        deviation = int(cfg.trade_deviation_points)
        magic = int(cfg.trade_magic)
        comment_prefix = (cfg.trade_comment_prefix or "AI-ICT").strip()

        dist_to_entry_pts = abs(entry - cp) / point
        use_pending = dist_to_entry_pts >= pending_thr
        if use_pending and dist_to_entry_pts <= deviation:
            use_pending = False

        from datetime import timedelta
        exp_time = datetime.now() + timedelta(minutes=int(cfg.trade_pending_ttl_min))

        log_base = {
            "t": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "sym": sym, "dir": direction, "entry": entry, "sl": sl, "tp1": tp1, "tp2": tp2,
            "lots_total": lots_total, "vol1": vol1, "vol2": vol2,
            "rr_tp2": rr2, "use_pending": use_pending, "pending_thr": pending_thr,
            "cooldown_s": cool_s, "deviation": deviation, "magic": magic,
            "dry_run": bool(cfg.auto_trade_dry_run)
        }
        self._log_trade_decision({**log_base, "stage": "pre-check"}, folder_override=(self.mt5_symbol_var.get().strip() or None))

        if cfg.auto_trade_dry_run:
            self.ui_status("Auto-Trade: DRY-RUN — chỉ log, không gửi lệnh.")

            self._save_last_trade_state({"sig": setup_sig, "time": time.time()})
            return

        reqs = []
        if use_pending:
            if direction == "long":
                otype = mt5.ORDER_TYPE_BUY_LIMIT if entry < cp else mt5.ORDER_TYPE_BUY_STOP
            else:
                otype = mt5.ORDER_TYPE_SELL_LIMIT if entry > cp else mt5.ORDER_TYPE_SELL_STOP
            common = dict(
                action=mt5.TRADE_ACTION_PENDING, symbol=sym, type=otype, price=round(entry, digits),
                sl=round(sl, digits), deviation=deviation, magic=magic,
                type_time=mt5.ORDER_TIME_SPECIFIED, expiration=exp_time
            )

            reqs = [
                dict(**common, volume=vol1, tp=round(tp1, digits), comment=f"{comment_prefix}-TP1"),
                dict(**common, volume=vol2, tp=round(tp2, digits), comment=f"{comment_prefix}-TP2"),
            ]
        else:
            if direction == "long":
                otype = mt5.ORDER_TYPE_BUY;  px = round(ask, digits)
            else:
                otype = mt5.ORDER_TYPE_SELL; px = round(bid, digits)
            common = dict(
                action=mt5.TRADE_ACTION_DEAL, symbol=sym, type=otype, price=px,
                sl=round(sl, digits), deviation=deviation, magic=magic,
                type_time=mt5.ORDER_TIME_GTC
            )

            reqs = [
                dict(**common, volume=vol1, tp=round(tp1, digits), comment=f"{comment_prefix}-TP1"),
                dict(**common, volume=vol2, tp=round(tp2, digits), comment=f"{comment_prefix}-TP2"),
            ]

        errs = []
        for req in reqs:
            prefer = "pending" if req.get("action") == mt5.TRADE_ACTION_PENDING else "market"
            res = self._order_send_smart(req, prefer=prefer, retry_per_mode=2)
            if not res or res.retcode != mt5.TRADE_RETCODE_DONE:
                errs.append(str(getattr(res, "comment", "unknown")))

        if errs:
            self.ui_status("Auto-Trade: lỗi gửi lệnh: " + "; ".join(errs))
            self._log_trade_decision({**log_base, "stage": "send", "errors": errs}, folder_override=(self.mt5_symbol_var.get().strip() or None))
        else:
            self._save_last_trade_state({"sig": setup_sig, "time": time.time()})
            self._log_trade_decision({**log_base, "stage": "send", "ok": True}, folder_override=(self.mt5_symbol_var.get().strip() or None))
            self.ui_status("Auto-Trade: đã gửi 2 lệnh TP1/TP2.")


