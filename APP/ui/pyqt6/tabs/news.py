"""Tab Tin tức kinh tế cho PyQt6."""

from __future__ import annotations

from typing import Iterable, Mapping, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QHBoxLayout,
)

from APP.ui.state import UiConfigState


class NewsTabWidget(QWidget):
    """Hiển thị danh sách tin tức và bộ lọc blackout."""

    manual_refresh_requested = pyqtSignal()
    override_toggled = pyqtSignal(bool)

    def __init__(self, config_state: UiConfigState, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._config_state = config_state

        self.override_checkbox = QCheckBox("Tạm thời bỏ qua chặn tin tức", self)
        self.override_checkbox.stateChanged.connect(self._emit_override)

        self.refresh_button = QPushButton("Refresh ngay", self)
        self.refresh_button.clicked.connect(self.manual_refresh_requested)

        self.status_label = QLabel("Chưa tải dữ liệu tin tức", self)
        self._provider_summary: str = ""

        self.table = QTableWidget(self)
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels([
            "Thời gian (Local)",
            "Quốc gia",
            "Sự kiện",
            "Ảnh hưởng",
            "Actual",
            "Forecast",
            "Previous",
            "Surprise",
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)

        self._build_layout()

    # ------------------------------------------------------------------
    def _build_layout(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        header = QLabel("Theo dõi tin tức quan trọng")
        header.setProperty("class", "h2")
        layout.addWidget(header)

        filters = QLabel(
            f"Chặn trước {self._config_state.news.block_before_min} phút / sau "
            f"{self._config_state.news.block_after_min} phút"
        )
        filters.setObjectName("newsFilters")
        layout.addWidget(filters)

        controls = QHBoxLayout()
        controls.addWidget(self.override_checkbox)
        controls.addStretch(1)
        controls.addWidget(self.refresh_button)
        layout.addLayout(controls)

        layout.addWidget(self.status_label)
        layout.addWidget(self.table)

    # ------------------------------------------------------------------
    def update_events(
        self,
        events: Iterable[dict],
        *,
        source: str | None = None,
        latency_sec: float | None = None,
        providers: Mapping[str, Mapping[str, object]] | None = None,
    ) -> None:
        if providers is not None:
            self.set_provider_state(providers)

        events = list(events)
        self.table.setRowCount(len(events))

        for row, event in enumerate(events):
            values = self._format_event_row(event)
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                elif column in (3, 7):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                else:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(row, column, item)

        summary = getattr(self, "_provider_summary", "")
        if not events:
            message = (
                "Không có tin tức quan trọng nào. Kiểm tra lại kết nối mạng hoặc cấu hình."
            )
            if summary:
                message = f"{message}\nNguồn dữ liệu: {summary}"
            self.status_label.setText(message)
            return

        latency_text = f"{latency_sec:.1f}s" if latency_sec is not None else "?"
        message = f"Đã tải {len(events)} sự kiện (độ trễ {latency_text})."
        if summary:
            message = f"{message}\nNguồn dữ liệu: {summary}"
        self.status_label.setText(message)

    def set_loading(self, loading: bool) -> None:
        self.refresh_button.setEnabled(not loading)
        if loading:
            self.status_label.setText("Đang tải dữ liệu tin tức…")

    def set_provider_state(self, providers: Mapping[str, Mapping[str, object]] | None) -> None:
        """Chuẩn hóa trạng thái provider phục vụ hiển thị UI."""

        if not providers:
            self._provider_summary = ""
            return

        state_labels = {
            "ready": "sẵn sàng",
            "degraded": "giới hạn",
            "error": "lỗi",
            "timeout": "timeout",
            "backoff": "tạm dừng",
            "cancelled": "đã hủy",
            "disabled": "tắt",
            "pending": "đang chạy",
        }
        summary_parts: list[str] = []
        for name, info in sorted(providers.items()):
            label = name.upper()
            state = str(info.get("state") or "không xác định").lower()
            state_text = state_labels.get(state, state)
            piece = f"{label}: {state_text}"

            event_count = info.get("event_count")
            if isinstance(event_count, int) and event_count > 0 and state == "ready":
                piece += f" ({event_count})"

            error = info.get("error")
            notes = info.get("notes") or []
            if error:
                piece += f" - {error}"
            elif notes:
                piece += f" - {notes[0]}"

            summary_parts.append(piece)

        self._provider_summary = " | ".join(summary_parts)

    def _emit_override(self, state: int) -> None:
        enabled = state == Qt.CheckState.Checked.value
        self.override_toggled.emit(enabled)

    # ------------------------------------------------------------------
    @staticmethod
    def _format_event_row(event: dict) -> list[str]:
        when = event.get("when_local")
        if hasattr(when, "strftime"):
            when_text = when.strftime("%Y-%m-%d %H:%M")
        else:
            when_text = str(when or "—")

        def _fmt(value: object, suffix: str = "") -> str:
            if value in (None, ""):
                return "—"
            try:
                return f"{float(value):.2f}{suffix}"
            except (TypeError, ValueError):
                return str(value)

        surprise = event.get("surprise_score")
        surprise_dir = str(event.get("surprise_direction") or "").lower()
        if surprise in (None, ""):
            surprise_text = "—"
        else:
            arrow = "↑" if surprise_dir == "positive" else "↓" if surprise_dir == "negative" else ""
            try:
                surprise_text = f"{float(surprise):+.2f}{arrow}"
            except (TypeError, ValueError):
                surprise_text = f"{surprise}{arrow}"

        impact_raw = str(event.get("impact") or "").lower()
        if "high" in impact_raw or impact_raw.endswith("3"):
            impact = "High"
        elif "medium" in impact_raw or impact_raw.endswith("2"):
            impact = "Medium"
        else:
            impact = impact_raw.capitalize() or "Low"

        return [
            when_text,
            str(event.get("country") or "—"),
            str(event.get("title") or "—"),
            impact,
            _fmt(event.get("actual")),
            _fmt(event.get("forecast")),
            _fmt(event.get("previous")),
            surprise_text,
        ]
