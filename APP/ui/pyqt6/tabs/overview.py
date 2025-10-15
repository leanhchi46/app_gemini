"""Tab Tổng quan & điều phối phiên phân tích cho PyQt6."""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
    QPlainTextEdit,
    QProgressBar,
)

from APP.ui.state import AutorunState, UiConfigState


class OverviewTab(QWidget):
    """Hiển thị cấu hình workspace và phát tín hiệu hành động chính."""

    start_analysis_requested = pyqtSignal()
    cancel_analysis_requested = pyqtSignal()
    autorun_toggled = pyqtSignal(bool)
    autorun_interval_changed = pyqtSignal(int)
    save_workspace_requested = pyqtSignal()
    load_workspace_requested = pyqtSignal()

    def __init__(self, config_state: UiConfigState, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._config_state = config_state
        self._is_running = False

        self.status_label = QLabel("Chưa khởi động phiên phân tích")
        self.progress_bar = QProgressBar(self)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        self._indeterminate = False

        self.log_view = QPlainTextEdit(self)
        self.log_view.setReadOnly(True)
        self.log_view.setPlaceholderText("Nhật ký phiên làm việc sẽ xuất hiện tại đây…")

        self._autorun_checkbox = QCheckBox("Bật autorun phiên phân tích", self)
        self._autorun_checkbox.setChecked(config_state.autorun.enabled)
        self._autorun_checkbox.stateChanged.connect(self._on_toggle_autorun)

        self._autorun_interval = QSpinBox(self)
        self._autorun_interval.setRange(30, 3600)
        self._autorun_interval.setSingleStep(30)
        self._autorun_interval.setValue(config_state.autorun.interval_secs)
        self._autorun_interval.valueChanged.connect(self.autorun_interval_changed)

        self.start_button = QPushButton("Khởi động phân tích", self)
        self.start_button.clicked.connect(self._emit_start)

        self.cancel_button = QPushButton("Hủy phiên hiện tại", self)
        self.cancel_button.clicked.connect(self.cancel_analysis_requested)
        self.cancel_button.setEnabled(False)

        self.save_button = QPushButton("Lưu workspace", self)
        self.save_button.clicked.connect(self.save_workspace_requested)
        self.load_button = QPushButton("Nạp workspace", self)
        self.load_button.clicked.connect(self.load_workspace_requested)

        self._build_layout()
        self._refresh_status()

    # ------------------------------------------------------------------
    # Layout helpers
    # ------------------------------------------------------------------
    def _build_layout(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel("Tổng quan workspace")
        title.setProperty("class", "h2")
        layout.addWidget(title)

        form = QFormLayout()
        form.addRow("Thư mục lưu trữ", QLabel(self._config_state.folder.folder))
        form.addRow("Mô hình AI", QLabel(self._config_state.model))
        form.addRow("Số báo cáo nhớ ngữ cảnh", QLabel(str(self._config_state.context.n_reports)))
        form.addRow("Tự động lưu Markdown", QLabel(str(self._config_state.persistence.max_md_reports)))
        layout.addLayout(form)

        autorun_row = QHBoxLayout()
        autorun_row.addWidget(self._autorun_checkbox)
        autorun_row.addWidget(QLabel("Khoảng thời gian (giây):", self))
        autorun_row.addWidget(self._autorun_interval)
        autorun_row.addStretch(1)
        layout.addLayout(autorun_row)

        button_row = QHBoxLayout()
        button_row.addWidget(self.start_button)
        button_row.addWidget(self.cancel_button)
        button_row.addStretch(1)
        button_row.addWidget(self.save_button)
        button_row.addWidget(self.load_button)
        layout.addLayout(button_row)

        layout.addWidget(self.status_label)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.log_view)

    # ------------------------------------------------------------------
    # Public API for main window/logic layer
    # ------------------------------------------------------------------
    def append_log(self, message: str) -> None:
        """Thêm dòng nhật ký mới lên đầu vùng log."""

        existing = self.log_view.toPlainText()
        if existing:
            new_content = f"{message}\n{existing}"
        else:
            new_content = message
        self.log_view.setPlainText(new_content)

    def set_status(self, message: str, *, running: Optional[bool] = None) -> None:
        """Cập nhật trạng thái hiển thị và trạng thái nút."""

        self.status_label.setText(message)
        if running is not None:
            self._is_running = running
            self.start_button.setEnabled(not running)
            self.cancel_button.setEnabled(running)
            self.progress_bar.setVisible(running)
        self._refresh_status()

    def set_progress_visible(self, visible: bool) -> None:
        self.progress_bar.setVisible(visible)

    def set_progress_value(self, value: float) -> None:
        """Thiết lập giá trị phần trăm (0-100) cho thanh tiến trình."""

        clamped = max(0.0, min(100.0, value))
        if self._indeterminate:
            self.set_progress_indeterminate(False)
        self.progress_bar.setValue(int(round(clamped)))

    def set_progress_indeterminate(self, enabled: bool) -> None:
        """Chuyển thanh tiến trình sang chế độ vô định hoặc có giá trị."""

        if enabled and not self._indeterminate:
            self.progress_bar.setRange(0, 0)
            self._indeterminate = True
        elif not enabled and self._indeterminate:
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(0)
            self._indeterminate = False

    def set_autorun_state(self, enabled: bool, interval_secs: int) -> None:
        self._autorun_checkbox.setChecked(enabled)
        self._autorun_interval.setValue(interval_secs)

    def autorun_state(self) -> AutorunState:
        """Trả về trạng thái autorun hiện tại dưới dạng dataclass trung lập."""

        return AutorunState(
            enabled=self._autorun_checkbox.isChecked(),
            interval_secs=int(self._autorun_interval.value()),
        )

    # ------------------------------------------------------------------
    # Slots for internal widgets
    # ------------------------------------------------------------------
    def _emit_start(self) -> None:
        if self._is_running:
            return
        self.start_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.progress_bar.setVisible(True)
        self.start_analysis_requested.emit()

    def _on_toggle_autorun(self, state: int) -> None:
        enabled = state == Qt.CheckState.Checked.value
        self.autorun_toggled.emit(enabled)

    def _refresh_status(self) -> None:
        if self._is_running:
            self.status_label.setProperty("class", "status-running")
        else:
            self.status_label.setProperty("class", "status-idle")
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)
