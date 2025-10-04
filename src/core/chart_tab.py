from __future__ import annotations

import tkinter as tk
from tkinter import ttk
import logging # Thêm import logging
from typing import Any, Tuple, Optional

logger = logging.getLogger(__name__) # Khởi tạo logger

try:
    # Optional: Only needed when the Chart tab is used
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
except Exception as e:  # pragma: no cover - optional UI deps
    Figure = None  # type: ignore
    FigureCanvasTkAgg = None  # type: ignore
    logger.warning(f"Không thể import matplotlib modules: {e}. Tab Chart sẽ bị vô hiệu hóa.")


class ChartTabTV:
    """
    Lớp ChartTabTV quản lý tab biểu đồ trong giao diện người dùng.
    Nó hiển thị dữ liệu giá, thông tin tài khoản, các lệnh đang mở và lịch sử giao dịch.
    Phụ thuộc vào MetaTrader5 và matplotlib (nếu có); được khởi tạo bởi ứng dụng chính
    chỉ khi các phụ thuộc này có sẵn.
    """

    def __init__(self, app: Any, notebook: ttk.Notebook):
        """
        Khởi tạo một đối tượng ChartTabTV.

        Args:
            app: Đối tượng ứng dụng chính chứa các biến và phương thức cần thiết.
            notebook: Đối tượng ttk.Notebook mà tab biểu đồ sẽ được thêm vào.
        """
        logger.debug("Bắt đầu khởi tạo ChartTabTV.")
        self.app = app
        self.root = app.root

        self.symbol_var = tk.StringVar(value="XAUUSD")
        self.tf_var = tk.StringVar(value="M1")
        self.n_candles_var = tk.IntVar(value=100)
        self.refresh_secs_var = tk.IntVar(value=1)
        # Kiểu hiển thị biểu đồ: "Đường" hoặc "Nến"
        self.chart_type_var = tk.StringVar(value="Nến")

        self._after_job = None
        self._running = False

        self.tab = ttk.Frame(notebook, padding=8)
        notebook.add(self.tab, text="Chart")

        self.tab.rowconfigure(1, weight=1)
        self.tab.columnconfigure(0, weight=2)
        self.tab.columnconfigure(1, weight=1)

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

        self.root.after(200, self.start)

        chart_wrap = ttk.Frame(self.tab)
        chart_wrap.grid(row=1, column=0, sticky="nsew", padx=(0, 6))
        chart_wrap.rowconfigure(1, weight=1)
        chart_wrap.columnconfigure(0, weight=1)

        if Figure is None or FigureCanvasTkAgg is None:
            # Minimal fallback if matplotlib is not present
            label = ttk.Label(chart_wrap, text="Không có Matplotlib")
            label.grid(row=0, column=0, sticky="w")
            logger.warning("Matplotlib hoặc FigureCanvasTkAgg không có sẵn.")
            return

        self.fig = Figure(figsize=(6, 4), dpi=100, constrained_layout=False)
        self.ax_price = self.fig.add_subplot(1, 1, 1)
        self.canvas = FigureCanvasTkAgg(self.fig, master=chart_wrap)
        self.canvas.get_tk_widget().grid(row=1, column=0, sticky="nsew")
        logger.debug("Đã khởi tạo Figure và FigureCanvasTkAgg.")

        try:
            from matplotlib.backends.backend_tkagg import NavigationToolbar2Tk  # type: ignore
            tb_frame = ttk.Frame(chart_wrap)
            tb_frame.grid(row=0, column=0, sticky="ew", pady=(0, 4))
            self.toolbar = NavigationToolbar2Tk(self.canvas, tb_frame)
            self.toolbar.update()
            logger.debug("Đã khởi tạo NavigationToolbar2Tk.")
        except Exception as e:
            self.toolbar = None
            logger.warning(f"Không thể khởi tạo NavigationToolbar2Tk: {e}")

        # Right column wrapper to stack panels (Account + No-Trade)
        right_col = ttk.Frame(self.tab)
        right_col.grid(row=1, column=1, sticky="nsew")
        for i in range(1):
            right_col.columnconfigure(i, weight=1)

        acc_box = ttk.LabelFrame(right_col, text="Thông tin tài khoản", padding=8)
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
        logger.debug("Đã khởi tạo panel thông tin tài khoản.")

        grids = ttk.Frame(self.tab)
        grids.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=(6, 0))
        grids.columnconfigure(0, weight=1)
        grids.columnconfigure(1, weight=1)
        grids.rowconfigure(0, weight=1)

        pos_box = ttk.LabelFrame(grids, text="Lệnh đang mở", padding=6)
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

        his_box = ttk.LabelFrame(grids, text="Lịch sử (deals gần nhất)", padding=6)
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

        # --- No-Trade panel ---
        self.nt_session_gate = tk.StringVar(value="-")
        self.nt_reasons = tk.StringVar(value="")
        self.nt_events = tk.StringVar(value="")

        nt_box = ttk.LabelFrame(right_col, text="Không giao dịch", padding=8)
        nt_box.grid(row=1, column=0, sticky="nsew", pady=(6, 0))
        nt_box.columnconfigure(0, weight=1)

        ttk.Label(nt_box, text="Phiên giao dịch:").grid(row=0, column=0, sticky="w")
        self.lbl_nt_session = ttk.Label(nt_box, textvariable=self.nt_session_gate)
        self.lbl_nt_session.grid(row=0, column=1, sticky="e")

        ttk.Label(nt_box, text="Lý do:").grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.lbl_nt_reasons = ttk.Label(nt_box, textvariable=self.nt_reasons, wraplength=260, justify="left")
        self.lbl_nt_reasons.grid(row=2, column=0, columnspan=2, sticky="w")

        ttk.Label(nt_box, text="Sự kiện sắp tới:").grid(row=3, column=0, sticky="w", pady=(6, 0))
        self.lbl_nt_events = ttk.Label(nt_box, textvariable=self.nt_events, wraplength=260, justify="left")
        self.lbl_nt_events.grid(row=4, column=0, columnspan=2, sticky="w")
        logger.debug("Đã khởi tạo panel No-Trade.")

        self._redraw_safe()
        logger.debug("Kết thúc khởi tạo ChartTabTV.")

    def start(self):
        """
        Bắt đầu quá trình làm mới biểu đồ và thông tin định kỳ.
        """
        logger.debug("Bắt đầu hàm start.")
        if self._running:
            logger.debug("ChartTabTV đã chạy, bỏ qua.")
            return
        try:
            self._ensure_mt5(want_account=False)
            logger.debug("Đã đảm bảo kết nối MT5 (không cần thông tin tài khoản).")
        except Exception as e:
            logger.warning(f"Lỗi khi đảm bảo kết nối MT5 trong start: {e}")
            pass
        self._running = True
        self._tick()
        logger.debug("Kết thúc hàm start.")

    def stop(self):
        """
        Dừng quá trình làm mới biểu đồ và thông tin.
        """
        logger.debug("Bắt đầu hàm stop.")
        self._running = False
        if self._after_job:
            self.root.after_cancel(self._after_job)
            self._after_job = None
            logger.debug("Đã hủy tác vụ _after_job.")
        logger.debug("Kết thúc hàm stop.")

    def _populate_symbol_list(self):
        """
        Điền danh sách các ký hiệu giao dịch vào combobox.
        """
        logger.debug("Bắt đầu _populate_symbol_list.")
        try:
            if not self._ensure_mt5(want_account=False):
                logger.warning("Không thể populate symbol list vì MT5 chưa sẵn sàng.")
                return
            import MetaTrader5 as mt5
            syms = mt5.symbols_get()
            names = sorted([s.name for s in syms]) if syms else []
            if names:
                self.cbo_symbol["values"] = names
                try:
                    pref = getattr(self.app, "mt5_symbol_var", None).get().strip() if getattr(self.app, "mt5_symbol_var", None) else None
                except Exception:
                    pref = None
                if pref and pref in names:
                    self.symbol_var.set(pref)
                    logger.debug(f"Đã đặt symbol ưu tiên: {pref}")
                elif "XAUUSD" in names:
                    self.symbol_var.set("XAUUSD")
                    logger.debug("Đã đặt symbol mặc định: XAUUSD")
            logger.debug(f"Đã populate {len(names)} symbols.")
        except Exception as e:
            logger.warning(f"Lỗi khi populate symbol list: {e}")
            pass
        logger.debug("Kết thúc _populate_symbol_list.")

    def _mt5_tf(self, tf_str: str):
        """
        Chuyển đổi chuỗi khung thời gian (ví dụ: "M1", "H1") thành mã khung thời gian của MT5.

        Args:
            tf_str: Chuỗi khung thời gian.

        Returns:
            Mã khung thời gian của MT5 hoặc None nếu không thể chuyển đổi.
        """
        logger.debug(f"Bắt đầu _mt5_tf cho chuỗi: '{tf_str}'")
        try:
            import MetaTrader5 as mt5
        except Exception as e:
            logger.warning(f"Không thể import MetaTrader5 trong _mt5_tf: {e}")
            return None
        mapping = {
            "M1": mt5.TIMEFRAME_M1,
            "M5": mt5.TIMEFRAME_M5,
            "M15": mt5.TIMEFRAME_M15,
            "H1": mt5.TIMEFRAME_H1,
            "H4": mt5.TIMEFRAME_H4,
            "D1": mt5.TIMEFRAME_D1,
        }
        result = mapping.get(tf_str.upper(), mt5.TIMEFRAME_M5)
        logger.debug(f"Kết thúc _mt5_tf. Mã khung thời gian: {result}")
        return result

    def _ensure_mt5(self, *, want_account: bool = True) -> bool:
        """
        Đảm bảo kết nối với terminal MetaTrader 5 đã được khởi tạo.

        Args:
            want_account: Nếu True, sẽ kiểm tra thông tin tài khoản.

        Returns:
            True nếu MT5 đã được khởi tạo và sẵn sàng, ngược lại là False.
        """
        logger.debug(f"Bắt đầu _ensure_mt5. Want account: {want_account}")
        try:
            import MetaTrader5 as mt5
        except Exception as e:
            self.acc_status.set("Chưa cài MetaTrader5 (pip install MetaTrader5)")
            logger.warning(f"Không thể import MetaTrader5 trong _ensure_mt5: {e}")
            return False

        # If app says it's initialized, trust it but verify account if needed
        if getattr(self.app, "mt5_initialized", False):
            logger.debug("MT5 đã được app báo là initialized.")
            if want_account and mt5.account_info() is None:
                self.acc_status.set("MT5: chưa đăng nhập (account_info=None)")
                logger.warning("MT5 initialized nhưng không lấy được account info.")
                return False
            logger.debug("MT5 initialized và account info OK (nếu cần).")
            return True

        # If not initialized, try to initialize directly here
        try:
            if not mt5.initialize():
                self.acc_status.set(f"MT5 init failed: {mt5.last_error()}")
                logger.warning(f"MT5 initialize() thất bại: {mt5.last_error()}")
                return False
            # If successful, update the app's state flag
            if hasattr(self.app, "mt5_initialized"):
                self.app.mt5_initialized = True
                logger.debug("MT5 initialize() thành công, đã cập nhật trạng thái app.")
        except Exception as e:
            self.acc_status.set(f"MT5 connect error: {e}")
            logger.error(f"Lỗi kết nối MT5 trong _ensure_mt5: {e}")
            return False

        # Re-check account info after trying to connect
        if want_account and mt5.account_info() is None:
            self.acc_status.set("MT5: chưa đăng nhập (account_info=None)")
            logger.warning("MT5 initialize() thành công nhưng không lấy được account info sau đó.")
            return False

        logger.debug("Kết thúc _ensure_mt5. Kết nối MT5 OK.")
        return True

    def _rates_to_df(self, symbol: str, tf_code: Any, count: int) -> Tuple[Any, Optional[str]]:
        """
        Lấy dữ liệu nến từ MT5 và chuyển đổi thành DataFrame của pandas.

        Args:
            symbol: Ký hiệu giao dịch.
            tf_code: Mã khung thời gian của MT5.
            count: Số lượng nến cần lấy.

        Returns:
            Một tuple chứa DataFrame và thông báo lỗi (nếu có).
        """
        logger.debug(f"Bắt đầu _rates_to_df cho symbol: {symbol}, tf_code: {tf_code}, count: {count}")
        try:
            import MetaTrader5 as mt5
            import pandas as pd
        except Exception as e:
            logger.error(f"Không thể import MetaTrader5 hoặc pandas trong _rates_to_df: {e}")
            return None, "Không thể import MetaTrader5 hoặc pandas"
        try:
            # Normalize inputs
            symbol = (symbol or "").strip()
            try:
                cnt = int(count)
            except Exception:
                cnt = 100
                logger.debug(f"Count không hợp lệ, đặt mặc định là {cnt}.")

            if not symbol or tf_code is None:
                logger.warning("Ký hiệu hoặc khung thời gian trống.")
                return None, "Ký hiệu hoặc khung thời gian trống"

            # Ensure symbol is selected/visible in Market Watch.
            info = mt5.symbol_info(symbol)
            if info is None:
                logger.debug(f"Ký hiệu '{symbol}' không tìm thấy, thử đoán.")
                try:
                    cands = mt5.symbols_get(f"{symbol}*") or mt5.symbols_get(f"*{symbol}*") or []
                    if cands:
                        new_symbol = getattr(cands[0], "name", None)
                        if new_symbol:
                            symbol = new_symbol
                            try:
                                self.symbol_var.set(symbol)
                                logger.debug(f"Đã đoán và đặt ký hiệu mới: {symbol}")
                            except Exception:
                                pass
                            info = mt5.symbol_info(symbol)
                except Exception as e:
                    logger.warning(f"Lỗi khi đoán ký hiệu: {e}")
                    pass

            if info is None:
                logger.warning(f"Ký hiệu '{symbol}' không tồn tại sau khi đoán.")
                return None, f"Ký hiệu '{symbol}' không tồn tại"

            if not info.visible:
                logger.debug(f"Ký hiệu '{symbol}' không hiển thị, thử chọn.")
                try:
                    if not mt5.symbol_select(symbol, True):
                        logger.warning(f"Không thể chọn ký hiệu '{symbol}'.")
                        return None, f"Không thể chọn ký hiệu '{symbol}'"
                    __import__("time").sleep(0.1)  # Wait a bit for terminal
                    logger.debug(f"Đã chọn ký hiệu '{symbol}'.")
                except Exception as e:
                    logger.error(f"Lỗi khi chọn ký hiệu: {e}")
                    return None, f"Lỗi khi chọn ký hiệu: {e}"

            # Fetch rates
            rates = mt5.copy_rates_from_pos(symbol, tf_code, 0, cnt)
            if rates is None or len(rates) == 0:
                err = mt5.last_error()
                logger.warning(f"Không có dữ liệu rates cho '{symbol}' {tf_code}: {err}")
                return None, f"Không có dữ liệu rates: {err}"

            df = pd.DataFrame(rates)
            if df.empty:
                logger.warning("DataFrame trống sau khi chuyển đổi rates.")
                return None, "DataFrame trống sau khi chuyển đổi"

            df["time"] = pd.to_datetime(df["time"], unit="s")
            df.set_index("time", inplace=True)
            logger.debug(f"Đã lấy và xử lý rates cho '{symbol}' {tf_code}. Số dòng: {len(df)}")
            return df, None
        except Exception as e:
            logger.error(f"Lỗi ngoại lệ trong _rates_to_df: {e}")
            return None, f"Lỗi ngoại lệ: {e}"

    def _style(self):
        """
        Cấu hình kiểu hiển thị cho biểu đồ matplotlib.
        """
        logger.debug("Bắt đầu _style.")
        try:
            import matplotlib as mpl
            mpl.rcParams.update({"axes.grid": True, "grid.alpha": 0.25})
            logger.debug("Đã cập nhật style matplotlib.")
        except Exception as e:
            logger.warning(f"Lỗi khi cập nhật style matplotlib: {e}")
            pass
        logger.debug("Kết thúc _style.")

    def _fmt(self, x: Any, digits: int = 5) -> str:
        """
        Định dạng một giá trị số thành chuỗi với số chữ số thập phân nhất định.

        Args:
            x: Giá trị cần định dạng.
            digits: Số chữ số thập phân.

        Returns:
            Chuỗi đã định dạng.
        """
        logger.debug(f"Bắt đầu _fmt cho giá trị: {x}, digits: {digits}")
        try:
            result = f"{float(x):.{int(digits)}f}"
            logger.debug(f"Đã format giá trị: {result}")
            return result
        except Exception as e:
            logger.warning(f"Lỗi khi format giá trị '{x}': {e}")
            return str(x)

    def _update_account_info(self, symbol: str):
        """
        Cập nhật thông tin tài khoản MT5 trên giao diện người dùng.

        Args:
            symbol: Ký hiệu giao dịch hiện tại (để lấy thông tin liên quan).
        """
        logger.debug(f"Bắt đầu _update_account_info cho symbol: {symbol}")
        try:
            if not self._ensure_mt5(want_account=True):
                logger.warning("Không thể cập nhật thông tin tài khoản vì MT5 chưa sẵn sàng.")
                return
            import MetaTrader5 as mt5
            ai = mt5.account_info()
            if ai:
                self.acc_balance.set(f"{ai.balance:.2f}")
                self.acc_equity.set(f"{ai.equity:.2f}")
                self.acc_margin.set(f"{ai.margin_free:.2f}")
                self.acc_leverage.set(str(getattr(ai, "leverage", "-")))
                self.acc_currency.set(getattr(ai, "currency", "-"))
                self.acc_status.set("Kết nối MT5 OK")
                logger.debug("Đã cập nhật thông tin tài khoản.")
            else:
                self.acc_status.set("MT5: Chưa đăng nhập (account_info=None)")
                logger.warning("Không lấy được thông tin tài khoản MT5.")
        except Exception as e:
            logger.error(f"Lỗi khi cập nhật thông tin tài khoản: {e}")
            pass
        logger.debug("Kết thúc _update_account_info.")

    def _fill_positions_table(self, symbol: str):
        """
        Điền dữ liệu các lệnh đang mở vào bảng trên giao diện người dùng.

        Args:
            symbol: Ký hiệu giao dịch để lọc các lệnh.
        """
        logger.debug(f"Bắt đầu _fill_positions_table cho symbol: {symbol}")
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
            logger.debug(f"Đã điền {len(poss)} lệnh đang mở vào bảng.")
        except Exception as e:
            logger.error(f"Lỗi khi điền bảng lệnh đang mở: {e}")
            pass
        logger.debug("Kết thúc _fill_positions_table.")

    def _fill_history_table(self, symbol: str):
        """
        Điền dữ liệu lịch sử giao dịch (deals gần nhất) vào bảng trên giao diện người dùng.

        Args:
            symbol: Ký hiệu giao dịch để lọc lịch sử.
        """
        logger.debug(f"Bắt đầu _fill_history_table cho symbol: {symbol}")
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
            logger.debug(f"Đã điền {len(deals)} lịch sử giao dịch vào bảng.")
        except Exception as e:
            logger.error(f"Lỗi khi điền bảng lịch sử giao dịch: {e}")
            pass
        logger.debug("Kết thúc _fill_history_table.")

    def _draw_chart(self):
        """
        Vẽ biểu đồ giá bằng dữ liệu từ MT5 và matplotlib.
        """
        logger.debug("Bắt đầu _draw_chart.")
        # Ensure `sym` is always bound even if an early error occurs
        try:
            sym = self.symbol_var.get().strip()
        except Exception:
            sym = ""
            logger.warning("Không lấy được symbol từ symbol_var.")
        try:
            import MetaTrader5 as mt5
        except Exception as e:
            logger.error(f"Không thể import MetaTrader5 trong _draw_chart: {e}")
            try:
                self.ax_price.clear()
                self.ax_price.set_title("Không có MetaTrader5")
                self.canvas.draw_idle()
            except Exception:
                pass
            return
                # Ensure MT5 session is initialized
        if not self._ensure_mt5(want_account=False):
            logger.warning("MT5 chưa sẵn sàng để vẽ biểu đồ.")
            try:
                self.ax_price.clear()
                self.ax_price.set_title("MT5 chưa sẵn sàng")
                self.canvas.draw_idle()
            except Exception:
                pass
            return
        # Check for pandas
        try:
            import pandas as _pd  # noqa: F401
        except Exception as e:
            logger.error(f"Không thể import pandas trong _draw_chart: {e}")
            try:
                self.ax_price.clear()
                self.ax_price.set_title("Chưa cài pandas (pip install pandas)")
                self.canvas.draw_idle()
            except Exception:
                pass
            return
        # `sym` was already read above; keep using it
        tf_code = self._mt5_tf(self.tf_var.get())
        cnt = int(self.n_candles_var.get() or 100)
        df, err_msg = self._rates_to_df(sym, tf_code, cnt)
        if df is None or df.empty:
            logger.warning(f"Không có dữ liệu hoặc DataFrame trống để vẽ biểu đồ: {err_msg}")
            self.ax_price.clear()
            self.ax_price.set_title(err_msg or "Không có dữ liệu")
            self.canvas.draw_idle()
            return
        self.ax_price.clear()
        try:
            import matplotlib.dates as mdates
            kind = (self.chart_type_var.get() or "Đường").strip()
            if kind == "Nến":
                logger.debug("Vẽ biểu đồ nến.")
                try:
                    try:
                        from mplfinance.original_flavor import candlestick_ohlc  # type: ignore
                    except Exception:
                        from mpl_finance import candlestick_ohlc  # type: ignore
                except Exception as e:
                    candlestick_ohlc = None  # type: ignore
                    logger.warning(f"Không thể import candlestick_ohlc: {e}")

                if candlestick_ohlc is None:
                    self.ax_price.plot(df.index, df["close"], color="#0ea5e9", lw=1.2)
                    logger.debug("Vẽ biểu đồ đường thay vì nến do thiếu thư viện.")
                else:
                    import numpy as _np
                    xs = mdates.date2num(df.index.to_pydatetime())
                    ohlc = _np.column_stack((xs, df["open"].values, df["high"].values, df["low"].values, df["close"].values))
                    step = float(_np.median(_np.diff(xs))) if len(xs) > 1 else (1.0 / (24 * 60))
                    width = step * 0.7
                    candlestick_ohlc(self.ax_price, ohlc, width=width, colorup="#22c55e", colordown="#ef4444", alpha=0.9)
                    self.ax_price.xaxis_date()
                    logger.debug("Đã vẽ biểu đồ nến.")
            else:
                self.ax_price.plot(df.index, df["close"], color="#0ea5e9", lw=1.2)
                logger.debug("Đã vẽ biểu đồ đường.")
            self.ax_price.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
        except Exception as e:
            logger.error(f"Lỗi khi vẽ biểu đồ: {e}")
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
                self.ax_price.text(1.01, entry, " " + label, va="center", color=col, fontsize=8, transform=self.ax_price.get_yaxis_transform())
            logger.debug(f"Đã vẽ {len(poss)} lệnh đang mở lên biểu đồ.")

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
                self.ax_price.text(1.01, px, " " + txt, va="center", color=pend_col, fontsize=8, transform=self.ax_price.get_yaxis_transform())
                if sl:
                    self.ax_price.axhline(sl, color="#ef4444", ls=":", lw=1.0, alpha=0.85)
                    self.ax_price.text(df.index[-1], sl, "  SL", va="center", color="#ef4444", fontsize=7)
                if tp:
                    self.ax_price.axhline(tp, color="#22c55e", ls=":", lw=1.0, alpha=0.85)
                    self.ax_price.text(df.index[-1], tp, "  TP", va="center", color="#22c55e", fontsize=7)
            logger.debug(f"Đã vẽ {len(ords)} lệnh chờ lên biểu đồ.")

            # Draw current price line
            tick = mt5.symbol_info_tick(sym)
            if tick:
                current_price = getattr(tick, "bid", 0.0)
                if current_price > 0:
                    self.ax_price.axhline(current_price, color='black', ls='--', lw=0.8, alpha=0.9)
                    self.ax_price.text(1.01, current_price, f" {self._fmt(current_price, digits)}",
                                       va="center", color='black', fontsize=8,
                                       bbox=dict(facecolor='white', alpha=0.5, edgecolor='none', boxstyle='round,pad=0.1'),
                                       transform=self.ax_price.get_yaxis_transform())
                    logger.debug(f"Đã vẽ đường giá hiện tại: {current_price}")
        except Exception as e:
            logger.error(f"Lỗi khi vẽ các đối tượng giao dịch lên biểu đồ: {e}")
            pass

        self.ax_price.set_title(f"{sym}  •  {self.tf_var.get()}  •  {len(df)} bars")
        self.fig.subplots_adjust(right=0.75)
        self.canvas.draw_idle()
        logger.debug("Kết thúc _draw_chart.")

    def _redraw_safe(self):
        """
        Vẽ lại biểu đồ và cập nhật các panel thông tin một cách an toàn.
        Xử lý lỗi để tránh crash ứng dụng.
        """
        logger.debug("Bắt đầu _redraw_safe.")
        try:
            self._draw_chart()
        except Exception as e:
            logger.error(f"Lỗi khi vẽ biểu đồ an toàn: {e}")
            try:
                self.ax_price.clear()
                self.ax_price.set_title(f"Chart error: {e}")
                self.canvas.draw_idle()
            except Exception:
                pass

        # Always update account info, regardless of chart success
        sym = ""
        try:
            sym = self.symbol_var.get().strip()
        except Exception:
            logger.warning("Không lấy được symbol từ symbol_var trong _redraw_safe.")
            pass
        try:
            self._update_account_info(sym)
            self._fill_positions_table(sym)
            self._fill_history_table(sym)
            logger.debug("Đã cập nhật thông tin tài khoản, lệnh và lịch sử.")
        except Exception as e:
            logger.error(f"Lỗi khi cập nhật thông tin tài khoản/lệnh/lịch sử: {e}")
            pass

        try:
            self._update_notrade_panel()
            logger.debug("Đã cập nhật panel No-Trade.")
        except Exception as e:
            logger.error(f"Lỗi khi cập nhật panel No-Trade: {e}")
            pass
        logger.debug("Kết thúc _redraw_safe.")

    def _tick(self):
        """
        Hàm tick được gọi định kỳ để làm mới dữ liệu và biểu đồ.
        """
        logger.debug("Bắt đầu _tick.")
        if not self._running:
            logger.debug("_tick dừng vì _running là False.")
            return
        try:
            # Opportunistic refresh of shared news cache (non-blocking)
            if hasattr(self.app, "_refresh_news_cache"):
                ttl = None
                try:
                    ttl = int(getattr(self.app, "news_cache_ttl_sec_var", None).get()) if getattr(self.app, "news_cache_ttl_sec_var", None) else None
                except Exception:
                    ttl = None
                    logger.warning("Không lấy được news_cache_ttl_sec_var, dùng mặc định.")
                self.app._refresh_news_cache(ttl=int(ttl or 300))
                logger.debug(f"Đã refresh news cache với TTL: {ttl or 300}.")
        except Exception as e:
            logger.error(f"Lỗi khi refresh news cache trong _tick: {e}")
            pass
        self._redraw_safe()
        secs = max(1, int(self.refresh_secs_var.get() or 5))
        self._after_job = self.root.after(secs * 1000, self._tick)
        logger.debug(f"Lên lịch _tick tiếp theo sau {secs} giây.")
        logger.debug("Kết thúc _tick.")

    # -------------------------
    # No-Trade panel helpers
    # -------------------------
    def _compute_sessions_today(self, symbol: str) -> dict:
        """
        Tính toán các phiên giao dịch trong ngày hiện tại.

        Args:
            symbol: Ký hiệu giao dịch (hiện không được sử dụng trực tiếp để tính phiên).

        Returns:
            Một từ điển chứa thông tin về các phiên giao dịch.
        """
        logger.debug(f"Bắt đầu _compute_sessions_today cho symbol: {symbol}")
        try:
            from src.utils import mt5_utils as _mt5u
            # The session ranges are now based on system time, not rates.
            # We can call the helper directly without fetching MT5 data here.
            result = _mt5u.session_ranges_today(None) or {}
            logger.debug(f"Đã tính toán sessions today: {result}")
            return result
        except Exception as e:
            logger.error(f"Lỗi khi tính toán sessions today: {e}")
            return {}

    def _allowed_session_now(self, ss: dict) -> bool:
        """
        Kiểm tra xem phiên giao dịch hiện tại có được phép giao dịch hay không.

        Args:
            ss: Từ điển chứa thông tin về các phiên giao dịch trong ngày.

        Returns:
            True nếu phiên hiện tại được phép, ngược lại là False.
        """
        logger.debug(f"Bắt đầu _allowed_session_now với sessions: {ss}")
        try:
            now = __import__("datetime").datetime.now().strftime("%H:%M")
            def _in(r):
                return bool(r and r.get("start") and r.get("end") and r["start"] <= now < r["end"])
            ok = False
            if getattr(self.app, "trade_allow_session_asia_var", None) and self.app.trade_allow_session_asia_var.get():
                ok = ok or _in(ss.get("asia"))
                logger.debug(f"Kiểm tra phiên Asia: {ok}")
            if getattr(self.app, "trade_allow_session_london_var", None) and self.app.trade_allow_session_london_var.get():
                ok = ok or _in(ss.get("london"))
                logger.debug(f"Kiểm tra phiên London: {ok}")
            if getattr(self.app, "trade_allow_session_ny_var", None) and self.app.trade_allow_session_ny_var.get():
                ok = ok or _in(ss.get("newyork_am")) or _in(ss.get("newyork_pm"))
                logger.debug(f"Kiểm tra phiên New York: {ok}")
            # If no restriction flags checked, allow
            flags = [
                bool(getattr(self.app, "trade_allow_session_asia_var", None) and self.app.trade_allow_session_asia_var.get()),
                bool(getattr(self.app, "trade_allow_session_london_var", None) and self.app.trade_allow_session_london_var.get()),
                bool(getattr(self.app, "trade_allow_session_ny_var", None) and self.app.trade_allow_session_ny_var.get()),
            ]
            if not any(flags):
                ok = True
                logger.debug("Không có cờ phiên nào được chọn, mặc định cho phép.")
            logger.debug(f"Kết thúc _allowed_session_now. Kết quả: {ok}")
            return bool(ok)
        except Exception as e:
            logger.error(f"Lỗi khi kiểm tra phiên giao dịch: {e}")
            return True

    def _update_notrade_panel(self):
        """
        Cập nhật panel "Không giao dịch" với trạng thái phiên, lý do và các sự kiện sắp tới.
        """
        logger.debug("Bắt đầu _update_notrade_panel.")
        # Session gate
        sym = (self.symbol_var.get().strip() or getattr(self.app, "mt5_symbol_var", tk.StringVar(value="")).get().strip() or "")
        ss = self._compute_sessions_today(sym) if sym else {}
        sess_ok = self._allowed_session_now(ss)
        self.nt_session_gate.set("Allowed" if sess_ok else "Blocked")
        logger.debug(f"Trạng thái phiên giao dịch: {'Allowed' if sess_ok else 'Blocked'}")

        # Reasons from last evaluate
        reasons = []
        try:
            reasons = list(getattr(self.app, "last_no_trade_reasons", []) or [])
        except Exception:
            reasons = []
            logger.warning("Không lấy được last_no_trade_reasons.")
        if reasons:
            txt = "\n".join([f"- {str(r)}" for r in reasons[:4]])
        else:
            txt = "(none)"
        self.nt_reasons.set(txt)
        logger.debug(f"Lý do No-Trade: {txt}")

        # Upcoming high-impact events (limit 3) relevant to symbol
        try:
            from src.services import news as _news
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
            logger.debug(f"Sự kiện sắp tới: {self.nt_events.get()}")
        except Exception as e:
            self.nt_events.set("(none)")
            logger.error(f"Lỗi khi cập nhật sự kiện tin tức: {e}")
        logger.debug("Kết thúc _update_notrade_panel.")
