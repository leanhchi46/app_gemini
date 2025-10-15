# -*- coding: utf-8 -*-
"""UI implementation for the Chart tab."""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, Iterable, Optional

import tkinter as tk
from tkinter import scrolledtext, ttk

from concurrent.futures import Future

from APP.core.trading import conditions
from APP.core.trading.no_trade_metrics import NoTradeMetrics, collect_no_trade_metrics
from APP.services import mt5_service
from APP.ui.controllers.chart_controller import ChartController, ChartStreamConfig
from APP.utils import threading_utils
from APP.utils.safe_data import SafeData
from APP.utils.threading_utils import CancelToken

try:  # pragma: no cover - optional dependency
    from matplotlib.backends._backend_tk import NavigationToolbar2Tk
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    from matplotlib.figure import Figure
    import matplotlib.dates as mdates
    from mplfinance.original_flavor import candlestick_ohlc
    import numpy as np

    MATPLOTLIB_AVAILABLE = True
except ImportError:  # pragma: no cover - graceful fallback
    class Figure:  # type: ignore[too-many-ancestors]
        """Lightweight placeholder used when matplotlib is unavailable."""

        def add_subplot(self, *_args: Any, **_kwargs: Any) -> Any:
            return None

        def subplots_adjust(self, **_kwargs: Any) -> None:
            return None

    class FigureCanvasTkAgg:  # type: ignore[too-many-ancestors]
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            raise RuntimeError("Matplotlib chưa được cài đặt.")

    class NavigationToolbar2Tk:  # type: ignore[too-many-ancestors]
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            raise RuntimeError("Matplotlib chưa được cài đặt.")

        def update(self) -> None:  # pragma: no cover - placeholder
            return None

    MATPLOTLIB_AVAILABLE = False
    mdates = None  # type: ignore[assignment]
    np = None  # type: ignore[assignment]
    candlestick_ohlc = None  # type: ignore[assignment]

if TYPE_CHECKING:
    from APP.configs.app_config import RunConfig
    from APP.ui.app_ui import AppUI
    from APP.ui.utils.ui_builder import UiBuilder

logger = logging.getLogger(__name__)

DEFAULT_SYMBOL = "XAUUSD"
MAX_EVENTS_DISPLAYED = 5

mt5_backend = getattr(mt5_service, "mt5", None)


class ChartTab:
    """Tkinter widgets and background coordination for the Chart tab."""

    def __init__(
        self,
        app_ui: AppUI,
        notebook: ttk.Notebook,
        ui_builder: Optional[UiBuilder] = None,
        controller: Optional[ChartController] = None,
    ) -> None:
        self.app_ui = app_ui
        self.notebook = notebook
        self.ui_builder = ui_builder
        self.app = app_ui  # Backwards compatibility alias
        self.root = app_ui.root

        self._controller: Optional[ChartController] = controller
        self._running = False
        self._stream_active = False
        self._after_job: Optional[str] = None
        self._backlog_limit = 50
        self._tooltip_window: Optional[tk.Toplevel] = None

        # Tkinter variables
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

        # UI component handles initialised during build steps
        self.tab = ttk.Frame(self.notebook, padding=8)
        self.tab.columnconfigure(0, weight=3)
        self.tab.columnconfigure(1, weight=2)
        self.tab.rowconfigure(1, weight=1)
        self.tab.rowconfigure(2, weight=1)
        self.notebook.add(self.tab, text="Chart")

        self.cbo_symbol: Optional[ttk.Combobox] = None
        self.cbo_tf: Optional[ttk.Combobox] = None
        self.cbo_chart_type: Optional[ttk.Combobox] = None
        self.fig: Optional[Figure] = None
        self.ax_price: Any = None
        self.canvas: Optional[FigureCanvasTkAgg] = None
        self.toolbar: Optional[NavigationToolbar2Tk] = None
        self.tree_pos: Optional[ttk.Treeview] = None
        self.tree_his: Optional[ttk.Treeview] = None
        self.pos_cols: tuple[str, ...] = ()
        self.his_cols: tuple[str, ...] = ()
        self._nt_reasons_box: Optional[scrolledtext.ScrolledText] = None
        self._nt_metrics_box: Optional[scrolledtext.ScrolledText] = None
        self._nt_events_box: Optional[scrolledtext.ScrolledText] = None

        self._build_controls()
        self._build_chart_area()
        self._build_right_panel()
        self._build_bottom_grids()

        logger.debug("ChartTab UI đã được khởi tạo hoàn chỉnh.")

    # ------------------------------------------------------------------
    # UI builders
    # ------------------------------------------------------------------
    def _build_controls(self) -> None:
        ctrl = ttk.Frame(self.tab)
        ctrl.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))

        ttk.Label(ctrl, text="Ký hiệu:").pack(side="left", padx=(0, 2))
        self.cbo_symbol = ttk.Combobox(
            ctrl,
            width=16,
            textvariable=self.app.mt5_symbol_var,
            state="normal",
            values=[],
        )
        self.cbo_symbol.pack(side="left", padx=(0, 10))
        self._populate_symbol_list()

        ttk.Label(ctrl, text="Khung:").pack(side="left", padx=(0, 2))
        self.cbo_tf = ttk.Combobox(
            ctrl,
            width=6,
            state="readonly",
            values=["M1", "M5", "M15", "H1", "H4", "D1"],
            textvariable=self.tf_var,
        )
        self.cbo_tf.pack(side="left", padx=(0, 10))
        self.cbo_tf.bind("<<ComboboxSelected>>", self._reset_and_redraw)

        ttk.Label(ctrl, text="Số nến:").pack(side="left", padx=(0, 2))
        spin_candles = ttk.Spinbox(
            ctrl,
            from_=50,
            to=5000,
            textvariable=self.n_candles_var,
            width=8,
            command=self._reset_and_redraw,
        )
        spin_candles.pack(side="left", padx=(0, 10))

        ttk.Label(ctrl, text="Kiểu:").pack(side="left", padx=(0, 2))
        self.cbo_chart_type = ttk.Combobox(
            ctrl,
            width=8,
            state="readonly",
            values=["Đường", "Nến"],
            textvariable=self.chart_type_var,
        )
        self.cbo_chart_type.pack(side="left", padx=(0, 10))
        self.cbo_chart_type.bind("<<ComboboxSelected>>", self._reset_and_redraw)

        ttk.Label(ctrl, text="Làm mới (s):").pack(side="left", padx=(0, 2))
        ttk.Spinbox(ctrl, from_=1, to=3600, textvariable=self.refresh_secs_var, width=6)\
            .pack(side="left", padx=(0, 10))
        logger.debug("Kết thúc hàm _build_controls.")

    def _build_chart_area(self) -> None:
        chart_wrap = ttk.Frame(self.tab)
        chart_wrap.grid(row=1, column=0, sticky="nsew", padx=(0, 6))
        chart_wrap.rowconfigure(1, weight=1)
        chart_wrap.columnconfigure(0, weight=1)

        if not MATPLOTLIB_AVAILABLE:
            ttk.Label(
                chart_wrap,
                text="Vui lòng cài đặt Matplotlib và mplfinance để hiển thị biểu đồ.",
            ).grid(row=0, column=0, sticky="nsew")
            return

        self.fig = Figure(figsize=(6, 4), dpi=100, constrained_layout=False)
        self.ax_price = self.fig.add_subplot(1, 1, 1)
        self.canvas = FigureCanvasTkAgg(self.fig, master=chart_wrap)
        self.canvas.get_tk_widget().grid(row=1, column=0, sticky="nsew")

        tb_frame = ttk.Frame(chart_wrap)
        tb_frame.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        self.toolbar = NavigationToolbar2Tk(self.canvas, tb_frame)
        self.toolbar.update()

    def _build_right_panel(self) -> None:
        right_col = ttk.Frame(self.tab)
        right_col.grid(row=1, column=1, sticky="nsew")
        right_col.columnconfigure(0, weight=1)
        right_col.rowconfigure(1, weight=1)

        self._build_account_panel(right_col)
        self._build_notrade_panel(right_col)

    def _build_account_panel(self, parent: ttk.Frame) -> None:
        acc_box = ttk.LabelFrame(parent, text="Thông tin tài khoản", padding=8)
        acc_box.grid(row=0, column=0, sticky="nsew")
        acc_box.columnconfigure(1, weight=1)

        rows = (
            ("Balance:", self.acc_balance),
            ("Equity:", self.acc_equity),
            ("Free margin:", self.acc_margin),
            ("Leverage:", self.acc_leverage),
            ("Currency:", self.acc_currency),
        )
        for idx, (label, var) in enumerate(rows):
            ttk.Label(acc_box, text=label).grid(row=idx, column=0, sticky="w")
            ttk.Label(acc_box, textvariable=var).grid(row=idx, column=1, sticky="e")

        ttk.Separator(acc_box, orient="horizontal").grid(
            row=len(rows), column=0, columnspan=2, sticky="ew", pady=6
        )
        ttk.Label(acc_box, textvariable=self.acc_status, foreground="#666").grid(
            row=len(rows) + 1, column=0, columnspan=2, sticky="w"
        )

    def _build_notrade_panel(self, parent: ttk.Frame) -> None:
        nt_box = ttk.LabelFrame(parent, text="Điều kiện giao dịch", padding=8)
        nt_box.grid(row=1, column=0, sticky="nsew", pady=(6, 0))
        nt_box.columnconfigure(1, weight=1)
        for row in (3, 5, 7):
            nt_box.rowconfigure(row, weight=1)

        ttk.Label(nt_box, text="Trạng thái:").grid(row=0, column=0, sticky="w")
        ttk.Label(nt_box, textvariable=self.nt_status, foreground="#0f172a").grid(
            row=0, column=1, sticky="e"
        )
        ttk.Label(nt_box, text="Phiên giao dịch:").grid(row=1, column=0, sticky="w")
        ttk.Label(nt_box, textvariable=self.nt_session_gate).grid(
            row=1, column=1, sticky="e"
        )

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

        self._set_nt_text(self._nt_reasons_box, "Đang thu thập dữ liệu…")
        self._set_nt_text(self._nt_metrics_box, "Đang thu thập dữ liệu…")
        self._set_nt_text(self._nt_events_box, "Đang thu thập dữ liệu…")

    def _build_bottom_grids(self) -> None:
        grids = ttk.Frame(self.tab)
        grids.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=(6, 0))
        grids.columnconfigure(0, weight=1)
        grids.columnconfigure(1, weight=1)
        grids.rowconfigure(0, weight=1)

        self._build_positions_grid(grids)
        self._build_history_grid(grids)

    def _build_positions_grid(self, parent: ttk.Frame) -> None:
        pos_box = ttk.LabelFrame(parent, text="Lệnh đang mở", padding=6)
        pos_box.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        pos_box.rowconfigure(0, weight=1)
        pos_box.columnconfigure(0, weight=1)

        self.pos_cols = ("ticket", "type", "lots", "price", "sl", "tp", "pnl")
        self.tree_pos = ttk.Treeview(pos_box, columns=self.pos_cols, show="headings", height=6)
        for column, width in zip(self.pos_cols, (90, 110, 70, 110, 110, 110, 100)):
            self.tree_pos.heading(column, text=column.upper())
            anchor = "e" if column in {"lots", "price", "sl", "tp", "pnl"} else "w"
            self.tree_pos.column(column, width=width, anchor=anchor)
        self.tree_pos.grid(row=0, column=0, sticky="nsew")

        scr = ttk.Scrollbar(pos_box, orient="vertical", command=self.tree_pos.yview)
        self.tree_pos.configure(yscrollcommand=scr.set)
        scr.grid(row=0, column=1, sticky="ns")

    def _build_history_grid(self, parent: ttk.Frame) -> None:
        his_box = ttk.LabelFrame(parent, text="Lịch sử (deals gần nhất)", padding=6)
        his_box.grid(row=0, column=1, sticky="nsew", padx=(4, 0))
        his_box.rowconfigure(0, weight=1)
        his_box.columnconfigure(0, weight=1)

        self.his_cols = ("time", "ticket", "type", "volume", "price", "profit")
        self.tree_his = ttk.Treeview(his_box, columns=self.his_cols, show="headings", height=6)
        for column, width in zip(self.his_cols, (140, 90, 70, 80, 110, 100)):
            self.tree_his.heading(column, text=column.upper())
            anchor = "e" if column in {"volume", "price", "profit"} else "w"
            self.tree_his.column(column, width=width, anchor=anchor)
        self.tree_his.grid(row=0, column=0, sticky="nsew")

        scr = ttk.Scrollbar(his_box, orient="vertical", command=self.tree_his.yview)
        self.tree_his.configure(yscrollcommand=scr.set)
        scr.grid(row=0, column=1, sticky="ns")

    # ------------------------------------------------------------------
    # Stream lifecycle
    # ------------------------------------------------------------------
    def start(self) -> None:
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
        logger.info("ChartTab đã bắt đầu stream dữ liệu.")

    def stop(self) -> None:
        self._running = False
        if self._after_job:
            self.root.after_cancel(self._after_job)
            self._after_job = None
        if self._controller:
            self._controller.stop_stream()
        self._stream_active = False
        logger.info("ChartTab đã dừng stream dữ liệu.")

    def _ensure_controller(self) -> ChartController:
        if not self._controller:
            self._controller = ChartController(
                threading_manager=self.app.threading_manager,
                ui_queue=self.app.ui_queue,
                backlog_limit=self._backlog_limit,
            )
        return self._controller

    def _schedule_next_tick(self, *, immediate: bool = False) -> None:
        delay_ms = 1 if immediate else self._compute_tick_interval_ms()
        self._after_job = self.root.after(delay_ms, self._tick)

    def _compute_tick_interval_ms(self) -> int:
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
        run_config = self.app._snapshot_config()
        updated_mt5 = replace(run_config.mt5, symbol=stream_config.symbol)
        updated_chart = replace(
            run_config.chart,
            timeframe=stream_config.timeframe,
            num_candles=stream_config.candles,
            chart_type=stream_config.chart_type,
        )
        return replace(run_config, mt5=updated_mt5, chart=updated_chart)

    # ------------------------------------------------------------------
    # Workers
    # ------------------------------------------------------------------
    def _chart_drawing_worker(
        self, stream_config: ChartStreamConfig, cancel_token: CancelToken
    ) -> Dict[str, Any]:
        if not mt5_service.is_connected():
            return {"success": False, "message": "MT5 chưa kết nối."}
        if mt5_backend is None:
            return {"success": False, "message": "Thiếu thư viện MetaTrader5."}

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
            rates = mt5_service._series_from_mt5(
                stream_config.symbol, tf_code, stream_config.candles
            )
        except Exception as exc:  # pragma: no cover - defensive logging
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

    def _update_info_worker(
        self, stream_config: ChartStreamConfig, cancel_token: CancelToken
    ) -> Dict[str, Any]:
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

        tasks: Iterable[tuple[Any, tuple[Any, ...], Dict[str, Any]]] = [
            (
                conditions.check_no_trade_conditions,
                (safe_mt5_data, run_config, self.app.news_service),
                {"now_utc": datetime.now(timezone.utc)},
            ),
            (self.app.news_service.get_upcoming_events, (run_config.mt5.symbol,), {}),
            (mt5_service.get_history_deals, (run_config.mt5.symbol,), {"days": 7}),
        ]
        results = threading_utils.run_in_parallel(tasks)
        cancel_token.raise_if_cancelled()

        no_trade_result = results.get("check_no_trade_conditions")
        if isinstance(no_trade_result, conditions.NoTradeCheckResult):
            no_trade_reasons = no_trade_result.to_messages(include_warnings=True)
            metrics = no_trade_result.metrics
        else:
            no_trade_reasons = list(no_trade_result or [])
            metrics = None

        if metrics is None:
            metrics = collect_no_trade_metrics(safe_mt5_data, run_config)

        return {
            "mt5_data": safe_mt5_data,
            "no_trade_reasons": no_trade_reasons,
            "no_trade_result": no_trade_result,
            "no_trade_metrics": metrics,
            "upcoming_events": results.get("get_upcoming_events", []),
            "history_deals": results.get("get_history_deals", []),
            "status_message": "Kết nối MT5 OK",
            "run_config": run_config,
        }

    # ------------------------------------------------------------------
    # Worker callbacks executed on UI thread
    # ------------------------------------------------------------------
    def _apply_data_updates(self, payload: Dict[str, Any]) -> None:
        safe_mt5_data: Optional[SafeData] = payload.get("mt5_data")
        no_trade_reasons: list[str] = payload.get("no_trade_reasons", [])
        no_trade_result = payload.get("no_trade_result")
        no_trade_metrics: Optional[NoTradeMetrics] = payload.get("no_trade_metrics")
        upcoming_events: list[dict] = payload.get("upcoming_events", [])
        history_deals: list[dict] = payload.get("history_deals", [])
        status_message: Optional[str] = payload.get("status_message")
        current_config: Optional["RunConfig"] = payload.get("run_config")

        if current_config is None:
            try:
                current_config = self.app._snapshot_config()
            except Exception:  # pragma: no cover - defensive logging
                logger.exception("Không thể chụp RunConfig hiện tại khi cập nhật UI chart.")

        if status_message:
            self.acc_status.set(status_message)

        if not safe_mt5_data or not safe_mt5_data.is_valid():
            self.nt_status.set("❓ Không có dữ liệu")
            self._set_nt_text(self._nt_reasons_box, "Không lấy được dữ liệu MT5.")
            self._set_nt_text(self._nt_metrics_box, "-")
            self._set_nt_text(self._nt_events_box, "-")
            return

        account = safe_mt5_data.get("account", {})
        self.acc_balance.set(f"{float(account.get('balance', 0.0)):.2f}")
        self.acc_equity.set(f"{float(account.get('equity', 0.0)):.2f}")
        self.acc_margin.set(f"{float(account.get('free_margin', 0.0)):.2f}")
        self.acc_leverage.set(str(account.get("leverage", "-")))
        self.acc_currency.set(account.get("currency", "-"))
        if not status_message:
            self.acc_status.set("Kết nối MT5 OK")

        killzone_active = safe_mt5_data.get("killzone_active", "-")
        self.nt_session_gate.set(str(killzone_active or "-"))

        self._refresh_positions_table(safe_mt5_data.get("positions", []))
        self._refresh_history_table(history_deals)

        status_text = "✅ Điều kiện phù hợp"
        if isinstance(no_trade_result, conditions.NoTradeCheckResult):
            if no_trade_result.has_blockers():
                status_text = "⛔ Bị chặn giao dịch"
            elif no_trade_result.warnings:
                status_text = "⚠️ Có cảnh báo"
        elif no_trade_reasons:
            status_text = "⚠️ Có cảnh báo"
        self.nt_status.set(status_text)

        reasons_text = (
            "\n".join(f"- {reason}" for reason in no_trade_reasons)
            if no_trade_reasons
            else "Không có vi phạm."
        )
        self._set_nt_text(self._nt_reasons_box, reasons_text)

        metrics = no_trade_metrics or collect_no_trade_metrics(safe_mt5_data, current_config)
        metrics_text = self._format_no_trade_metrics(metrics)
        self._set_nt_text(self._nt_metrics_box, metrics_text)

        events_text = self._format_events(upcoming_events)
        self._set_nt_text(self._nt_events_box, events_text)

    def _apply_chart_updates(self, payload: Dict[str, Any]) -> None:
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

        self.ax_price.clear()
        self._plot_price_data(rates)
        self._plot_trade_objects(
            payload.get("symbol", "-"),
            payload.get("info"),
            payload.get("tick"),
            payload.get("positions", []),
        )

        title_parts = [payload.get("symbol", "-")]
        timeframe = payload.get("timeframe")
        if timeframe:
            title_parts.append(str(timeframe))
        title_parts.append(f"{len(rates)} bars")
        self.ax_price.set_title(" | ".join(title_parts))
        if self.fig:
            self.fig.subplots_adjust(right=0.75)
        self.canvas.draw_idle()

    # ------------------------------------------------------------------
    # Helper logic
    # ------------------------------------------------------------------
    def _refresh_positions_table(self, positions: Iterable[dict[str, Any]]) -> None:
        if not self.tree_pos:
            return
        self.tree_pos.delete(*self.tree_pos.get_children())
        for entry in positions:
            values = (
                entry.get("ticket"),
                entry.get("type"),
                f"{float(entry.get('volume', 0.0)):.2f}",
                f"{float(entry.get('price_open', 0.0)):.5f}",
                f"{float(entry.get('sl', 0.0)):.5f}",
                f"{float(entry.get('tp', 0.0)):.5f}",
                f"{float(entry.get('profit', 0.0)):.2f}",
            )
            self.tree_pos.insert("", "end", values=values)

    def _refresh_history_table(self, history: Iterable[dict[str, Any]]) -> None:
        if not self.tree_his:
            return
        self.tree_his.delete(*self.tree_his.get_children())
        for entry in history:
            time_val = entry.get("time")
            if isinstance(time_val, datetime):
                time_disp = time_val.strftime("%Y-%m-%d %H:%M")
            else:
                time_disp = str(time_val)
            values = (
                time_disp,
                entry.get("ticket"),
                entry.get("type"),
                entry.get("volume"),
                entry.get("price"),
                entry.get("profit"),
            )
            self.tree_his.insert("", "end", values=values)

    def _reset_and_redraw(self, *_args: Any) -> None:
        controller = self._ensure_controller()
        controller.update_config(self._build_stream_config())
        controller.request_snapshot()

    def _mt5_tf(self, tf_str: str) -> Optional[int]:
        backend = mt5_backend
        if backend is None:
            return None
        mapping = {
            "M1": getattr(backend, "TIMEFRAME_M1", None),
            "M5": getattr(backend, "TIMEFRAME_M5", None),
            "M15": getattr(backend, "TIMEFRAME_M15", None),
            "H1": getattr(backend, "TIMEFRAME_H1", None),
            "H4": getattr(backend, "TIMEFRAME_H4", None),
            "D1": getattr(backend, "TIMEFRAME_D1", None),
        }
        return mapping.get(tf_str.upper())

    def _populate_symbol_list(self) -> None:
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
            except Exception as exc:  # pragma: no cover - logging pathway
                logger.error("Không thể lấy danh sách symbol: %s", exc)
                names = []
            self.app.ui_queue.put(lambda lst=names: self._apply_symbol_list(lst))

        record.future.add_done_callback(on_done)

    def _apply_symbol_list(self, names: list[str]) -> None:
        if not self.cbo_symbol:
            return
        self.cbo_symbol["values"] = names
        current_symbol = self.app.mt5_symbol_var.get()
        if current_symbol and current_symbol in names:
            return
        if DEFAULT_SYMBOL in names:
            self.app.mt5_symbol_var.set(DEFAULT_SYMBOL)
        elif names:
            self.app.mt5_symbol_var.set(names[0])

    def _tick(self) -> None:
        if not self._running:
            return
        if self._controller and self._stream_active:
            self._controller.trigger_refresh()
        self._schedule_next_tick()

    def _set_nt_text(self, widget: Optional[scrolledtext.ScrolledText], value: str) -> None:
        if not widget:
            return
        widget.configure(state="normal")
        widget.delete("1.0", tk.END)
        text = (value or "").strip()
        widget.insert("1.0", (text or "Không có dữ liệu.") + "\n")
        widget.configure(state="disabled")

    def _format_no_trade_metrics(self, metrics: Optional[NoTradeMetrics]) -> str:
        if not metrics:
            return "Không có dữ liệu chỉ số."

        lines: list[str] = []

        spread = metrics.spread
        if spread.current_pips is not None:
            segment = f"Spread: {spread.current_pips:.2f} pips"
            if spread.threshold_pips:
                segment += f" / {spread.threshold_pips:.2f} pips"
            if spread.p90_5m_pips is not None:
                segment += f" (P90 5m {spread.p90_5m_pips:.2f})"
            elif spread.p90_30m_pips is not None:
                segment += f" (P90 30m {spread.p90_30m_pips:.2f})"
            if spread.atr_pct is not None:
                segment += f" | {spread.atr_pct:.1f}% ATR"
            lines.append(segment)
        else:
            lines.append("Spread: N/A")

        atr = metrics.atr
        if atr.atr_m5_pips is not None:
            segment = f"ATR M5: {atr.atr_m5_pips:.2f} pips"
            if atr.min_required_pips:
                segment += f" (ngưỡng {atr.min_required_pips:.2f})"
            if atr.atr_pct_of_adr20 is not None:
                segment += f" | {atr.atr_pct_of_adr20:.1f}% ADR20"
            lines.append(segment)
        else:
            lines.append("ATR M5: N/A")

        key_metrics = metrics.key_levels
        if key_metrics.nearest and key_metrics.nearest.distance_pips is not None:
            segment = (
                f"Key level: {key_metrics.nearest.distance_pips:.2f} pips tới "
                f"{key_metrics.nearest.name or '?'}"
            )
            if key_metrics.threshold_pips:
                segment += f" (ngưỡng ≥ {key_metrics.threshold_pips:.2f})"
            lines.append(segment)
        elif key_metrics.threshold_pips:
            lines.append(
                f"Key level: thiếu dữ liệu (ngưỡng ≥ {key_metrics.threshold_pips:.2f})"
            )
        else:
            lines.append("Key level: N/A")

        collected_at = metrics.collected_at
        if collected_at:
            lines.append(f"Thu thập lúc: {collected_at}")

        return "\n".join(lines)

    def _plot_price_data(self, rates: list[dict]) -> None:
        if not self.ax_price or not MATPLOTLIB_AVAILABLE:
            return
        try:
            timestamps = [datetime.strptime(row["time"], "%Y-%m-%d %H:%M:%S") for row in rates]
            closes = [row["close"] for row in rates]
            if self.chart_type_var.get() == "Nến" and candlestick_ohlc and np is not None:
                xs = mdates.date2num(timestamps)
                ohlc = np.column_stack(
                    (
                        xs,
                        [row["open"] for row in rates],
                        [row["high"] for row in rates],
                        [row["low"] for row in rates],
                        closes,
                    )
                )
                step = np.median(np.diff(xs)) if len(xs) > 1 else (1.0 / (24 * 60))
                width = float(step * 0.7)
                candlestick_ohlc(
                    self.ax_price,
                    ohlc,
                    width=width,
                    colorup="#22c55e",
                    colordown="#ef4444",
                    alpha=0.9,
                )
                self.ax_price.xaxis_date()
            else:
                self.ax_price.plot(timestamps, closes, color="#0ea5e9", lw=1.2)
            self.ax_price.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.error("Lỗi khi vẽ dữ liệu giá: %s", exc)

    def _plot_trade_objects(
        self,
        symbol: str,
        info: Any,
        tick: Any,
        positions: Iterable[dict[str, Any]],
    ) -> None:
        if not self.ax_price:
            return
        try:
            digits = 5
            if isinstance(info, dict):
                digits = int(info.get("digits", 5) or 5)
            elif info is not None:
                digits = int(getattr(info, "digits", 5) or 5)

            bid = 0.0
            if isinstance(tick, dict):
                bid = float(tick.get("bid") or 0.0)
            elif tick is not None:
                bid = float(getattr(tick, "bid", 0.0) or 0.0)

            if bid > 0:
                color = "#3b82f6"
                self.ax_price.axhline(bid, color=color, ls="--", lw=1.0, alpha=0.9)
                label = f"BID {bid:.{digits}f}"
                self.ax_price.text(
                    1.01,
                    bid,
                    " " + label,
                    va="center",
                    color=color,
                    fontsize=9,
                    weight="bold",
                    transform=self.ax_price.get_yaxis_transform(),
                )

            for position in positions:
                pos_type = position.get("type")
                price_open = float(position.get("price_open", 0.0) or 0.0)
                sl = float(position.get("sl", 0.0) or 0.0)
                tp = float(position.get("tp", 0.0) or 0.0)
                volume = float(position.get("volume", 0.0) or 0.0)

                colour = "#22c55e" if pos_type in (0, "BUY") else "#ef4444"
                self.ax_price.axhline(price_open, color=colour, ls="--", lw=1.0, alpha=0.95)
                if sl > 0:
                    self.ax_price.axhline(sl, color="#ef4444", ls=":", lw=1.0, alpha=0.85)
                if tp > 0:
                    self.ax_price.axhline(tp, color="#22c55e", ls=":", lw=1.0, alpha=0.85)
                label = f"{'BUY' if pos_type in (0, 'BUY') else 'SELL'} {volume:.2f} @{price_open:.{digits}f}"
                self.ax_price.text(
                    1.01,
                    price_open,
                    " " + label,
                    va="center",
                    color=colour,
                    fontsize=8,
                    transform=self.ax_price.get_yaxis_transform(),
                )
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.error("Lỗi khi vẽ các đối tượng giao dịch: %s", exc)

    def _format_events(self, events: Iterable[dict]) -> str:
        items: list[str] = []
        for event in events:
            if len(items) >= MAX_EVENTS_DISPLAYED:
                break
            when = event.get("when_local") or event.get("time")
            if isinstance(when, datetime):
                when_text = when.strftime("%d/%m %H:%M")
            else:
                when_text = str(when or "?")
            country = event.get("country") or event.get("region") or "?"
            title = event.get("title") or event.get("event") or "Sự kiện"
            impact = event.get("impact") or event.get("importance")
            suffix = f" ({impact})" if impact else ""
            items.append(f"- {when_text} [{country}] {title}{suffix}")
        if not items:
            return "Không có sự kiện sắp tới."
        return "\n".join(items)

    def _show_tooltip(self, event: tk.Event, text: str) -> None:
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
        if self._tooltip_window:
            self._tooltip_window.destroy()
            self._tooltip_window = None
