"""Tab quản lý lịch sử báo cáo và ngữ cảnh cho giao diện PyQt6."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
    QPlainTextEdit,
)


@dataclass(frozen=True)
class HistoryEntry:
    """Đại diện một tệp lịch sử hiển thị trên UI."""

    path: Path
    display_name: str


class HistoryTabWidget(QWidget):
    """Tab PyQt6 cho phép duyệt báo cáo Markdown và file ngữ cảnh."""

    refresh_requested = pyqtSignal(str)
    preview_requested = pyqtSignal(str)
    open_requested = pyqtSignal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.status_label = QLabel("Chưa tải danh sách lịch sử.", self)

        self.reports_list = QListWidget(self)
        self.reports_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.reports_list.itemSelectionChanged.connect(lambda: self._emit_preview("reports"))
        self.reports_list.itemDoubleClicked.connect(lambda _: self._emit_open("reports"))

        self.json_list = QListWidget(self)
        self.json_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.json_list.itemSelectionChanged.connect(lambda: self._emit_preview("contexts"))
        self.json_list.itemDoubleClicked.connect(lambda _: self._emit_open("contexts"))

        self.preview_box = QPlainTextEdit(self)
        self.preview_box.setReadOnly(True)
        self.preview_box.setPlaceholderText("Nội dung tệp sẽ hiển thị tại đây…")

        self.refresh_reports_button = QPushButton("Làm mới báo cáo", self)
        self.refresh_reports_button.clicked.connect(lambda: self.refresh_requested.emit("reports"))

        self.refresh_json_button = QPushButton("Làm mới ngữ cảnh", self)
        self.refresh_json_button.clicked.connect(lambda: self.refresh_requested.emit("contexts"))

        self.open_button = QPushButton("Mở thư mục chứa", self)
        self.open_button.clicked.connect(lambda: self._emit_open(self._current_category()))

        self._build_layout()

    # ------------------------------------------------------------------
    def _build_layout(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel("Lịch sử báo cáo & ngữ cảnh")
        title.setProperty("class", "h2")
        layout.addWidget(title)

        action_bar = QFormLayout()
        action_bar.addRow("Trạng thái", self.status_label)
        layout.addLayout(action_bar)

        button_row = QGridLayout()
        button_row.addWidget(self.refresh_reports_button, 0, 0)
        button_row.addWidget(self.refresh_json_button, 0, 1)
        button_row.addWidget(self.open_button, 0, 2)
        button_row.setColumnStretch(3, 1)
        layout.addLayout(button_row)

        splitter = QSplitter(self)
        splitter.setOrientation(Qt.Orientation.Horizontal)

        reports_group = QGroupBox("Báo cáo (.md)", self)
        rg_layout = QVBoxLayout(reports_group)
        rg_layout.addWidget(self.reports_list)
        splitter.addWidget(reports_group)

        json_group = QGroupBox("Ngữ cảnh (.json)", self)
        jg_layout = QVBoxLayout(json_group)
        jg_layout.addWidget(self.json_list)
        splitter.addWidget(json_group)

        splitter.addWidget(self.preview_box)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 2)
        splitter.setStretchFactor(2, 3)

        layout.addWidget(splitter)

    # ------------------------------------------------------------------
    def set_files(self, kind: str, entries: Iterable[HistoryEntry]) -> None:
        """Cập nhật danh sách tệp cho loại tương ứng."""

        mapping = {"reports": self.reports_list, "contexts": self.json_list}
        if kind not in mapping:
            return

        widget = mapping[kind]
        widget.clear()

        for entry in entries:
            item = QListWidgetItem(entry.display_name)
            widget.addItem(item)
            item.setData(Qt.ItemDataRole.UserRole, str(entry.path))

        if not widget.count():
            widget.addItem("(Không có tệp phù hợp)")

    def set_status(self, message: str) -> None:
        self.status_label.setText(message)

    def set_preview_text(self, text: str) -> None:
        self.preview_box.setPlainText(text)

    def clear_preview(self) -> None:
        self.preview_box.clear()

    def set_loading(self, kind: str, loading: bool) -> None:
        if kind == "reports":
            self.refresh_reports_button.setEnabled(not loading)
        elif kind == "contexts":
            self.refresh_json_button.setEnabled(not loading)

    # ------------------------------------------------------------------
    def _emit_preview(self, kind: str) -> None:
        path = self._resolve_selected_path(kind)
        if path:
            self.preview_requested.emit(str(path))

    def _emit_open(self, kind: Optional[str]) -> None:
        if not kind:
            return
        path = self._resolve_selected_path(kind)
        if path:
            self.open_requested.emit(str(path))

    def _resolve_selected_path(self, kind: str) -> Optional[Path]:
        mapping = {
            "reports": self.reports_list,
            "contexts": self.json_list,
        }
        if kind not in mapping:
            return None

        widget = mapping[kind]
        current_items = widget.selectedItems()
        if not current_items:
            return None
        item = current_items[0]
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data:
            return None
        return Path(str(data))

    def _current_category(self) -> Optional[str]:
        if self.reports_list.hasFocus():
            return "reports"
        if self.json_list.hasFocus():
            return "contexts"
        # ưu tiên danh sách đang có lựa chọn
        if self.reports_list.selectedItems():
            return "reports"
        if self.json_list.selectedItems():
            return "contexts"
        return None

