# -*- coding: utf-8 -*-
"""
Module for the Chart Tab in the application's UI.

This module contains the ChartTab class, which is responsible for creating,
arranging, and managing all the widgets within the 'Chart' tab of the main
application window. This includes controls for running analysis, displaying
reports, and showing trade status.
"""
from __future__ import annotations

import logging
import tkinter as tk
from dataclasses import replace
import tkinter as tk
from datetime import datetime, timezone
from tkinter import ttk
from tkinter import scrolledtext
from typing import TYPE_CHECKING, Any, Dict, Optional

from concurrent.futures import CancelledError, Future

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None

# Các import của bên thứ ba
try:
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    from matplotlib.backends._backend_tk import NavigationToolbar2Tk
    import matplotlib.dates as mdates
    from mplfinance.original_flavor import candlestick_ohlc
    import numpy as np
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    # Tạo các lớp giả để chương trình không bị crash nếu thiếu matplotlib
    class Figure:
        pass

    class FigureCanvasTkAgg:
        pass

    class NavigationToolbar2Tk:
        pass
    MATPLOTLIB_AVAILABLE = False

# Các import cục bộ
from APP.core.trading import conditions
from APP.core.trading.no_trade_metrics import NoTradeMetrics, collect_no_trade_metrics
from APP.services import mt5_service
from APP.ui.controllers.chart_controller import ChartController, ChartStreamConfig
from APP.utils import threading_utils
from APP.utils.threading_utils import CancelToken
from APP.utils.safe_data import SafeData

if TYPE_CHECKING:
    from APP.configs.app_config import RunConfig
    from APP.ui.app_ui import AppUI
    from APP.ui.controllers.chart_controller import ChartController
    from APP.ui.utils.ui_builder import UiBuilder

logger = logging.getLogger(__name__)

# Constants for UI layout and styling
PAD_X = 5
PAD_Y = 5
FONT_BOLD = ("Helvetica", 10, "bold")


class ChartTab:
    """
    Manages the UI components within the 'Chart' tab.

    This class encapsulates the creation and layout of all widgets,
    and connects UI events (like button clicks) to the appropriate
    controller methods.
    """

    def __init__(
        self,
        app_ui: AppUI,
        notebook: ttk.Notebook,
        ui_builder: Optional[UiBuilder] = None,
        controller: Optional[ChartController] = None,
    ):
        """
        Initializes the ChartTab.

        Args:
            app_ui: The main application UI instance.
            notebook: The parent ttk.Notebook widget.
            ui_builder: Optional UiBuilder helper for widget creation.
            controller: Optional chart controller instance to reuse.
        """
        self.app_ui = app_ui
        self.notebook = notebook
        self.ui_builder = ui_builder
        self.controller = controller
        # Aliases for compatibility with legacy code
        self.app = app_ui
        self.root = app_ui.root

        # Runtime state
        self._controller: Optional[ChartController] = controller
        self._running = False
        self._stream_active = False
        self._after_job: Optional[str] = None
        self._backlog_limit = 50
        self._tooltip_window: Optional[tk.Toplevel] = None

        # Tkinter variables
        self.nt_status = tk.StringVar(value="Đang tải...")
        self.nt_session_gate = tk.StringVar(value="-")
        self.tf_var = tk.StringVar(value="M15")
        self.n_candles_var = tk.IntVar(value=150)
        self.chart_type_var = tk.StringVar(value="Nến")
        self.refresh_secs_var = tk.IntVar(value=5)

        self.acc_balance = tk.StringVar(value="-")
        self.acc_equity = tk.StringVar(value="-")
        self.acc_margin = tk.StringVar(value="-")
        self.acc_leverage = tk.StringVar(value="-")
        self.acc_currency = tk.StringVar(value="-")
        self.acc_status = tk.StringVar(value="Chưa kết nối MT5")

        # Biến cho panel No-Trade
        self.nt_status = tk.StringVar(value="Đang tải...")
        self.nt_session_gate = tk.StringVar(value="-")
        self._nt_reasons_box: Optional[scrolledtext.ScrolledText] = None
        self._nt_metrics_box: Optional[scrolledtext.ScrolledText] = None
        self._nt_events_box: Optional[scrolledtext.ScrolledText] = None
        logger.debug("Kết thúc hàm _init_vars.")

    def _build_controls(self):
        """Xây dựng bảng điều khiển trên cùng."""
        logger.debug("Bắt đầu hàm _build_controls.")
        ctrl = ttk.Frame(self.tab)
        ctrl.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))

        ttk.Label(ctrl, text="Ký hiệu:").pack(side="left", padx=(0, 2))
        self.cbo_symbol = ttk.Combobox(ctrl, width=16, textvariable=self.app.mt5_symbol_var, state="normal", values=[])
        self.cbo_symbol.pack(side="left", padx=(0, 10))
        self._populate_symbol_list()

        ttk.Label(ctrl, text="Khung:").pack(side="left", padx=(0, 2))
        self.cbo_tf = ttk.Combobox(
            ctrl, width=6, state="readonly", values=["M1", "M5", "M15", "H1", "H4", "D1"], textvariable=self.tf_var
        )
        self.cbo_tf.pack(side="left", padx=(0, 10))
        self.cbo_tf.bind("<<ComboboxSelected>>", self._reset_and_redraw)

        ttk.Label(ctrl, text="Số nến:").pack(side="left", padx=(0, 2))
        ttk.Spinbox(ctrl, from_=50, to=5000, textvariable=self.n_candles_var, width=8, command=self._reset_and_redraw)\
            .pack(side="left", padx=(0, 10))

        ttk.Label(ctrl, text="Kiểu:").pack(side="left", padx=(0, 2))
        self.cbo_chart_type = ttk.Combobox(
            ctrl, width=8, state="readonly", values=["Đường", "Nến"], textvariable=self.chart_type_var
        )
        self.cbo_chart_type.pack(side="left", padx=(0, 10))
        self.cbo_chart_type.bind("<<ComboboxSelected>>", self._reset_and_redraw)

        ttk.Label(ctrl, text="Làm mới (s):").pack(side="left", padx=(0, 2))
        ttk.Spinbox(ctrl, from_=1, to=3600, textvariable=self.refresh_secs_var, width=6)\
            .pack(side="left", padx=(0, 10))
        logger.debug("Kết thúc hàm _build_controls.")

    def _build_chart_area(self):
        """Xây dựng khu vực hiển thị biểu đồ."""
        chart_wrap = ttk.Frame(self.tab)
        chart_wrap.grid(row=1, column=0, sticky="nsew", padx=(0, 6))
        chart_wrap.rowconfigure(1, weight=1)
        chart_wrap.columnconfigure(0, weight=1)

        if not MATPLOTLIB_AVAILABLE:
            ttk.Label(chart_wrap, text="Vui lòng cài đặt thư viện Matplotlib và mplfinance để hiển thị biểu đồ.").grid(row=0, column=0, sticky="nsew")
            logger.warning("Matplotlib hoặc các thư viện phụ thuộc không có sẵn.")
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
        right_col = ttk.Frame(self.tab)
        right_col.grid(row=1, column=1, sticky="nsew")
        right_col.columnconfigure(0, weight=1)
        right_col.rowconfigure(1, weight=1)
        self._build_account_panel(right_col)
        self._build_notrade_panel(right_col)

    def _build_account_panel(self, parent: ttk.Frame) -> None:
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

    def _create_chart_display(self, parent: ttk.Frame) -> None:
        """Creates the chart display area."""
        chart_wrap = ttk.LabelFrame(parent, text="Chart Display")
        chart_wrap.grid(row=0, column=0, sticky="nsew", pady=(0, PAD_Y))
        chart_wrap.columnconfigure(0, weight=1)
        chart_wrap.rowconfigure(0, weight=1)

        # Placeholder for chart
        placeholder_label = ttk.Label(
            chart_wrap, text="Chart will be displayed here.", anchor="center"
        )
        placeholder_label.grid(row=0, column=0, sticky="nsew")

    def _build_notrade_panel(self, parent: ttk.Frame):
        """Xây dựng panel điều kiện không giao dịch."""
        nt_box = ttk.LabelFrame(parent, text="Điều kiện giao dịch", padding=8)
        nt_box.grid(row=1, column=0, sticky="nsew", pady=(6, 0))
        nt_box.columnconfigure(1, weight=1)
        nt_box.rowconfigure(3, weight=1)
        nt_box.rowconfigure(5, weight=1)
        nt_box.rowconfigure(7, weight=1)
        ttk.Label(nt_box, text="Trạng thái:").grid(row=0, column=0, sticky="w")
        ttk.Label(nt_box, textvariable=self.nt_status, foreground="#0f172a").grid(row=0, column=1, sticky="e")
        ttk.Label(nt_box, text="Phiên giao dịch:").grid(row=1, column=0, sticky="w")
        ttk.Label(nt_box, textvariable=self.nt_session_gate).grid(row=1, column=1, sticky="e")
        ttk.Label(nt_box, text="Lý do No-Trade:").grid(row=2, column=0, sticky="nw", pady=(4, 0))
        self._nt_reasons_box = scrolledtext.ScrolledText(
            nt_box,
            height=5,
            wrap="word",
            state="disabled",
            relief="solid",
            borderwidth=1,
        )
        self._nt_reasons_box.grid(row=3, column=0, columnspan=2, sticky="nsew")
        ttk.Label(nt_box, text="Chỉ số bảo vệ:").grid(row=4, column=0, sticky="nw", pady=(6, 0))
        self._nt_metrics_box = scrolledtext.ScrolledText(
            nt_box,
            height=5,
            wrap="word",
            state="disabled",
            relief="solid",
            borderwidth=1,
        )
        self._nt_metrics_box.grid(row=5, column=0, columnspan=2, sticky="nsew")
        ttk.Label(nt_box, text="Sự kiện sắp tới:").grid(row=6, column=0, sticky="nw", pady=(6, 0))
        self._nt_events_box = scrolledtext.ScrolledText(
            nt_box,
            height=4,
            wrap="word",
            state="disabled",
            relief="solid",
            borderwidth=1,
        )
        self._nt_events_box.grid(row=7, column=0, columnspan=2, sticky="nsew")
        self._set_nt_text(self._nt_reasons_box, "Đang thu thập dữ liệu...")
        self._set_nt_text(self._nt_metrics_box, "Đang thu thập dữ liệu...")
        self._set_nt_text(self._nt_events_box, "Đang thu thập dữ liệu...")

    def _set_nt_text(self, widget: Optional[scrolledtext.ScrolledText], value: str) -> None:
        """Cập nhật nội dung của vùng văn bản No-Trade ở chế độ chỉ đọc."""

        if not widget:
            return
        widget.configure(state="normal")
        widget.delete("1.0", tk.END)
        text = (value or "").strip()
        if not text:
            text = "Không có dữ liệu."
        widget.insert("1.0", text + "\n")
        widget.configure(state="disabled")

    def _build_bottom_grids(self):
        """Xây dựng các bảng dữ liệu ở dưới cùng."""
        grids = ttk.Frame(self.tab)
        grids.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=(6, 0))
        grids.columnconfigure(0, weight=1)
        grids.columnconfigure(1, weight=1)
        grids.rowconfigure(0, weight=1)
        self._build_positions_grid(grids)
        self._build_history_grid(grids)

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

    def _reset_and_redraw(self, *_args) -> None:
        """Reloads the chart stream configuration and triggers a snapshot refresh."""
        controller = self._ensure_controller()
        controller.update_config(self._build_stream_config())
        controller.request_snapshot()

    def start(self) -> None:
        """Bắt đầu quá trình làm mới biểu đồ và thông tin định kỳ."""
        if self._running:
            return
        controller = self._ensure_controller()
        controller.start_stream(
            config=self._build_stream_config(),
            info_worker=self._update_info_worker,
            chart_worker=self._chart_drawing_worker,
            on_info_done=self._apply_data_updates,
            on_chart_done=self._apply_chart_updates,
        )
        self._stream_active = True
        self._running = True
        self._schedule_next_tick(immediate=True)
        logger.info("ChartTab đã bắt đầu làm mới dữ liệu.")

    def stop(self) -> None:
        """Dừng quá trình làm mới biểu đồ và thông tin."""
        self._running = False
        if self._after_job:
            self.root.after_cancel(self._after_job)
            self._after_job = None
        if self._controller:
            self._controller.stop_stream()
        self._stream_active = False
        logger.info("ChartTab đã dừng làm mới dữ liệu.")

    def _ensure_controller(self) -> ChartController:
        """Đảm bảo luôn có controller hợp lệ."""

        if not self._controller:
            self._controller = ChartController(
                threading_manager=self.app.threading_manager,
                ui_queue=self.app.ui_queue,
                backlog_limit=self._backlog_limit,
            )
        return self._controller

    def _schedule_next_tick(self, *, immediate: bool = False) -> None:
        """Lên lịch tick tiếp theo với chu kỳ realtime."""

        delay_ms = 1 if immediate else self._compute_tick_interval_ms()
        self._after_job = self.root.after(delay_ms, self._tick)

    def _compute_tick_interval_ms(self) -> int:
        """Tính toán khoảng thời gian tick dựa trên cấu hình người dùng."""

        raw = self.refresh_secs_var.get() or 1
        secs = max(0.2, min(float(raw), 1.0))  # ép realtime ≤1s theo yêu cầu Product
        return int(secs * 1000)

    def _build_stream_config(self) -> ChartStreamConfig:
        """Tạo cấu hình stream dựa trên trạng thái UI hiện tại."""

        symbol = self.app.mt5_symbol_var.get().strip() or "XAUUSD"
        if not self.app.mt5_symbol_var.get().strip():
            self.app.mt5_symbol_var.set(symbol)
        timeframe = self.tf_var.get()
        candles = max(50, self.n_candles_var.get() or 150)
        return ChartStreamConfig(
            symbol=symbol,
            timeframe=timeframe,
            candles=candles,
            chart_type=self.chart_type_var.get(),
        )

    def _snapshot_run_config(self, stream_config: ChartStreamConfig) -> "RunConfig":
        """Lấy snapshot RunConfig và điều chỉnh theo stream hiện tại."""
        run_config = self.app._snapshot_config()
        updated_mt5 = replace(run_config.mt5, symbol=stream_config.symbol)
        updated_chart = replace(
            run_config.chart,
            timeframe=stream_config.timeframe,
            num_candles=stream_config.candles,
            chart_type=stream_config.chart_type,
        )
        return replace(run_config, mt5=updated_mt5, chart=updated_chart)

    def _mt5_tf(self, tf_str: str) -> Optional[int]:
        """Chuyển đổi chuỗi khung thời gian thành mã MT5."""
        if mt5 is None:
            return None
        mapping = {
            "M1": getattr(mt5, "TIMEFRAME_M1", None),
            "M5": getattr(mt5, "TIMEFRAME_M5", None),
            "M15": getattr(mt5, "TIMEFRAME_M15", None),
            "H1": getattr(mt5, "TIMEFRAME_H1", None),
            "H4": getattr(mt5, "TIMEFRAME_H4", None),
            "D1": getattr(mt5, "TIMEFRAME_D1", None),
        }
        return mapping.get(tf_str.upper())

    def _chart_drawing_worker(self, stream_config: ChartStreamConfig, cancel_token: CancelToken) -> Dict[str, Any]:
        """Worker dựng dữ liệu biểu đồ cho UI thread."""
        if not mt5_service.is_connected():
            return {"success": False, "message": "MT5 chưa kết nối."}

        cancel_token.raise_if_cancelled()
        run_config = self._snapshot_run_config(stream_config)
        safe_mt5_data = mt5_service.get_market_data(
            run_config.mt5,
            timezone_name=run_config.no_run.timezone,
            killzone_overrides={
                "summer": run_config.no_run.killzone_summer,
                "winter": run_config.no_run.killzone_winter,
            },
        )
        cancel_token.raise_if_cancelled()
        if not isinstance(safe_mt5_data, SafeData) or not safe_mt5_data.is_valid():
            return {"success": False, "message": "Không lấy được dữ liệu MT5."}

        tf_code = self._mt5_tf(stream_config.timeframe)
        if tf_code is None:
            return {"success": False, "message": "Khung thời gian không hỗ trợ."}

        try:
            rates = mt5_service._series_from_mt5(stream_config.symbol, tf_code, stream_config.candles)
        except Exception as exc:
            logger.exception("Lỗi khi lấy dữ liệu biểu đồ: %s", exc)
            return {"success": False, "message": str(exc)}

        cancel_token.raise_if_cancelled()
        return {
            "success": True,
            "symbol": stream_config.symbol,
            "timeframe": stream_config.timeframe,
            "rates": rates,
            "info": safe_mt5_data.get("info", {}),
            "tick": safe_mt5_data.get("tick", {}),
            "positions": safe_mt5_data.get("positions", []),
        }

    def _populate_symbol_list(self) -> None:
        """Điền danh sách các ký hiệu giao dịch vào combobox bằng facade mới."""

        def worker(cancel_token: CancelToken) -> list[str]:
            cancel_token.raise_if_cancelled()
            names = mt5_service.get_all_symbols()
            cancel_token.raise_if_cancelled()
            return names

        record = self.app.threading_manager.submit(
            func=worker,
            group="chart.init",
            name="chart.symbols",
            metadata={"component": "chart"},
        )

        def on_done(future: Future) -> None:  # type: ignore[name-defined]
            try:
                names = future.result()
            except Exception as exc:  # pragma: no cover - logging path
                logger.error("Không thể lấy danh sách symbol: %s", exc)
                names = []
            self.app.ui_queue.put(lambda lst=names: self._apply_symbol_list(lst))

        record.future.add_done_callback(on_done)

    def _apply_symbol_list(self, names: list[str]) -> None:
        """Cập nhật combobox symbol trên luồng UI."""

        if not self.cbo_symbol:
            return
        self.cbo_symbol["values"] = names
        current_symbol = self.app.mt5_symbol_var.get()
        if current_symbol and current_symbol in names:
            return
        if "XAUUSD" in names:
            self.app.mt5_symbol_var.set("XAUUSD")
        elif names:
            self.app.mt5_symbol_var.set(names[0])
        logger.debug("Đã cập nhật danh sách symbol (%d mục).", len(names))

    def _tick(self) -> None:
        """Hàm tick được gọi định kỳ để làm mới dữ liệu."""

        if not self._running:
            return
        if self._controller and self._stream_active:
            self._controller.trigger_refresh()
        self._schedule_next_tick()

    def _update_info_worker(self, stream_config: ChartStreamConfig, cancel_token: CancelToken) -> Dict[str, Any]:
        """Worker lấy dữ liệu tài khoản/lệnh/No-Trade với cancel token."""

        if not mt5_service.is_connected():
            return {"mt5_data": None, "status_message": "MT5 chưa kết nối."}

        run_config = self._snapshot_run_config(stream_config)

        cancel_token.raise_if_cancelled()
        safe_mt5_data = mt5_service.get_market_data(
            run_config.mt5,
            timezone_name=run_config.no_run.timezone,
            killzone_overrides={
                "summer": run_config.no_run.killzone_summer,
                "winter": run_config.no_run.killzone_winter,
            },
        )
        if not safe_mt5_data.is_valid():
            return {"mt5_data": None, "status_message": "Không lấy được dữ liệu MT5."}

        tasks = [
            (
                conditions.check_no_trade_conditions,
                (safe_mt5_data, current_config, self.app.news_service),
                {"now_utc": datetime.now(timezone.utc)},
            ),
            (self.app.news_service.get_upcoming_events, (current_config.mt5.symbol,), {}),
            (mt5_service.get_history_deals, (current_config.mt5.symbol,), {"days": 7}),
        ]
        results = threading_utils.run_in_parallel(tasks)
        cancel_token.raise_if_cancelled()

        no_trade_result = results.get("check_no_trade_conditions")
        if isinstance(no_trade_result, conditions.NoTradeCheckResult):
            no_trade_reasons = no_trade_result.to_messages(include_warnings=True)
        else:
            no_trade_reasons = list(no_trade_result or [])

        return {
            "mt5_data": safe_mt5_data,
            "no_trade_reasons": no_trade_reasons,
            "no_trade_result": no_trade_result,
            "upcoming_events": results.get("get_upcoming_events", []),
            "history_deals": results.get("get_history_deals", []),
            "status_message": "Kết nối MT5 OK",
            "run_config": current_config,
        }

    def _apply_data_updates(self, payload: Dict[str, Any]):
        """
        Áp dụng dữ liệu được lấy từ luồng nền lên các widget UI.
        Hàm này phải được gọi từ luồng chính (UI thread).
        """
        safe_mt5_data: Optional[SafeData] = payload.get("mt5_data")
        no_trade_reasons: list[str] = payload.get("no_trade_reasons", [])
        no_trade_result = payload.get("no_trade_result")
        upcoming_events: list[dict] = payload.get("upcoming_events", [])
        history_deals: list[dict] = payload.get("history_deals", [])
        status_message: Optional[str] = payload.get("status_message")
        current_config: Optional["RunConfig"] = payload.get("run_config")
        if current_config is None:
            try:
                current_config = self.app._snapshot_config()
            except Exception:
                logger.exception("Không thể chụp lại cấu hình hiện tại để hiển thị No-Trade.")

        if status_message:
            self.acc_status.set(status_message)

        if not safe_mt5_data or not safe_mt5_data.is_valid():
            logger.debug("Bỏ qua cập nhật chi tiết do không có dữ liệu MT5 hợp lệ.")
            self.nt_status.set("❓ Không có dữ liệu")
            return

        # Cập nhật thông tin tài khoản
        acc_info = safe_mt5_data.get("account", {})
        self.acc_balance.set(f"{acc_info.get('balance', 0.0):.2f}")
        self.acc_equity.set(f"{acc_info.get('equity', 0.0):.2f}")
        self.acc_margin.set(f"{acc_info.get('free_margin', 0.0):.2f}")
        self.acc_leverage.set(str(acc_info.get('leverage', '-')))
        self.acc_currency.set(acc_info.get('currency', '-'))
        if not status_message:
            self.acc_status.set("Kết nối MT5 OK")

        # Cập nhật bảng lệnh đang mở
        positions = safe_mt5_data.get("positions", [])
        if self.tree_pos:
            self.tree_pos.delete(*self.tree_pos.get_children())
            for p in positions:
                values = (
                    p.get("ticket"), p.get("type"), f"{p.get('volume', 0.0):.2f}",
                    f"{p.get('price_open', 0.0):.5f}", f"{p.get('sl', 0.0):.5f}",
                    f"{p.get('tp', 0.0):.5f}", f"{p.get('profit', 0.0):.2f}"
                )
                self.tree_pos.insert("", "end", values=values)

        # Cập nhật bảng lịch sử
        if self.tree_his:
            self.tree_his.delete(*self.tree_his.get_children())
            if history_deals:
                for d in history_deals:
                    values = (
                        d.get("time"), d.get("ticket"), d.get("type"),
                        d.get("volume"), d.get("price"), d.get("profit")
                    )
                    self.tree_his.insert("", "end", values=values)

        # Cập nhật panel No-Trade
        self.nt_session_gate.set(safe_mt5_data.get("killzone_active", "N/A"))
        status_text = "✅ An toàn"
        if isinstance(no_trade_result, conditions.NoTradeCheckResult):
            try:
                self.app.last_no_trade_result = no_trade_result.to_dict(
                    include_messages=True
                )
            except Exception:
                logger.exception("Không thể serial hóa kết quả No-Trade cho AppUI.")
            if no_trade_result.has_blockers():
                status_text = "⛔ Bị chặn"
                lines = no_trade_result.to_messages(include_warnings=True)
            elif no_trade_result.warnings:
                status_text = "⚠️ Có cảnh báo"
                lines = no_trade_result.to_messages(include_warnings=True)
            else:
                lines = ["✅ Không có trở ngại."]
            metrics_obj = no_trade_result.metrics
        else:
            has_reasons = bool(no_trade_reasons)
            status_text = "⛔ Bị chặn" if has_reasons else "✅ An toàn"
            lines = no_trade_reasons or ["✅ Không có trở ngại."]
            metrics_obj = None

        self.nt_status.set(status_text)

        if lines:
            reasons_text = "\n".join(lines)
        else:
            reasons_text = "✅ Không có trở ngại."
        self._set_nt_text(self._nt_reasons_box, reasons_text)

        if metrics_obj is None and safe_mt5_data and current_config:
            try:
                metrics_obj = collect_no_trade_metrics(safe_mt5_data, current_config)
            except Exception:
                logger.exception("Không thể thu thập chỉ số No-Trade để hiển thị UI.")
                metrics_obj = None

        metrics_text = self._format_no_trade_metrics(metrics_obj)
        self._set_nt_text(self._nt_metrics_box, metrics_text)

        if upcoming_events:
            events_str = "\n".join(
                f"- {e['when_local'].strftime('%H:%M')} ({e.get('country', 'N/A')}): {e.get('title', 'N/A')}"
                for e in upcoming_events[:3] # Hiển thị 3 sự kiện gần nhất
            )
            self._set_nt_text(self._nt_events_box, events_str)
        else:
            self._set_nt_text(self._nt_events_box, "Không có sự kiện quan trọng sắp tới.")

    def _format_no_trade_metrics(self, metrics: Optional[NoTradeMetrics]) -> str:
        """Tạo chuỗi mô tả các chỉ số bảo vệ No-Trade."""

        if not metrics:
            return "Không có dữ liệu chỉ số."

        lines: list[str] = []

        spread = metrics.spread
        if spread.current_pips is not None:
            spread_line = f"Spread: {spread.current_pips:.2f} pips"
            if spread.threshold_pips:
                spread_line += f" / {spread.threshold_pips:.2f} pips"
            if spread.p90_5m_pips is not None:
                spread_line += f" (P90 5m {spread.p90_5m_pips:.2f})"
            elif spread.p90_30m_pips is not None:
                spread_line += f" (P90 30m {spread.p90_30m_pips:.2f})"
            if spread.atr_pct is not None:
                spread_line += f" | {spread.atr_pct:.1f}% ATR"
            lines.append(spread_line)
        else:
            lines.append("Spread: N/A")

        atr = metrics.atr
        if atr.atr_m5_pips is not None:
            atr_line = f"ATR M5: {atr.atr_m5_pips:.2f} pips"
            if atr.min_required_pips:
                atr_line += f" (ngưỡng {atr.min_required_pips:.2f})"
            if atr.atr_pct_of_adr20 is not None:
                atr_line += f" | {atr.atr_pct_of_adr20:.1f}% ADR20"
            lines.append(atr_line)
        else:
            lines.append("ATR M5: N/A")

        key_metrics = metrics.key_levels
        if key_metrics.nearest and key_metrics.nearest.distance_pips is not None:
            key_line = (
                f"Key level: {key_metrics.nearest.distance_pips:.2f} pips tới "
                f"{key_metrics.nearest.name or '?'}"
            )
            if key_metrics.threshold_pips:
                key_line += f" (ngưỡng ≥ {key_metrics.threshold_pips:.2f})"
            lines.append(key_line)
        elif key_metrics.threshold_pips:
            lines.append(
                f"Key level: thiếu dữ liệu (ngưỡng ≥ {key_metrics.threshold_pips:.2f})"
            )
        else:
            lines.append("Key level: N/A")

        return "\n".join(lines)

    def _format_no_trade_metrics(self, metrics: Optional[NoTradeMetrics]) -> str:
        """Tạo chuỗi mô tả các chỉ số bảo vệ No-Trade."""

        if not metrics:
            return "Không có dữ liệu chỉ số."

        lines: list[str] = []

        spread = metrics.spread
        if spread.current_pips is not None:
            spread_line = f"Spread: {spread.current_pips:.2f} pips"
            if spread.threshold_pips:
                spread_line += f" / {spread.threshold_pips:.2f} pips"
            if spread.p90_5m_pips is not None:
                spread_line += f" (P90 5m {spread.p90_5m_pips:.2f})"
            elif spread.p90_30m_pips is not None:
                spread_line += f" (P90 30m {spread.p90_30m_pips:.2f})"
            if spread.atr_pct is not None:
                spread_line += f" | {spread.atr_pct:.1f}% ATR"
            lines.append(spread_line)
        else:
            lines.append("Spread: N/A")

        atr = metrics.atr
        if atr.atr_m5_pips is not None:
            atr_line = f"ATR M5: {atr.atr_m5_pips:.2f} pips"
            if atr.min_required_pips:
                atr_line += f" (ngưỡng {atr.min_required_pips:.2f})"
            if atr.atr_pct_of_adr20 is not None:
                atr_line += f" | {atr.atr_pct_of_adr20:.1f}% ADR20"
            lines.append(atr_line)
        else:
            lines.append("ATR M5: N/A")

        key_metrics = metrics.key_levels
        if key_metrics.nearest and key_metrics.nearest.distance_pips is not None:
            key_line = (
                f"Key level: {key_metrics.nearest.distance_pips:.2f} pips tới "
                f"{key_metrics.nearest.name or '?'}"
            )
            if key_metrics.threshold_pips:
                key_line += f" (ngưỡng ≥ {key_metrics.threshold_pips:.2f})"
            lines.append(key_line)
        elif key_metrics.threshold_pips:
            lines.append(
                f"Key level: thiếu dữ liệu (ngưỡng ≥ {key_metrics.threshold_pips:.2f})"
            )
        else:
            lines.append("Key level: N/A")

        return "\n".join(lines)

    def _apply_chart_updates(self, payload: Dict[str, Any]) -> None:
        """Áp dụng kết quả worker biểu đồ lên FigureCanvas."""
        if not self.ax_price or not self.canvas:
            return

        if not payload.get("success", True):
            self.ax_price.clear()
            self.ax_price.set_title(payload.get("message", "Lỗi không xác định"))
            self.canvas.draw_idle()
            return

        rates = payload.get("rates") or []
        if not rates:
            self.ax_price.clear()
            self.ax_price.set_title("Không có dữ liệu biểu đồ")
            self.canvas.draw_idle()
            return

        symbol = payload.get("symbol", "-")
        timeframe = payload.get("timeframe", "-")

        self.ax_price.clear()
        self._plot_price_data(rates)
        self._plot_trade_objects(symbol, payload.get("info"), payload.get("tick"), payload.get("positions", []))

        title_parts = [symbol]
        if timeframe:
            title_parts.append(timeframe)
        title_parts.append(f"{len(rates)} bars")
        self.ax_price.set_title(" | ".join(title_parts))
        if self.fig:
            self.fig.subplots_adjust(right=0.75)
        self.canvas.draw_idle()

    def _plot_price_data(self, rates: list[dict]):
        """Vẽ dữ liệu giá (nến hoặc đường) lên biểu đồ."""
        if not self.ax_price:
            return
        try:
            df_index = [datetime.strptime(r['time'], "%Y-%m-%d %H:%M:%S") for r in rates]
            if self.chart_type_var.get() == "Nến":
                xs = mdates.date2num(df_index)
                ohlc = np.column_stack((xs, [r['open'] for r in rates], [r['high'] for r in rates], [r['low'] for r in rates], [r['close'] for r in rates]))
                step = np.median(np.diff(xs)) if len(xs) > 1 else (1.0 / (24 * 60))
                width = step * 0.7
                candlestick_ohlc(self.ax_price, ohlc, width=float(width), colorup="#22c55e", colordown="#ef4444", alpha=0.9)
                self.ax_price.xaxis_date()
            else:
                self.ax_price.plot(df_index, [r['close'] for r in rates], color="#0ea5e9", lw=1.2)
            self.ax_price.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
        except Exception as e:
            logger.error(f"Lỗi khi vẽ dữ liệu giá: {e}")

    def _plot_trade_objects(self, sym: str, info: Any, tick: Any, positions: list):
        """Vẽ các đối tượng giao dịch (lệnh, giá) và đường giá real-time lên biểu đồ."""
        if not self.ax_price:
            return
        try:
            digits = 5
            if isinstance(info, dict):
                digits = int(info.get("digits", 5) or 5)
            elif info is not None:
                digits = int(getattr(info, "digits", 5) or 5)

            tick_bid = 0.0
            if isinstance(tick, dict):
                tick_bid = float(tick.get("bid") or 0.0)
            elif tick is not None:
                tick_bid = float(getattr(tick, "bid", 0.0) or 0.0)

            if tick_bid > 0:
                price_color = "#3b82f6"
                self.ax_price.axhline(tick_bid, color=price_color, ls="--", lw=1.0, alpha=0.9)
                price_label = f"BID {tick_bid:.{digits}f}"
                self.ax_price.text(1.01, tick_bid, " " + price_label, va="center", color=price_color, fontsize=9, weight='bold', transform=self.ax_price.get_yaxis_transform())

            # Vẽ các lệnh đang mở
            for p in positions:
                col = "#22c55e" if p.type == 0 else "#ef4444"
                self.ax_price.axhline(p.price_open, color=col, ls="--", lw=1.0, alpha=0.95)
                if p.sl > 0:
                    self.ax_price.axhline(p.sl, color="#ef4444", ls=":", lw=1.0, alpha=0.85)
                if p.tp > 0:
                    self.ax_price.axhline(p.tp, color="#22c55e", ls=":", lw=1.0, alpha=0.85)
                label = f"{'BUY' if p.type==0 else 'SELL'} {p.volume:.2f} @{p.price_open:.{digits}f}"
                self.ax_price.text(1.01, p.price_open, " " + label, va="center", color=col, fontsize=8, transform=self.ax_price.get_yaxis_transform())
        except Exception as e:
            logger.error(f"Lỗi khi vẽ các đối tượng giao dịch: {e}")

    def _show_tooltip(self, event: tk.Event, text: str) -> None:
        """Displays a tooltip window near the widget."""
        if self._tooltip_window:
            self._tooltip_window.destroy()

        x = event.x_root + 20
        y = event.y_root + 10

        self._tooltip_window = tk.Toplevel(self.app_ui.root)
        self._tooltip_window.wm_overrideredirect(True)
        self._tooltip_window.wm_geometry(f"+{x}+{y}")

        label = ttk.Label(
            self._tooltip_window,
            text=text,
            justify="left",
            background="#ffffe0",
            relief="solid",
            borderwidth=1,
            padding=5,
        )
        label.pack(ipadx=1)

    def _hide_tooltip(self) -> None:
        """Destroys the tooltip window."""
        if self._tooltip_window:
            self._tooltip_window.destroy()
            self._tooltip_window = None
