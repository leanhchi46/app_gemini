# -*- coding: utf-8 -*-
"""
Quản lý tab biểu đồ trong giao diện người dùng.

Hiển thị dữ liệu giá, thông tin tài khoản, các lệnh đang mở và lịch sử giao dịch.
Tương tác với các service để lấy dữ liệu và hiển thị một cách an toàn.
"""

from __future__ import annotations

import logging
from dataclasses import replace
import tkinter as tk
from datetime import datetime
from tkinter import ttk
from typing import TYPE_CHECKING, Any, Dict, Optional

from concurrent.futures import CancelledError, Future

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
    class Figure: pass
    class FigureCanvasTkAgg: pass
    class NavigationToolbar2Tk: pass
    MATPLOTLIB_AVAILABLE = False

# Các import cục bộ
from APP.core.trading import conditions
from APP.services import mt5_service
from APP.ui.controllers.chart_controller import ChartController, ChartStreamConfig
from APP.utils import threading_utils
from APP.utils.threading_utils import CancelToken

if TYPE_CHECKING:
    from APP.ui.app_ui import AppUI
    from APP.utils.safe_data import SafeData

logger = logging.getLogger(__name__)


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

        self._controller = ChartController(
            threading_manager=self.app.threading_manager,
            ui_queue=self.app.ui_queue,
            backlog_limit=self._backlog_limit,
        )

        self.root.after(200, self.start)
        self.root.after(400, self._redraw_chart_safe)
        logger.debug("Kết thúc hàm __init__ của ChartTab.")

    def _init_vars(self):
        """Khởi tạo các biến Tkinter và trạng thái."""
        logger.debug("Bắt đầu hàm _init_vars.")
        self.tf_var = tk.StringVar(value="M15")
        self.n_candles_var = tk.IntVar(value=150)
        self.refresh_secs_var = tk.IntVar(value=1)  # Giới hạn 1s để đáp ứng realtime tick
        self.chart_type_var = tk.StringVar(value="Nến")
        self._after_job: Optional[str] = None
        self._running = False
        self._last_bar_time: Optional[datetime] = None
        self._stream_active = False
        self._controller: Optional[ChartController] = None
        self._backlog_limit = 50

        # Biến cho biểu đồ
        self.fig: Optional[Figure] = None
        self.ax_price: Optional[Any] = None
        self.canvas: Optional[FigureCanvasTkAgg] = None
        self.toolbar: Optional[NavigationToolbar2Tk] = None

        # Biến cho panel tài khoản
        self.acc_balance = tk.StringVar(value="-")
        self.acc_equity = tk.StringVar(value="-")
        self.acc_margin = tk.StringVar(value="-")
        self.acc_leverage = tk.StringVar(value="-")
        self.acc_currency = tk.StringVar(value="-")
        self.acc_status = tk.StringVar(value="Chưa kết nối MT5")

        # Biến cho panel No-Trade
        self.nt_session_gate = tk.StringVar(value="-")
        self.nt_reasons = tk.StringVar(value="")
        self.nt_events = tk.StringVar(value="")
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
        self._build_account_panel(right_col)
        self._build_notrade_panel(right_col)

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

    def _build_notrade_panel(self, parent: ttk.Frame):
        """Xây dựng panel điều kiện không giao dịch."""
        nt_box = ttk.LabelFrame(parent, text="Điều kiện giao dịch", padding=8)
        nt_box.grid(row=1, column=0, sticky="nsew", pady=(6, 0))
        nt_box.columnconfigure(1, weight=1)
        ttk.Label(nt_box, text="Phiên giao dịch:").grid(row=0, column=0, sticky="w")
        ttk.Label(nt_box, textvariable=self.nt_session_gate).grid(row=0, column=1, sticky="e")
        ttk.Label(nt_box, text="Lý do No-Trade:").grid(row=1, column=0, sticky="nw", pady=(4, 0))
        ttk.Label(nt_box, textvariable=self.nt_reasons, wraplength=260, justify="left").grid(row=2, column=0, columnspan=2, sticky="w")
        ttk.Label(nt_box, text="Sự kiện sắp tới:").grid(row=3, column=0, sticky="nw", pady=(6, 0))
        ttk.Label(nt_box, textvariable=self.nt_events, wraplength=260, justify="left").grid(row=4, column=0, columnspan=2, sticky="w")

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

        current_config = self.app._snapshot_config()
        if current_config.mt5.symbol != stream_config.symbol:
            updated_mt5 = replace(current_config.mt5, symbol=stream_config.symbol)
        else:
            updated_mt5 = current_config.mt5

        updated_chart = replace(
            current_config.chart,
            timeframe=stream_config.timeframe,
            num_candles=stream_config.candles,
            chart_type=stream_config.chart_type,
        )

        current_config = replace(current_config, mt5=updated_mt5, chart=updated_chart)

        cancel_token.raise_if_cancelled()
        safe_mt5_data = mt5_service.get_market_data(
            current_config.mt5, timezone_name=current_config.no_run.timezone
        )
        if not safe_mt5_data.is_valid():
            return {"mt5_data": None, "status_message": "Không lấy được dữ liệu MT5."}

        tasks = [
            (conditions.check_no_trade_conditions, (safe_mt5_data, current_config, self.app.news_service), {}),
            (self.app.news_service.get_upcoming_events, (current_config.mt5.symbol,), {}),
            (mt5_service.get_history_deals, (current_config.mt5.symbol,), {"days": 7}),
        ]
        results = threading_utils.run_in_parallel(tasks)
        cancel_token.raise_if_cancelled()

        return {
            "mt5_data": safe_mt5_data,
            "no_trade_reasons": results.get("check_no_trade_conditions", []),
            "upcoming_events": results.get("get_upcoming_events", []),
            "history_deals": results.get("get_history_deals", []),
            "status_message": "Kết nối MT5 OK",
        }

    def _apply_data_updates(self, payload: Dict[str, Any]):
        """
        Áp dụng dữ liệu được lấy từ luồng nền lên các widget UI.
        Hàm này phải được gọi từ luồng chính (UI thread).
        """
        safe_mt5_data: Optional[SafeData] = payload.get("mt5_data")
        no_trade_reasons: list[str] = payload.get("no_trade_reasons", [])
        upcoming_events: list[dict] = payload.get("upcoming_events", [])
        history_deals: list[dict] = payload.get("history_deals", [])
        status_message: Optional[str] = payload.get("status_message")

        if status_message:
            self.acc_status.set(status_message)

        if not safe_mt5_data or not safe_mt5_data.is_valid():
            logger.debug("Bỏ qua cập nhật chi tiết do không có dữ liệu MT5 hợp lệ.")
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
        if no_trade_reasons:
            self.nt_reasons.set("- " + "\n- ".join(no_trade_reasons))
        else:
            self.nt_reasons.set("Không có")

        if upcoming_events:
            events_str = "\n".join(
                f"- {e['when_local'].strftime('%H:%M')} ({e.get('country', 'N/A')}): {e.get('title', 'N/A')}"
                for e in upcoming_events[:3] # Hiển thị 3 sự kiện gần nhất
            )
            self.nt_events.set(events_str)
        else:
            self.nt_events.set("Không có sự kiện quan trọng sắp tới.")

    def _chart_drawing_worker(self, stream_config: ChartStreamConfig, cancel_token: CancelToken) -> Dict[str, Any]:
        """Worker chuẩn bị payload biểu đồ có hỗ trợ cancel."""

        try:
            if not mt5_service.is_connected():
                return {"success": False, "message": "MT5 chưa sẵn sàng"}

            sym = stream_config.symbol
            if not sym:
                return {"success": False, "message": "Chưa chọn Symbol"}

            tf_map = {
                "M1": mt5_service.mt5.TIMEFRAME_M1,
                "M5": mt5_service.mt5.TIMEFRAME_M5,
                "M15": mt5_service.mt5.TIMEFRAME_M15,
                "H1": mt5_service.mt5.TIMEFRAME_H1,
                "H4": mt5_service.mt5.TIMEFRAME_H4,
                "D1": mt5_service.mt5.TIMEFRAME_D1,
            }
            tf_code = tf_map.get(stream_config.timeframe, mt5_service.mt5.TIMEFRAME_M15)
            cnt = stream_config.candles

            cancel_token.raise_if_cancelled()
            rates = mt5_service._series_from_mt5(sym, tf_code, cnt)

            if not rates:
                return {"success": False, "message": "Không có dữ liệu"}

            cancel_token.raise_if_cancelled()
            info = mt5_service.mt5.symbol_info(sym)
            tick = mt5_service.mt5.symbol_info_tick(sym)
            positions = mt5_service.mt5.positions_get(symbol=sym) or []

            return {
                "success": True,
                "rates": rates,
                "info": info,
                "tick": tick,
                "positions": positions,
                "symbol": sym,
                "timeframe": stream_config.timeframe,
                "chart_type": stream_config.chart_type,
            }
        except CancelledError:
            raise
        except Exception as e:  # pragma: no cover - logging path
            logger.error(f"Lỗi trong worker vẽ biểu đồ: {e}", exc_info=True)
            return {"success": False, "message": f"Lỗi worker: {e}"}

    def _apply_chart_updates(self, payload: Dict[str, Any]) -> None:
        """
        Áp dụng dữ liệu đã chuẩn bị từ worker lên biểu đồ Matplotlib.
        Hàm này phải được gọi từ luồng UI.
        """
        if not MATPLOTLIB_AVAILABLE or not self.ax_price or not self.canvas:
            return

        if not payload.get("success"):
            self.ax_price.clear()
            self.ax_price.set_title(payload.get("message", "Lỗi không xác định"))
            self.canvas.draw_idle()
            return

        # Giải nén payload
        rates = payload["rates"]
        sym = payload["symbol"]
        timeframe = payload["timeframe"]

        # Bắt đầu vẽ
        self.ax_price.clear()
        self._plot_price_data(rates)
        self._plot_trade_objects(sym, payload["info"], payload["tick"], payload["positions"])

        self.ax_price.set_title(f"{sym}  •  {timeframe}  •  {len(rates)} bars")
        if self.fig:
            self.fig.subplots_adjust(right=0.75)
        self.canvas.draw_idle()

    def _plot_price_data(self, rates: list[dict]):
        """Vẽ dữ liệu giá (nến hoặc đường) lên biểu đồ."""
        if not self.ax_price: return
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
        if not self.ax_price: return
        try:
            digits = info.digits if info else 5

            # Vẽ đường giá real-time
            if tick and tick.bid > 0:
                current_price = tick.bid
                price_color = "#3b82f6" # Blue
                self.ax_price.axhline(current_price, color=price_color, ls="--", lw=1.0, alpha=0.9)
                price_label = f"BID {current_price:.{digits}f}"
                self.ax_price.text(1.01, current_price, " " + price_label, va="center", color=price_color, fontsize=9, weight='bold', transform=self.ax_price.get_yaxis_transform())

            # Vẽ các lệnh đang mở
            for p in positions:
                col = "#22c55e" if p.type == 0 else "#ef4444"
                self.ax_price.axhline(p.price_open, color=col, ls="--", lw=1.0, alpha=0.95)
                if p.sl > 0: self.ax_price.axhline(p.sl, color="#ef4444", ls=":", lw=1.0, alpha=0.85)
                if p.tp > 0: self.ax_price.axhline(p.tp, color="#22c55e", ls=":", lw=1.0, alpha=0.85)
                label = f"{'BUY' if p.type==0 else 'SELL'} {p.volume:.2f} @{p.price_open:.{digits}f}"
                self.ax_price.text(1.01, p.price_open, " " + label, va="center", color=col, fontsize=8, transform=self.ax_price.get_yaxis_transform())
        except Exception as e:
            logger.error(f"Lỗi khi vẽ các đối tượng giao dịch: {e}")

    def _reset_and_redraw(self, event: Any = None) -> None:
        """Đặt lại trạng thái và buộc vẽ lại biểu đồ."""
        logger.debug("Đặt lại trạng thái và vẽ lại biểu đồ do hành động của người dùng.")
        self._last_bar_time = None
        controller = self._ensure_controller()
        controller.update_config(self._build_stream_config())
        if self._stream_active:
            controller.request_snapshot()

    def _redraw_chart_safe(self) -> None:
        """
        Yêu cầu controller cập nhật biểu đồ theo cấu hình hiện tại.
        """
        controller = self._ensure_controller()
        controller.update_config(self._build_stream_config())
        if self._stream_active:
            controller.request_snapshot()
