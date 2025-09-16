from __future__ import annotations

import tkinter as tk
from tkinter import ttk

try:
    # Optional: Only needed when the Chart tab is used
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
except Exception:  # pragma: no cover - optional UI deps
    Figure = None  # type: ignore
    FigureCanvasTkAgg = None  # type: ignore


class ChartTabTV:
    """
    Chart tab for displaying price data, account info, positions and history.
    Relies on MetaTrader5 and matplotlib if present; constructed by the main app
    only when those dependencies are available.
    """

    def __init__(self, app, notebook):
        self.app = app
        self.root = app.root

        self.symbol_var = tk.StringVar(value="XAUUSD")
        self.tf_var = tk.StringVar(value="M1")
        self.n_candles_var = tk.IntVar(value=100)
        self.refresh_secs_var = tk.IntVar(value=1)

        self._after_job = None
        self._running = False

        self.tab = ttk.Frame(notebook, padding=8)
        notebook.add(self.tab, text="Chart")

        self.tab.rowconfigure(1, weight=1)
        self.tab.columnconfigure(0, weight=2)
        self.tab.columnconfigure(1, weight=1)

        ctrl = ttk.Frame(self.tab)
        ctrl.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        for i in range(10):
            ctrl.columnconfigure(i, weight=0)
        ctrl.columnconfigure(9, weight=1)

        ttk.Label(ctrl, text="Symbol:").grid(row=0, column=0, sticky="w")
        self.cbo_symbol = ttk.Combobox(ctrl, width=16, textvariable=self.symbol_var, state="normal", values=[])
        self.cbo_symbol.grid(row=0, column=1, sticky="w", padx=(4, 10))
        self.cbo_symbol.bind("<<ComboboxSelected>>", lambda e: self._redraw_safe())
        self._populate_symbol_list()

        ttk.Label(ctrl, text="TF:").grid(row=0, column=2, sticky="w")
        self.cbo_tf = ttk.Combobox(
            ctrl, width=6, state="readonly", values=["M1", "M5", "M15", "H1", "H4", "D1"], textvariable=self.tf_var
        )
        self.cbo_tf.grid(row=0, column=3, sticky="w", padx=(4, 10))
        self.cbo_tf.bind("<<ComboboxSelected>>", lambda e: self._redraw_safe())

        ttk.Label(ctrl, text="Số nến:").grid(row=0, column=4, sticky="w")
        ttk.Spinbox(ctrl, from_=50, to=5000, textvariable=self.n_candles_var, width=8, command=self._redraw_safe)\
            .grid(row=0, column=5, sticky="w", padx=(4, 10))

        ttk.Label(ctrl, text="Làm mới (s):").grid(row=0, column=6, sticky="w")
        ttk.Spinbox(ctrl, from_=1, to=3600, textvariable=self.refresh_secs_var, width=6)\
            .grid(row=0, column=7, sticky="w", padx=(4, 10))

        self.btn_start = ttk.Button(ctrl, text="► Start", command=self.start)
        self.btn_start.grid(row=0, column=8, sticky="w")
        self.btn_stop = ttk.Button(ctrl, text="□ Stop", command=self.stop, state="disabled")
        self.btn_stop.grid(row=0, column=9, sticky="w", padx=(6, 10))
        try:
            self.btn_start.grid_remove()
            self.btn_stop.grid_remove()
        except Exception:
            pass

        self.root.after(200, self.start)

        chart_wrap = ttk.Frame(self.tab)
        chart_wrap.grid(row=1, column=0, sticky="nsew", padx=(0, 6))
        chart_wrap.rowconfigure(1, weight=1)
        chart_wrap.columnconfigure(0, weight=1)

        if Figure is None or FigureCanvasTkAgg is None:
            # Minimal fallback if matplotlib is not present
            label = ttk.Label(chart_wrap, text="Matplotlib not available")
            label.grid(row=0, column=0, sticky="w")
            return

        self.fig = Figure(figsize=(6, 4), dpi=100, constrained_layout=False)
        self.ax_price = self.fig.add_subplot(1, 1, 1)
        self.canvas = FigureCanvasTkAgg(self.fig, master=chart_wrap)
        self.canvas.get_tk_widget().grid(row=1, column=0, sticky="nsew")

        try:
            from matplotlib.backends.backend_tkagg import NavigationToolbar2Tk  # type: ignore
            tb_frame = ttk.Frame(chart_wrap)
            tb_frame.grid(row=0, column=0, sticky="ew", pady=(0, 4))
            self.toolbar = NavigationToolbar2Tk(self.canvas, tb_frame)
            self.toolbar.update()
        except Exception:
            self.toolbar = None

        # Right column wrapper to stack panels (Account + No-Trade)
        right_col = ttk.Frame(self.tab)
        right_col.grid(row=1, column=1, sticky="nsew")
        for i in range(1):
            right_col.columnconfigure(i, weight=1)

        acc_box = ttk.LabelFrame(right_col, text="Account info", padding=8)
        acc_box.grid(row=0, column=0, sticky="nsew")
        for i in range(2):
            acc_box.columnconfigure(i, weight=1)
        self.acc_balance = tk.StringVar(value="-")
        self.acc_equity = tk.StringVar(value="-")
        self.acc_margin = tk.StringVar(value="-")
        self.acc_leverage = tk.StringVar(value="-")
        self.acc_currency = tk.StringVar(value="-")
        self.acc_status = tk.StringVar(value="Chưa kết nối MT5")
        ttk.Label(acc_box, text="Balance:").grid(row=0, column=0, sticky="w")
        ttk.Label(acc_box, textvariable=self.acc_balance).grid(row=0, column=1, sticky="e")
        ttk.Label(acc_box, text="Equity:").grid(row=1, column=0, sticky="w")
        ttk.Label(acc_box, textvariable=self.acc_equity).grid(row=1, column=1, sticky="e")
        ttk.Label(acc_box, text="Free margin:").grid(row=2, column=0, sticky="w")
        ttk.Label(acc_box, textvariable=self.acc_margin).grid(row=2, column=1, sticky="e")
        ttk.Label(acc_box, text="Leverage:").grid(row=3, column=0, sticky="w")
        ttk.Label(acc_box, textvariable=self.acc_leverage).grid(row=3, column=1, sticky="e")
        ttk.Label(acc_box, text="Currency:").grid(row=4, column=0, sticky="w")
        ttk.Label(acc_box, textvariable=self.acc_currency).grid(row=4, column=1, sticky="e")
        ttk.Separator(acc_box, orient="horizontal").grid(row=5, column=0, columnspan=2, sticky="ew", pady=6)
        ttk.Label(acc_box, textvariable=self.acc_status, foreground="#666").grid(row=6, column=0, columnspan=2, sticky="w")

        grids = ttk.Frame(self.tab)
        grids.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=(6, 0))
        grids.columnconfigure(0, weight=1)
        grids.columnconfigure(1, weight=1)
        grids.rowconfigure(0, weight=1)

        pos_box = ttk.LabelFrame(grids, text="Open positions", padding=6)
        pos_box.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        pos_box.rowconfigure(0, weight=1)
        pos_box.columnconfigure(0, weight=1)
        self.pos_cols = ("ticket", "type", "lots", "price", "sl", "tp", "pnl")
        self.tree_pos = ttk.Treeview(pos_box, columns=self.pos_cols, show="headings", height=6)
        for c, w in zip(self.pos_cols, (90, 110, 70, 110, 110, 110, 100)):
            self.tree_pos.heading(c, text=c.upper())
            self.tree_pos.column(c, width=w, anchor="e" if c in ("lots", "price", "sl", "tp", "pnl") else "w")
        self.tree_pos.grid(row=0, column=0, sticky="nsew")
        scr1 = ttk.Scrollbar(pos_box, orient="vertical", command=self.tree_pos.yview)
        self.tree_pos.configure(yscrollcommand=scr1.set)
        scr1.grid(row=0, column=1, sticky="ns")

        his_box = ttk.LabelFrame(grids, text="History (deals gần nhất)", padding=6)
        his_box.grid(row=0, column=1, sticky="nsew", padx=(4, 0))
        his_box.rowconfigure(0, weight=1)
        his_box.columnconfigure(0, weight=1)
        self.his_cols = ("time", "ticket", "type", "volume", "price", "profit")
        self.tree_his = ttk.Treeview(his_box, columns=self.his_cols, show="headings", height=6)
        for c, w in zip(self.his_cols, (140, 90, 70, 80, 110, 100)):
            self.tree_his.heading(c, text=c.upper())
            self.tree_his.column(c, width=w, anchor="e" if c in ("volume", "price", "profit") else "w")
        self.tree_his.grid(row=0, column=0, sticky="nsew")
        scr2 = ttk.Scrollbar(his_box, orient="vertical", command=self.tree_his.yview)
        self.tree_his.configure(yscrollcommand=scr2.set)
        scr2.grid(row=0, column=1, sticky="ns")

        # --- No-Trade panel ---
        self.nt_session_gate = tk.StringVar(value="-")
        self.nt_reasons = tk.StringVar(value="")
        self.nt_events = tk.StringVar(value="")

        nt_box = ttk.LabelFrame(right_col, text="No-Trade", padding=8)
        nt_box.grid(row=1, column=0, sticky="nsew", pady=(6, 0))
        nt_box.columnconfigure(0, weight=1)

        ttk.Label(nt_box, text="Session gate:").grid(row=0, column=0, sticky="w")
        self.lbl_nt_session = ttk.Label(nt_box, textvariable=self.nt_session_gate)
        self.lbl_nt_session.grid(row=0, column=1, sticky="e")

        ttk.Label(nt_box, text="Reasons:").grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.lbl_nt_reasons = ttk.Label(nt_box, textvariable=self.nt_reasons, wraplength=260, justify="left")
        self.lbl_nt_reasons.grid(row=2, column=0, columnspan=2, sticky="w")

        ttk.Label(nt_box, text="Upcoming events:").grid(row=3, column=0, sticky="w", pady=(6, 0))
        self.lbl_nt_events = ttk.Label(nt_box, textvariable=self.nt_events, wraplength=260, justify="left")
        self.lbl_nt_events.grid(row=4, column=0, columnspan=2, sticky="w")

        self._redraw_safe()

    def start(self):
        if self._running:
            return
        self._running = True
        self.btn_start.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self._tick()

    def stop(self):
        self._running = False
        if self._after_job:
            self.root.after_cancel(self._after_job)
            self._after_job = None
        self.btn_start.configure(state="normal")
        self.btn_stop.configure(state="disabled")

    def _populate_symbol_list(self):
        try:
            if not self._ensure_mt5(want_account=False):
                return
            import MetaTrader5 as mt5
            syms = mt5.symbols_get()
            names = sorted([s.name for s in syms]) if syms else []
            if names:
                self.cbo_symbol["values"] = names
                if "XAUUSD" in names:
                    self.symbol_var.set("XAUUSD")
        except Exception:
            pass

    def _mt5_tf(self, tf_str: str):
        try:
            import MetaTrader5 as mt5
        except Exception:
            return None
        mapping = {
            "M1": mt5.TIMEFRAME_M1,
            "M5": mt5.TIMEFRAME_M5,
            "M15": mt5.TIMEFRAME_M15,
            "H1": mt5.TIMEFRAME_H1,
            "H4": mt5.TIMEFRAME_H4,
            "D1": mt5.TIMEFRAME_D1,
        }
        return mapping.get(tf_str.upper(), mt5.TIMEFRAME_M5)

    def _ensure_mt5(self, *, want_account: bool = True) -> bool:
        try:
            import MetaTrader5 as mt5
        except Exception:
            self.acc_status.set("Chưa cài MetaTrader5 (pip install MetaTrader5)")
            return False
        if getattr(self.app, "mt5_initialized", False):
            if want_account and mt5.account_info() is None:
                self.acc_status.set("MT5: chưa đăng nhập (account_info=None)")
                return False
            return True
        if getattr(self.app, "mt5_enabled_var", None) and self.app.mt5_enabled_var.get():
            try:
                self.app._mt5_connect()
            except Exception:
                pass
            if getattr(self.app, "mt5_initialized", False):
                if want_account and mt5.account_info() is None:
                    self.acc_status.set("MT5: chưa đăng nhập (account_info=None)")
                    return False
                return True
        return False

    def _rates_to_df(self, symbol, tf_code, count: int):
        try:
            import MetaTrader5 as mt5
            import pandas as pd
        except Exception:
            return None
        try:
            rates = mt5.copy_rates_from_pos(symbol, tf_code, 0, int(count))
            if not rates:
                return None
            import pandas as pd
            df = pd.DataFrame(rates)
            if df.empty:
                return None
            import datetime as _dt
            df["time"] = pd.to_datetime(df["time"], unit="s")
            df.set_index("time", inplace=True)
            return df
        except Exception:
            return None

    def _style(self):
        try:
            import matplotlib as mpl
            mpl.rcParams.update({"axes.grid": True, "grid.alpha": 0.25})
        except Exception:
            pass

    def _fmt(self, x, digits=5):
        try:
            return f"{float(x):.{int(digits)}f}"
        except Exception:
            return str(x)

    def _update_account_info(self, symbol: str):
        try:
            import MetaTrader5 as mt5
            ai = mt5.account_info()
            if ai:
                self.acc_balance.set(f"{ai.balance:.2f}")
                self.acc_equity.set(f"{ai.equity:.2f}")
                self.acc_margin.set(f"{ai.margin_free:.2f}")
                self.acc_leverage.set(str(getattr(ai, "leverage", "-")))
                self.acc_currency.set(getattr(ai, "currency", "-"))
                self.acc_status.set("Kết nối MT5 OK")
        except Exception:
            pass

    def _fill_positions_table(self, symbol: str):
        try:
            import MetaTrader5 as mt5
            poss = mt5.positions_get(symbol=symbol) or []
            self.tree_pos.delete(*self.tree_pos.get_children())
            for p in poss:
                typ = int(getattr(p, "type", 0))
                lots = float(getattr(p, "volume", 0.0))
                price = float(getattr(p, "price_open", 0.0))
                sl = float(getattr(p, "sl", 0.0)) or None
                tp = float(getattr(p, "tp", 0.0)) or None
                pnl = float(getattr(p, "profit", 0.0))
                self.tree_pos.insert("", "end", values=(getattr(p, "ticket", "?"), "BUY" if typ == 0 else "SELL", f"{lots:.2f}",
                                                          self._fmt(price), self._fmt(sl), self._fmt(tp), f"{pnl:.2f}"))
        except Exception:
            pass

    def _fill_history_table(self, symbol: str):
        try:
            import MetaTrader5 as mt5
            self.tree_his.delete(*self.tree_his.get_children())
            now = __import__("datetime").datetime.now()
            deals = mt5.history_deals_get(now.replace(hour=0, minute=0, second=0), now, group=f"*{symbol}*") or []
            for d in deals[-100:]:
                t = getattr(d, "time", None)
                if t:
                    import datetime as _dt
                    t = _dt.datetime.fromtimestamp(int(t))
                self.tree_his.insert("", "end", values=(t, getattr(d, "ticket", "?"), getattr(d, "type", "?"),
                                                          getattr(d, "volume", "?"), getattr(d, "price", "?"), getattr(d, "profit", "?")))
        except Exception:
            pass

    def _draw_chart(self):
        try:
            import MetaTrader5 as mt5
        except Exception:
            return
        sym = self.symbol_var.get().strip()
        tf_code = self._mt5_tf(self.tf_var.get())
        cnt = int(self.n_candles_var.get() or 100)
        df = self._rates_to_df(sym, tf_code, cnt)
        if df is None or df.empty:
            self.ax_price.clear()
            self.ax_price.set_title("No data")
            self.canvas.draw_idle()
            return
        self.ax_price.clear()
        try:
            import matplotlib.dates as mdates
            self.ax_price.plot(df.index, df["close"], color="#0ea5e9", lw=1.2)
            self.ax_price.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
        except Exception:
            pass
        try:
            digits = 2
            info = mt5.symbol_info(sym)
            if info:
                digits = int(getattr(info, "digits", 2))
            poss = mt5.positions_get(symbol=sym) or []
            for p in poss:
                typ_i = int(getattr(p, "type", 0))
                entry = float(getattr(p, "price_open", 0.0))
                sl = float(getattr(p, "sl", 0.0)) or None
                tp = float(getattr(p, "tp", 0.0)) or None
                col = "#22c55e" if typ_i == 0 else "#ef4444"
                self.ax_price.axhline(entry, color=col, ls="--", lw=1.0, alpha=0.95)
                if sl:
                    self.ax_price.axhline(sl, color="#ef4444", ls=":", lw=1.0, alpha=0.85)
                if tp:
                    self.ax_price.axhline(tp, color="#22c55e", ls=":", lw=1.0, alpha=0.85)
                label = f"{'BUY' if typ_i==0 else 'SELL'} {getattr(p,'volume',0):.2f} @{self._fmt(entry, digits)}"
                self.ax_price.text(df.index[-1], entry, "  " + label, va="center", color=col, fontsize=8)

            ords = mt5.orders_get(symbol=sym) or []
            def _otype_txt(t):
                m = {
                    getattr(mt5, "ORDER_TYPE_BUY_LIMIT", 2):  "BUY LIMIT",
                    getattr(mt5, "ORDER_TYPE_BUY_STOP", 4):   "BUY STOP",
                    getattr(mt5, "ORDER_TYPE_SELL_LIMIT", 3): "SELL LIMIT",
                    getattr(mt5, "ORDER_TYPE_SELL_STOP", 5):  "SELL STOP",
                }
                return m.get(int(t), f"TYPE {t}")
            for o in ords:
                otype = int(getattr(o, "type", 0))
                lots  = float(getattr(o, "volume_current", 0.0))
                px    = float(getattr(o, "price_open", 0.0)) or float(getattr(o, "price_current", 0.0))
                sl    = float(getattr(o, "sl", 0.0)) or None
                tp    = float(getattr(o, "tp", 0.0)) or None
                pend_col = "#8b5cf6"
                self.ax_price.axhline(px, color=pend_col, ls="--", lw=1.1, alpha=0.95)
                txt = f"PEND {_otype_txt(otype)} {lots:.2f} @{self._fmt(px, digits)}"
                self.ax_price.text(df.index[-1], px, "  " + txt, va="center", color=pend_col, fontsize=8)
                if sl:
                    self.ax_price.axhline(sl, color="#ef4444", ls=":", lw=1.0, alpha=0.85)
                    self.ax_price.text(df.index[-1], sl, "  SL", va="center", color="#ef4444", fontsize=7)
                if tp:
                    self.ax_price.axhline(tp, color="#22c55e", ls=":", lw=1.0, alpha=0.85)
                    self.ax_price.text(df.index[-1], tp, "  TP", va="center", color="#22c55e", fontsize=7)
        except Exception:
            pass

        self.ax_price.set_title(f"{sym}  •  {self.tf_var.get()}  •  {len(df)} bars")
        self.canvas.draw_idle()

        self._update_account_info(sym)
        self._fill_positions_table(sym)
        self._fill_history_table(sym)

    def _redraw_safe(self):
        try:
            self._draw_chart()
        except Exception as e:
            try:
                self.ax_price.clear()
                self.ax_price.set_title(f"Chart error: {e}")
                self.canvas.draw_idle()
            except Exception:
                pass
        try:
            self._update_notrade_panel()
        except Exception:
            pass

    def _tick(self):
        if not self._running:
            return
        try:
            # Opportunistic refresh of shared news cache (non-blocking)
            if hasattr(self.app, "_refresh_news_cache"):
                ttl = None
                try:
                    ttl = int(getattr(self.app, "news_cache_ttl_sec_var", None).get()) if getattr(self.app, "news_cache_ttl_sec_var", None) else None
                except Exception:
                    ttl = None
                self.app._refresh_news_cache(ttl=int(ttl or 300))
        except Exception:
            pass
        self._redraw_safe()
        secs = max(1, int(self.refresh_secs_var.get() or 5))
        self._after_job = self.root.after(secs * 1000, self._tick)

    # -------------------------
    # No-Trade panel helpers
    # -------------------------
    def _compute_sessions_today(self, symbol: str) -> dict:
        try:
            import MetaTrader5 as mt5
            from . import mt5_utils as _mt5u
        except Exception:
            return {}
        try:
            # Minimal: any non-empty list unlocks session schedule
            arr = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M1, 0, 5) or []
            if not arr:
                return {}
            rows = [{"time": str(x.get("time"))} for x in arr]
            return _mt5u.session_ranges_today(rows) or {}
        except Exception:
            return {}

    def _allowed_session_now(self, ss: dict) -> bool:
        try:
            now = __import__("datetime").datetime.now().strftime("%H:%M")
            def _in(r):
                return bool(r and r.get("start") and r.get("end") and r["start"] <= now < r["end"])
            ok = False
            if getattr(self.app, "trade_allow_session_asia_var", None) and self.app.trade_allow_session_asia_var.get():
                ok = ok or _in(ss.get("asia"))
            if getattr(self.app, "trade_allow_session_london_var", None) and self.app.trade_allow_session_london_var.get():
                ok = ok or _in(ss.get("london"))
            if getattr(self.app, "trade_allow_session_ny_var", None) and self.app.trade_allow_session_ny_var.get():
                ok = ok or _in(ss.get("newyork_pre")) or _in(ss.get("newyork_post"))
            # If no restriction flags checked, allow
            flags = [
                bool(getattr(self.app, "trade_allow_session_asia_var", None) and self.app.trade_allow_session_asia_var.get()),
                bool(getattr(self.app, "trade_allow_session_london_var", None) and self.app.trade_allow_session_london_var.get()),
                bool(getattr(self.app, "trade_allow_session_ny_var", None) and self.app.trade_allow_session_ny_var.get()),
            ]
            if not any(flags):
                ok = True
            return bool(ok)
        except Exception:
            return True

    def _update_notrade_panel(self):
        # Session gate
        sym = (self.symbol_var.get().strip() or getattr(self.app, "mt5_symbol_var", tk.StringVar(value="")).get().strip() or "")
        ss = self._compute_sessions_today(sym) if sym else {}
        sess_ok = self._allowed_session_now(ss)
        self.nt_session_gate.set("Allowed" if sess_ok else "Blocked")

        # Reasons from last evaluate
        reasons = []
        try:
            reasons = list(getattr(self.app, "last_no_trade_reasons", []) or [])
        except Exception:
            reasons = []
        if reasons:
            txt = "\n".join([f"- {str(r)}" for r in reasons[:4]])
        else:
            txt = "(none)"
        self.nt_reasons.set(txt)

        # Upcoming high-impact events (limit 3) relevant to symbol
        try:
            from . import news as _news
            feed = getattr(self.app, "ff_cache_events_local", []) or []
            evs = _news.next_events_for_symbol(feed, sym, limit=3)
            events_fmt = []
            for ev in evs:
                when = ev.get("when") if isinstance(ev, dict) else None
                title = (ev.get("title") if isinstance(ev, dict) else None) or "Event"
                cur = ev.get("curr") if isinstance(ev, dict) else None
                try:
                    ts = when.strftime('%a %H:%M') if hasattr(when, 'strftime') else str(when)
                except Exception:
                    ts = str(when)
                tag = f" [{cur}]" if cur else ""
                events_fmt.append(f"• {ts} — {title}{tag}")
            self.nt_events.set("\n".join(events_fmt) if events_fmt else "(none)")
        except Exception:
            self.nt_events.set("(none)")
