# -*- coding: utf-8 -*-
"""
Quản lý tab biểu đồ trong giao diện người dùng.

Hiển thị dữ liệu giá, thông tin tài khoản, các lệnh đang mở và lịch sử giao dịch.
"""

from __future__ import annotations

import logging
import tkinter as tk
from datetime import datetime
from tkinter import ttk
from typing import TYPE_CHECKING, Any, Optional, Tuple, cast

import MetaTrader5 as mt5_lib
from APP.ui.utils import ui_builder

# Cast mt5 to Any to suppress pyright errors for missing type stubs
mt5: Any = mt5_lib

# Khởi tạo logger
logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from APP.ui.app_ui import AppUI
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    from matplotlib.backends._backend_tk import NavigationToolbar2Tk
else:
    try:
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
        from matplotlib.backends._backend_tk import NavigationToolbar2Tk
    except ImportError:
        class Figure: pass
        class FigureCanvasTkAgg: pass
        class NavigationToolbar2Tk: pass


class ChartTab:
    """
    Lớp ChartTab quản lý tab biểu đồ trong giao diện người dùng.
    """

    def __init__(self, app: "AppUI", notebook: ttk.Notebook):
        """
        Khởi tạo một đối tượng ChartTab.
        """
        logger.debug("Bắt đầu hàm __init__ của ChartTab.")
        self.app = app
        self.root = app.root

        self._init_vars()

        self.tab = ttk.Frame(notebook, padding=8)
        notebook.add(self.tab, text="Chart")

        self.tab.rowconfigure(1, weight=1)
        self.tab.columnconfigure(0, weight=2)
        self.tab.columnconfigure(1, weight=1)

        self._build_controls()
        self._build_chart_area()
        self._build_right_panel()
        self._build_bottom_grids()

        self.root.after(200, self.start)
        self._redraw_safe()
        logger.debug("Kết thúc hàm __init__ của ChartTab.")

    def _init_vars(self):
        """Khởi tạo các biến Tkinter và trạng thái."""
        logger.debug("Bắt đầu hàm _init_vars.")
        self.symbol_var = tk.StringVar(value="XAUUSD")
        self.tf_var = tk.StringVar(value="M1")
        self.n_candles_var = tk.IntVar(value=100)
        self.refresh_secs_var = tk.IntVar(value=1)
        self.chart_type_var = tk.StringVar(value="Nến")
        self._after_job: Optional[str] = None
        self._running = False
        # Biến cho biểu đồ
        self.fig: Optional[Figure] = None
        self.ax_price: Optional[Any] = None  # AxesSubplot is not easily typed here
        self.canvas: Optional[FigureCanvasTkAgg] = None
        self.toolbar: Optional[NavigationToolbar2Tk] = None
        # Account panel vars
        self.acc_balance = tk.StringVar(value="-")
        self.acc_equity = tk.StringVar(value="-")
        self.acc_margin = tk.StringVar(value="-")
        self.acc_leverage = tk.StringVar(value="-")
        self.acc_currency = tk.StringVar(value="-")
        self.acc_status = tk.StringVar(value="Chưa kết nối MT5")
        # No-Trade panel vars
        self.nt_session_gate = tk.StringVar(value="-")
        self.nt_reasons = tk.StringVar(value="")
        self.nt_events = tk.StringVar(value="")
        logger.debug("Kết thúc hàm _init_vars.")

    def _build_controls(self):
        """Xây dựng bảng điều khiển trên cùng."""
        logger.debug("Bắt đầu hàm _build_controls.")
        ctrl = ttk.Frame(self.tab)
        ctrl.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        for i in range(12):
            ctrl.columnconfigure(i, weight=0)
        ctrl.columnconfigure(11, weight=1)

        ttk.Label(ctrl, text="Ký hiệu:").grid(row=0, column=0, sticky="w")
        self.cbo_symbol = ttk.Combobox(ctrl, width=16, textvariable=self.symbol_var, state="normal", values=[])
        self.cbo_symbol.grid(row=0, column=1, sticky="w", padx=(4, 10))
        self.cbo_symbol.bind("<<ComboboxSelected>>", lambda e: self._redraw_safe())
        self._populate_symbol_list()

        ttk.Label(ctrl, text="Khung:").grid(row=0, column=2, sticky="w")
        self.cbo_tf = ttk.Combobox(
            ctrl, width=6, state="readonly", values=["M1", "M5", "M15", "H1", "H4", "D1"], textvariable=self.tf_var
        )
        self.cbo_tf.grid(row=0, column=3, sticky="w", padx=(4, 10))
        self.cbo_tf.bind("<<ComboboxSelected>>", lambda e: self._redraw_safe())

        ttk.Label(ctrl, text="Số nến:").grid(row=0, column=4, sticky="w")
        ttk.Spinbox(ctrl, from_=50, to=5000, textvariable=self.n_candles_var, width=8, command=self._redraw_safe)\
            .grid(row=0, column=5, sticky="w", padx=(4, 10))

        ttk.Label(ctrl, text="Kiểu:").grid(row=0, column=6, sticky="w")
        self.cbo_chart_type = ttk.Combobox(
            ctrl, width=8, state="readonly", values=["Đường", "Nến"], textvariable=self.chart_type_var
        )
        self.cbo_chart_type.grid(row=0, column=7, sticky="w", padx=(4, 10))
        self.cbo_chart_type.bind("<<ComboboxSelected>>", lambda e: self._redraw_safe())

        ttk.Label(ctrl, text="Làm mới (s):").grid(row=0, column=8, sticky="w")
        ttk.Spinbox(ctrl, from_=1, to=3600, textvariable=self.refresh_secs_var, width=6)\
            .grid(row=0, column=9, sticky="w", padx=(4, 10))
        
        ttk.Button(ctrl, text="Tải file OHLC (.csv)...", command=self.load_data).grid(row=0, column=10, sticky="w", padx=(10, 0))
        logger.debug("Kết thúc hàm _build_controls.")
    
    def load_data(self):
        """Tải dữ liệu từ file CSV."""
        from tkinter import filedialog
        filepath = filedialog.askopenfilename(
            title="Chọn file OHLC (.csv)",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
        )
        if filepath:
            logger.info(f"Đã chọn file: {filepath}")
            # Placeholder for data loading logic
            ui_builder.show_message(title="Thông báo", message=f"Đã chọn file:\n{filepath}")

    def _build_chart_area(self):
        """Xây dựng khu vực hiển thị biểu đồ."""
        chart_wrap = ttk.Frame(self.tab)
        chart_wrap.grid(row=1, column=0, sticky="nsew", padx=(0, 6))
        chart_wrap.rowconfigure(1, weight=1)
        chart_wrap.columnconfigure(0, weight=1)

        try:
            from matplotlib.figure import Figure
            from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
            from matplotlib.backends._backend_tk import NavigationToolbar2Tk
        except ImportError:
            ttk.Label(chart_wrap, text="Không có Matplotlib").grid(row=0, column=0, sticky="w")
            logger.warning("Matplotlib hoặc FigureCanvasTkAgg không có sẵn.")
            return

        self.fig = Figure(figsize=(6, 4), dpi=100, constrained_layout=False)
        self.ax_price = self.fig.add_subplot(1, 1, 1)
        self.canvas = FigureCanvasTkAgg(self.fig, master=chart_wrap)
        self.canvas.get_tk_widget().grid(row=1, column=0, sticky="nsew")
        logger.debug("Đã khởi tạo Figure và FigureCanvasTkAgg.")

        tb_frame = ttk.Frame(chart_wrap)
        tb_frame.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        self.toolbar = NavigationToolbar2Tk(self.canvas, tb_frame)
        self.toolbar.update()
        logger.debug("Đã khởi tạo NavigationToolbar2Tk.")

    def _build_right_panel(self):
        """Xây dựng cột bên phải chứa các panel thông tin."""
        logger.debug("Bắt đầu hàm _build_right_panel.")
        right_col = ttk.Frame(self.tab)
        right_col.grid(row=1, column=1, sticky="nsew")
        right_col.columnconfigure(0, weight=1)
        self._build_account_panel(right_col)
        self._build_notrade_panel(right_col)
        logger.debug("Kết thúc hàm _build_right_panel.")

    def _build_account_panel(self, parent: ttk.Frame):
        """Xây dựng panel thông tin tài khoản."""
        acc_box = ttk.LabelFrame(parent, text="Thông tin tài khoản", padding=8)
        acc_box.grid(row=0, column=0, sticky="nsew")
        acc_box.columnconfigure(1, weight=1)
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
        logger.debug("Đã khởi tạo panel thông tin tài khoản.")

    def _build_notrade_panel(self, parent: ttk.Frame):
        """Xây dựng panel điều kiện không giao dịch."""
        nt_box = ttk.LabelFrame(parent, text="Không giao dịch", padding=8)
        nt_box.grid(row=1, column=0, sticky="nsew", pady=(6, 0))
        nt_box.columnconfigure(1, weight=1)
        ttk.Label(nt_box, text="Phiên giao dịch:").grid(row=0, column=0, sticky="w")
        ttk.Label(nt_box, textvariable=self.nt_session_gate).grid(row=0, column=1, sticky="e")
        ttk.Label(nt_box, text="Lý do:").grid(row=1, column=0, sticky="w", pady=(4, 0))
        ttk.Label(nt_box, textvariable=self.nt_reasons, wraplength=260, justify="left").grid(row=2, column=0, columnspan=2, sticky="w")
        ttk.Label(nt_box, text="Sự kiện sắp tới:").grid(row=3, column=0, sticky="w", pady=(6, 0))
        ttk.Label(nt_box, textvariable=self.nt_events, wraplength=260, justify="left").grid(row=4, column=0, columnspan=2, sticky="w")
        logger.debug("Đã khởi tạo panel No-Trade.")

    def _build_bottom_grids(self):
        """Xây dựng các bảng dữ liệu ở dưới cùng."""
        logger.debug("Bắt đầu hàm _build_bottom_grids.")
        grids = ttk.Frame(self.tab)
        grids.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=(6, 0))
        grids.columnconfigure(0, weight=1)
        grids.columnconfigure(1, weight=1)
        grids.rowconfigure(0, weight=1)
        self._build_positions_grid(grids)
        self._build_history_grid(grids)
        logger.debug("Kết thúc hàm _build_bottom_grids.")

    def _build_positions_grid(self, parent: ttk.Frame):
        """Xây dựng bảng các lệnh đang mở."""
        pos_box = ttk.LabelFrame(parent, text="Lệnh đang mở", padding=6)
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
        logger.debug("Đã khởi tạo bảng lệnh đang mở.")

    def _build_history_grid(self, parent: ttk.Frame):
        """Xây dựng bảng lịch sử giao dịch."""
        his_box = ttk.LabelFrame(parent, text="Lịch sử (deals gần nhất)", padding=6)
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
        logger.debug("Đã khởi tạo bảng lịch sử giao dịch.")

    def start(self) -> None:
        """Bắt đầu quá trình làm mới biểu đồ và thông tin định kỳ."""
        logger.debug("Bắt đầu hàm start.")
        if self._running:
            logger.debug("ChartTab đã chạy, bỏ qua.")
            return
        try:
            self._ensure_mt5(want_account=False)
        except Exception as e:
            logger.warning(f"Lỗi khi đảm bảo kết nối MT5 trong start: {e}")
        self._running = True
        self._tick()
        logger.debug("Kết thúc hàm start.")

    def stop(self) -> None:
        """Dừng quá trình làm mới biểu đồ và thông tin."""
        logger.debug("Bắt đầu hàm stop.")
        self._running = False
        if self._after_job:
            self.root.after_cancel(self._after_job)
            self._after_job = None
        logger.debug("Kết thúc hàm stop.")

    def _populate_symbol_list(self) -> None:
        """Điền danh sách các ký hiệu giao dịch vào combobox."""
        logger.debug("Bắt đầu hàm _populate_symbol_list.")
        try:
            from APP.services import mt5_service
            names = mt5_service.get_all_symbols()
            if names and self.cbo_symbol:
                self.cbo_symbol["values"] = names
                pref = self.app.mt5_symbol_var.get()
                if pref and pref in names:
                    self.symbol_var.set(pref)
                elif "XAUUSD" in names:
                    self.symbol_var.set("XAUUSD")
            logger.debug(f"Đã populate {len(names)} symbols.")
        except Exception as e:
            logger.warning(f"Lỗi khi populate symbol list: {e}")
        logger.debug("Kết thúc _populate_symbol_list.")

    def _mt5_tf(self, tf_str: str) -> Optional[int]:
        """Chuyển đổi chuỗi khung thời gian thành mã của MT5."""
        logger.debug(f"Bắt đầu hàm _mt5_tf cho chuỗi: '{tf_str}'")
        try:
            mapping = {
                "M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15,
                "H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4, "D1": mt5.TIMEFRAME_D1,
            }
            return mapping.get(tf_str.upper())
        except ImportError as e:
            logger.warning(f"Không thể import MetaTrader5 trong _mt5_tf: {e}")
            return None

    def _ensure_mt5(self, *, want_account: bool = True) -> bool:
        """Đảm bảo kết nối với terminal MetaTrader 5."""
        logger.debug(f"Bắt đầu hàm _ensure_mt5. Want account: {want_account}")
        try:
            from APP.services import mt5_service
            if not mt5_service.is_connected():
                self.acc_status.set("MT5 chưa kết nối.")
                return False
            if want_account and mt5.account_info() is None:
                self.acc_status.set("MT5: chưa đăng nhập.")
                return False
            self.acc_status.set("Kết nối MT5 OK")
            return True
        except Exception as e:
            self.acc_status.set(f"Lỗi MT5: {e}")
            logger.error(f"Lỗi kết nối MT5 trong _ensure_mt5: {e}")
            return False

    def _rates_to_df(self, symbol: str, tf_code: Any, count: int) -> Tuple[Any, Optional[str]]:
        """Lấy dữ liệu nến từ MT5 và chuyển đổi thành DataFrame."""
        logger.debug(f"Bắt đầu hàm _rates_to_df cho symbol: {symbol}, tf_code: {tf_code}, count: {count}")
        try:
            import pandas as pd
            rates = mt5.copy_rates_from_pos(symbol, tf_code, 0, count)
            if rates is None:
                return None, f"Không có dữ liệu rates cho {symbol}"
            df = pd.DataFrame(rates)
            df['time'] = pd.to_datetime(df['time'], unit='s')
            df = df.set_index('time')
            return df, None
        except Exception as e:
            logger.error(f"Lỗi ngoại lệ trong _rates_to_df: {e}")
            return None, f"Lỗi ngoại lệ: {e}"

    def _style(self) -> None:
        """Cấu hình kiểu hiển thị cho biểu đồ matplotlib."""
        try:
            import matplotlib as mpl
            mpl.rcParams.update({"axes.grid": True, "grid.alpha": 0.25})
        except Exception as e:
            logger.warning(f"Lỗi khi cập nhật style matplotlib: {e}")

    def _fmt(self, x: Any, digits: int = 5) -> str:
        """Định dạng một giá trị số thành chuỗi."""
        logger.debug(f"Bắt đầu hàm _fmt với x={x}, digits={digits}.")
        try:
            return f"{float(x):.{int(digits)}f}"
        except (ValueError, TypeError):
            return str(x)

    def _update_account_info(self, symbol: str) -> None:
        """Cập nhật thông tin tài khoản MT5 trên UI."""
        logger.debug(f"Bắt đầu hàm _update_account_info cho symbol: {symbol}")
        try:
            ai = mt5.account_info()
            if ai:
                self.acc_balance.set(f"{ai.balance:.2f}")
                self.acc_equity.set(f"{ai.equity:.2f}")
                self.acc_margin.set(f"{ai.margin_free:.2f}")
                self.acc_leverage.set(str(getattr(ai, "leverage", "-")))
                self.acc_currency.set(getattr(ai, "currency", "-"))
                self.acc_status.set("Kết nối MT5 OK")
            else:
                self.acc_status.set("MT5: Chưa đăng nhập")
        except Exception as e:
            logger.error(f"Lỗi khi cập nhật thông tin tài khoản: {e}")

    def _fill_positions_table(self, symbol: str) -> None:
        """Điền dữ liệu các lệnh đang mở vào bảng."""
        logger.debug(f"Bắt đầu hàm _fill_positions_table cho symbol: {symbol}")
        try:
            poss = mt5.positions_get(symbol=symbol) or []
            if self.tree_pos:
                self.tree_pos.delete(*self.tree_pos.get_children())
                for p in poss:
                    typ = "BUY" if p.type == 0 else "SELL"
                    self.tree_pos.insert("", "end", values=(
                        p.ticket, typ, f"{p.volume:.2f}",
                        self._fmt(p.price_open), self._fmt(p.sl), self._fmt(p.tp), f"{p.profit:.2f}"
                    ))
        except Exception as e:
            logger.error(f"Lỗi khi điền bảng lệnh đang mở: {e}")

    def _fill_history_table(self, symbol: str) -> None:
        """Điền dữ liệu lịch sử giao dịch vào bảng."""
        logger.debug(f"Bắt đầu hàm _fill_history_table cho symbol: {symbol}")
        try:
            import datetime as dt
            if self.tree_his:
                self.tree_his.delete(*self.tree_his.get_children())
                now = dt.datetime.now()
                deals = mt5.history_deals_get(now.replace(hour=0, minute=0, second=0), now, group=f"*{symbol}*") or []
                for d in deals[-100:]:
                    self.tree_his.insert("", "end", values=(
                        d.time, d.ticket, d.type, d.volume, d.price, d.profit
                    ))
        except Exception as e:
            logger.error(f"Lỗi khi điền bảng lịch sử giao dịch: {e}")

    def _draw_chart(self) -> None:
        """Vẽ biểu đồ giá."""
        logger.debug("Bắt đầu hàm _draw_chart.")

        if not self.ax_price or not self.canvas:
            logger.debug("ax_price hoặc canvas chưa được khởi tạo. Bỏ qua vẽ biểu đồ.")
            return

        sym = self.symbol_var.get().strip()
        try:
            from APP.services import mt5_service
        except ImportError as e:
            logger.error(f"Lỗi import trong _draw_chart: {e}")
            self.ax_price.clear()
            self.ax_price.set_title(f"Lỗi import: {e}")
            self.canvas.draw_idle()
            return

        if not mt5_service.is_connected():
            self.ax_price.clear()
            self.ax_price.set_title("MT5 chưa sẵn sàng")
            self.canvas.draw_idle()
            return

        tf_code = self._mt5_tf(self.tf_var.get())
        cnt = self.n_candles_var.get() or 100
        df, err_msg = self._rates_to_df(sym, tf_code, cnt)

        if df is None or df.empty:
            self.ax_price.clear()
            self.ax_price.set_title(err_msg or "Không có dữ liệu")
            self.canvas.draw_idle()
            return

        self.ax_price.clear()
        self._plot_price_data(df)
        self._plot_trade_objects(sym)

        self.ax_price.set_title(f"{sym}  •  {self.tf_var.get()}  •  {len(df)} bars")
        if self.fig:
            self.fig.subplots_adjust(right=0.75)
        self.canvas.draw_idle()
        logger.debug("Kết thúc hàm _draw_chart.")

    def _plot_price_data(self, df):
        """Vẽ dữ liệu giá (nến hoặc đường) lên biểu đồ."""
        if not self.ax_price:
            return
        try:
            import matplotlib.dates as mdates
            kind = self.chart_type_var.get().strip()
            if kind == "Nến":
                try:
                    from mplfinance.original_flavor import candlestick_ohlc
                    import numpy as np
                    xs = mdates.date2num(df.index.to_pydatetime())
                    ohlc = np.column_stack((xs, df["open"], df["high"], df["low"], df["close"]))
                    step = np.median(np.diff(xs)) if len(xs) > 1 else (1.0 / (24 * 60))
                    width = step * 0.7
                    candlestick_ohlc(self.ax_price, ohlc, width=float(width), colorup="#22c55e", colordown="#ef4444", alpha=0.9)
                    self.ax_price.xaxis_date()
                except ImportError:
                    logger.warning("Không thể import candlestick_ohlc, vẽ biểu đồ đường.")
                    self.ax_price.plot(df.index, df["close"], color="#0ea5e9", lw=1.2)
            else:
                self.ax_price.plot(df.index, df["close"], color="#0ea5e9", lw=1.2)
            self.ax_price.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
        except Exception as e:
            logger.error(f"Lỗi khi vẽ dữ liệu giá: {e}")

    def _plot_trade_objects(self, sym: str):
        """Vẽ các đối tượng giao dịch (lệnh, giá) lên biểu đồ."""
        if not self.ax_price:
            return
        try:
            info = mt5.symbol_info(sym)
            digits = info.digits if info else 2
            
            positions = mt5.positions_get(symbol=sym) or []
            for p in positions:
                col = "#22c55e" if p.type == 0 else "#ef4444"
                self.ax_price.axhline(p.price_open, color=col, ls="--", lw=1.0, alpha=0.95)
                if p.sl: self.ax_price.axhline(p.sl, color="#ef4444", ls=":", lw=1.0, alpha=0.85)
                if p.tp: self.ax_price.axhline(p.tp, color="#22c55e", ls=":", lw=1.0, alpha=0.85)
                label = f"{'BUY' if p.type==0 else 'SELL'} {p.volume:.2f} @{self._fmt(p.price_open, digits)}"
                self.ax_price.text(1.01, p.price_open, " " + label, va="center", color=col, fontsize=8, transform=self.ax_price.get_yaxis_transform())
            
            orders = mt5.orders_get(symbol=sym) or []
            for o in orders:
                pend_col = "#8b5cf6"
                self.ax_price.axhline(o.price_open, color=pend_col, ls="--", lw=1.1, alpha=0.95)
                txt = f"PEND {o.type_description} {o.volume_current:.2f} @{self._fmt(o.price_open, digits)}"
                self.ax_price.text(1.01, o.price_open, " " + txt, va="center", color=pend_col, fontsize=8, transform=self.ax_price.get_yaxis_transform())
                if o.sl: self.ax_price.axhline(o.sl, color="#ef4444", ls=":", lw=1.0, alpha=0.85)
                if o.tp: self.ax_price.axhline(o.tp, color="#22c55e", ls=":", lw=1.0, alpha=0.85)

            tick = mt5.symbol_info_tick(sym)
            if tick:
                current_price = tick.bid
                self.ax_price.axhline(current_price, color='black', ls='--', lw=0.8, alpha=0.9)
                self.ax_price.text(1.01, current_price, f" {self._fmt(current_price, digits)}",
                                   va="center", color='black', fontsize=8,
                                   bbox=dict(facecolor='white', alpha=0.5, edgecolor='none', boxstyle='round,pad=0.1'),
                                   transform=self.ax_price.get_yaxis_transform())
        except Exception as e:
            logger.error(f"Lỗi khi vẽ các đối tượng giao dịch: {e}")

    def _redraw_safe(self) -> None:
        """Vẽ lại toàn bộ tab một cách an toàn."""
        logger.debug("Bắt đầu hàm _redraw_safe.")
        try:
            self._draw_chart()
        except Exception as e:
            logger.error(f"Lỗi khi vẽ biểu đồ an toàn: {e}")
            try:
                if self.ax_price and self.canvas:
                    self.ax_price.clear()
                    self.ax_price.set_title(f"Chart error: {e}")
                    self.canvas.draw_idle()
            except Exception: pass

        sym = self.symbol_var.get().strip()
        try:
            self._update_account_info(sym)
            self._fill_positions_table(sym)
            self._fill_history_table(sym)
        except Exception as e:
            logger.error(f"Lỗi khi cập nhật thông tin: {e}")

        try:
            self._update_notrade_panel()
        except Exception as e:
            logger.error(f"Lỗi khi cập nhật panel No-Trade: {e}")
        logger.debug("Kết thúc hàm _redraw_safe.")

    def _tick(self) -> None:
        """Hàm tick được gọi định kỳ để làm mới dữ liệu."""
        logger.debug("Bắt đầu hàm _tick.")
        if not self._running:
            return

        self._redraw_safe()
        secs = max(1, self.refresh_secs_var.get() or 5)
        self._after_job = self.root.after(secs * 1000, self._tick)

    def _compute_sessions_today(self, symbol: str) -> dict:
        """Tính toán các phiên giao dịch trong ngày."""
        try:
            from APP.services import mt5_service
            return mt5_service.session_ranges_today(m1_rates=None) or {}
        except Exception as e:
            logger.error(f"Lỗi khi tính toán sessions today: {e}")
            return {}

    def _allowed_session_now(self, ss: dict) -> bool:
        """Kiểm tra xem phiên hiện tại có được phép giao dịch không."""
        if not self.app.run_config:
            return True  # Mặc định là cho phép nếu chưa có cấu hình
        try:
            import datetime
            now = datetime.datetime.now().strftime("%H:%M")
            def _in(r):
                return bool(r and r.get("start") and r.get("end") and r["start"] <= now < r["end"])

            config = self.app.run_config.no_trade
            ok = False
            if config.allow_session_asia: ok = ok or _in(ss.get("asia"))
            if config.allow_session_london: ok = ok or _in(ss.get("london"))
            if config.allow_session_ny: ok = ok or _in(ss.get("newyork_am")) or _in(ss.get("newyork_pm"))
            
            if not any([config.allow_session_asia, config.allow_session_london, config.allow_session_ny]):
                return True
            return ok
        except Exception as e:
            logger.error(f"Lỗi khi kiểm tra phiên giao dịch: {e}")
            return True

    def _update_notrade_panel(self) -> None:
        """Cập nhật panel "Không giao dịch"."""
        logger.debug("Bắt đầu hàm _update_notrade_panel.")
        # This panel is now mostly decorative as the core logic is in the worker.
        # We can provide some basic info.
        self.nt_session_gate.set("-")
        self.nt_reasons.set("(Kiểm tra trong worker)")
        
        try:
            # We can still show upcoming news
            from APP.services import news_service
            sym = self.symbol_var.get().strip()
            from APP.services import news_service
            from APP.utils.general_utils import format_timedelta

            # Sử dụng cache của app để tránh gọi API liên tục
            ok, why, events, fetch_ts = news_service.within_news_window_cached(
                symbol=sym,
                minutes_before=0, # Chỉ cần lấy events, không cần check window
                minutes_after=0,
                cache_events=self.app.news_events,
                cache_fetch_time=self.app.news_fetch_time,
                ttl_sec=600 # Cache 10 phút
            )
            self.app.news_events = events
            self.app.news_fetch_time = fetch_ts

            next_events = news_service.next_events_for_symbol(events, sym, limit=3)
            
            now = datetime.now().astimezone()
            events_fmt = []
            for ev in next_events:
                remaining = ev['when'] - now
                rem_str = format_timedelta(remaining)
                title = ev.get('title', 'N/A')
                curr = ev.get('curr', '')
                events_fmt.append(f"• [{curr}] {title} (trong {rem_str})")

            self.nt_events.set("\n".join(events_fmt) if events_fmt else "(không có sự kiện quan trọng)")
        except Exception as e:
            self.nt_events.set("(error)")
            logger.error(f"Lỗi khi cập nhật sự kiện tin tức: {e}")
        logger.debug("Kết thúc hàm _update_notrade_panel.")
