from __future__ import annotations

import tkinter as tk
from tkinter import ttk
import logging
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from APP.ui.app_ui import AppUI

logger = logging.getLogger(__name__)

try:
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
    from mplfinance.original_flavor import candlestick_ohlc  # type: ignore
except ImportError:
    Figure = None
    FigureCanvasTkAgg = None
    candlestick_ohlc = None
    NavigationToolbar2Tk = None
    logger.warning("Không thể import matplotlib hoặc mplfinance. Tab Chart sẽ bị vô hiệu hóa.")


class ChartTab:
    def __init__(self, app: "AppUI", notebook: ttk.Notebook):
        self.app = app
        self.root = app.root
        self.tab = ttk.Frame(notebook, padding=8)
        notebook.add(self.tab, text="Chart")
        self.chart_enabled = all((Figure, FigureCanvasTkAgg, candlestick_ohlc, NavigationToolbar2Tk))

        self._init_vars()
        self._setup_layout()
        self._create_controls()
        self._create_chart_area()
        self._create_info_panels()
        self._create_trade_grids()

        self.root.after(200, self.start)

    def _init_vars(self):
        self.symbol_var = tk.StringVar(value="XAUUSD")
        self.tf_var = tk.StringVar(value="M1")
        self.n_candles_var = tk.IntVar(value=100)
        self.refresh_secs_var = tk.IntVar(value=1)
        self.chart_type_var = tk.StringVar(value="Nến")
        self._after_job: Optional[str] = None
        self._running = False
        # Vars for info panels
        self.acc_balance = tk.StringVar(value="-")
        self.acc_equity = tk.StringVar(value="-")
        self.acc_margin = tk.StringVar(value="-")
        self.acc_leverage = tk.StringVar(value="-")
        self.acc_currency = tk.StringVar(value="-")
        self.acc_status = tk.StringVar(value="Chưa kết nối MT5")
        self.nt_session_gate = tk.StringVar(value="-")
        self.nt_reasons = tk.StringVar(value="")
        self.nt_events = tk.StringVar(value="")

    def _setup_layout(self):
        self.tab.rowconfigure(1, weight=1)
        self.tab.columnconfigure(0, weight=2)
        self.tab.columnconfigure(1, weight=1)

    def _create_controls(self):
        ctrl = ttk.Frame(self.tab)
        ctrl.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        # ... (Full control widgets setup from original file)
        ttk.Label(ctrl, text="Ký hiệu:").grid(row=0, column=0, sticky="w")
        self.cbo_symbol = ttk.Combobox(ctrl, width=16, textvariable=self.symbol_var, state="normal", values=[])
        self.cbo_symbol.grid(row=0, column=1, sticky="w", padx=(4, 10))
        self.cbo_symbol.bind("<<ComboboxSelected>>", lambda e: self._redraw_safe())

        ttk.Label(ctrl, text="Khung:").grid(row=0, column=2, sticky="w")
        self.cbo_tf = ttk.Combobox(ctrl, width=6, state="readonly", values=["M1", "M5", "M15", "H1", "H4", "D1"], textvariable=self.tf_var)
        self.cbo_tf.grid(row=0, column=3, sticky="w", padx=(4, 10))
        self.cbo_tf.bind("<<ComboboxSelected>>", lambda e: self._redraw_safe())
        # ... (add other controls)

    def _create_chart_area(self):
        chart_wrap = ttk.Frame(self.tab)
        chart_wrap.grid(row=1, column=0, sticky="nsew", padx=(0, 6))
        chart_wrap.rowconfigure(1, weight=1)
        chart_wrap.columnconfigure(0, weight=1)

        if not self.chart_enabled:
            ttk.Label(chart_wrap, text="Matplotlib/mplfinance chưa được cài đặt.").grid(row=0, column=0)
            return

        self.fig = Figure(figsize=(6, 4), dpi=100)
        self.ax_price = self.fig.add_subplot(1, 1, 1)
        self.canvas = FigureCanvasTkAgg(self.fig, master=chart_wrap)
        self.canvas.get_tk_widget().grid(row=1, column=0, sticky="nsew")
        
        tb_frame = ttk.Frame(chart_wrap)
        tb_frame.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        self.toolbar = NavigationToolbar2Tk(self.canvas, tb_frame)
        self.toolbar.update()

    def _create_info_panels(self):
        right_col = ttk.Frame(self.tab)
        right_col.grid(row=1, column=1, sticky="nsew")
        # ... (Account info and No-Trade panels setup from original file)

    def _create_trade_grids(self):
        grids = ttk.Frame(self.tab)
        grids.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=(6, 0))
        # ... (Positions and History treeviews setup from original file)

    def start(self):
        if self._running:
            return
        self._running = True
        self._tick()

    def stop(self):
        self._running = False
        if self._after_job:
            self.root.after_cancel(self._after_job)
            self._after_job = None

    def _tick(self):
        if not self._running:
            return
        self._redraw_safe()
        secs = max(1, self.refresh_secs_var.get())
        self._after_job = self.root.after(secs * 1000, self._tick)

    def _redraw_safe(self):
        if not self.chart_enabled:
            return
        try:
            self._draw_chart()
            # ... (update other panels)
        except Exception as e:
            logger.error(f"Lỗi khi vẽ lại biểu đồ: {e}", exc_info=True)

    def _draw_chart(self):
        # This is a simplified version. The full implementation would be here.
        self.ax_price.clear()
        sym = self.symbol_var.get()
        tf = self.tf_var.get()
        self.ax_price.set_title(f"{sym} - {tf}")
        # ... (Full drawing logic)
        self.canvas.draw_idle()
