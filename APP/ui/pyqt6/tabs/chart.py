"""Tab Biểu đồ sử dụng PyQt6."""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
    QPlainTextEdit,
)

from APP.ui.controllers import ChartStreamConfig
from APP.ui.state import UiConfigState


class ChartTabWidget(QWidget):
    """Phiên bản PyQt6 cho tab biểu đồ và thông tin MT5."""

    settings_changed = pyqtSignal(ChartStreamConfig)
    refresh_requested = pyqtSignal()
    snapshot_requested = pyqtSignal()

    def __init__(self, config_state: UiConfigState, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._config_state = config_state

        self.symbol_input = QLineEdit(config_state.mt5.symbol or "XAUUSD", self)
        self.timeframe_combo = QComboBox(self)
        self.timeframe_combo.addItems(["M1", "M5", "M15", "H1", "H4", "D1"])
        current_tf = config_state.chart.timeframe
        if current_tf:
            index = self.timeframe_combo.findText(current_tf)
            if index >= 0:
                self.timeframe_combo.setCurrentIndex(index)

        self.candle_spin = QSpinBox(self)
        self.candle_spin.setRange(50, 5000)
        self.candle_spin.setSingleStep(25)
        self.candle_spin.setValue(config_state.chart.num_candles)

        self.chart_type_combo = QComboBox(self)
        self.chart_type_combo.addItems(["Line", "Candlestick"])
        default_type = (config_state.chart.chart_type or "Line").lower()
        if "candlestick" in default_type or "nến" in default_type:
            default_label = "Candlestick"
        else:
            default_label = "Line"
        index = self.chart_type_combo.findText(default_label)
        if index >= 0:
            self.chart_type_combo.setCurrentIndex(index)

        self.refresh_button = QPushButton("Làm mới dữ liệu", self)
        self.refresh_button.clicked.connect(self.refresh_requested)
        self.snapshot_button = QPushButton("Lấy snapshot", self)
        self.snapshot_button.clicked.connect(self.snapshot_requested)

        self.chart_output = QPlainTextEdit(self)
        self.chart_output.setPlaceholderText("Snapshot biểu đồ hoặc OHLC sẽ xuất hiện tại đây…")
        self.chart_output.setReadOnly(True)

        self.metrics_output = QPlainTextEdit(self)
        self.metrics_output.setPlaceholderText("Số liệu No-Trade, vị thế mở hoặc lịch sử lệnh…")
        self.metrics_output.setReadOnly(True)

        self._build_layout()
        self._connect_change_signals()

    # ------------------------------------------------------------------
    def _build_layout(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        header = QLabel("Thiết lập stream biểu đồ")
        header.setProperty("class", "h2")
        layout.addWidget(header)

        form = QFormLayout()
        form.addRow("Ký hiệu", self.symbol_input)
        form.addRow("Khung thời gian", self.timeframe_combo)
        form.addRow("Số nến", self.candle_spin)
        form.addRow("Kiểu biểu đồ", self.chart_type_combo)
        layout.addLayout(form)

        action_row = QHBoxLayout()
        action_row.addWidget(self.refresh_button)
        action_row.addWidget(self.snapshot_button)
        action_row.addStretch(1)
        layout.addLayout(action_row)

        splitter = QSplitter(self)
        splitter.setOrientation(Qt.Orientation.Vertical)  # type: ignore[attr-defined]
        splitter.addWidget(self.chart_output)
        splitter.addWidget(self.metrics_output)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter)

    def _connect_change_signals(self) -> None:
        self.symbol_input.textChanged.connect(lambda _value: self._emit_settings())
        self.timeframe_combo.currentTextChanged.connect(lambda _value: self._emit_settings())
        self.candle_spin.valueChanged.connect(lambda _value: self._emit_settings())
        self.chart_type_combo.currentTextChanged.connect(lambda _value: self._emit_settings())

    # ------------------------------------------------------------------
    def current_config(self) -> ChartStreamConfig:
        return ChartStreamConfig(
            symbol=self.symbol_input.text().strip() or "XAUUSD",
            timeframe=self.timeframe_combo.currentText(),
            candles=int(self.candle_spin.value()),
            chart_type=self.chart_type_combo.currentText().lower(),
        )

    def set_snapshot_text(self, text: str) -> None:
        self.chart_output.setPlainText(text)

    def set_metrics_text(self, text: str) -> None:
        self.metrics_output.setPlainText(text)

    def _emit_settings(self) -> None:
        self.settings_changed.emit(self.current_config())
