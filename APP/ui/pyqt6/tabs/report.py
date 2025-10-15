"""Tab Báo cáo (Report) dành cho PyQt6."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QPlainTextEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


@dataclass(slots=True)
class ReportEntry:
    """Một hàng dữ liệu trong bảng báo cáo."""

    path: Path
    display_name: str
    status: str


class ReportTabWidget(QWidget):
    """Hiển thị danh sách báo cáo và phần chi tiết tương tự Tkinter."""

    refresh_requested = pyqtSignal()
    open_requested = pyqtSignal(str)
    open_folder_requested = pyqtSignal()
    delete_requested = pyqtSignal(str)
    selection_changed = pyqtSignal(str)

    def __init__(self, base_folder: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._base_folder = base_folder
        self._entries: list[ReportEntry] = []

        self._status_label = QLabel("Chưa tải danh sách báo cáo")

        self.table = QTableWidget(self)
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["#", "Tệp", "Trạng thái"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)

        self.detail_output = QPlainTextEdit(self)
        self.detail_output.setReadOnly(True)
        self.detail_output.setPlaceholderText("Chi tiết báo cáo sẽ hiển thị tại đây…")

        self.refresh_button = QPushButton("Làm mới", self)
        self.refresh_button.clicked.connect(self.refresh_requested.emit)
        self.open_button = QPushButton("Mở báo cáo", self)
        self.open_button.clicked.connect(self._emit_open)
        self.open_button.setEnabled(False)
        self.delete_button = QPushButton("Xoá", self)
        self.delete_button.clicked.connect(self._emit_delete)
        self.delete_button.setEnabled(False)
        self.folder_button = QPushButton("Mở thư mục Reports", self)
        self.folder_button.clicked.connect(self.open_folder_requested.emit)

        self._build_layout()

    # ------------------------------------------------------------------
    def _build_layout(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(12)

        controls = QHBoxLayout()
        controls.addWidget(self.refresh_button)
        controls.addStretch(1)
        controls.addWidget(self.open_button)
        controls.addWidget(self.delete_button)
        controls.addWidget(self.folder_button)
        outer.addLayout(controls)
        outer.addWidget(self._status_label)

        content = QGridLayout()
        content.setColumnStretch(0, 2)
        content.setColumnStretch(1, 3)
        content.setHorizontalSpacing(12)
        content.setVerticalSpacing(12)

        table_group = QGroupBox("Danh sách báo cáo")
        table_layout = QVBoxLayout(table_group)
        table_layout.addWidget(self.table)
        content.addWidget(table_group, 0, 0)

        detail_group = QGroupBox("Chi tiết tổng hợp")
        detail_layout = QVBoxLayout(detail_group)
        detail_layout.addWidget(self.detail_output)
        content.addWidget(detail_group, 0, 1)

        outer.addLayout(content)

    # ------------------------------------------------------------------
    def set_entries(self, entries: Sequence[ReportEntry]) -> None:
        """Nạp danh sách báo cáo vào bảng."""

        self._entries = list(entries)
        self.table.setRowCount(len(self._entries))
        for row, entry in enumerate(self._entries):
            index_item = QTableWidgetItem(str(row + 1))
            index_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            index_item.setData(Qt.ItemDataRole.UserRole, str(entry.path))
            name_item = QTableWidgetItem(entry.display_name)
            status_item = QTableWidgetItem(entry.status)
            self.table.setItem(row, 0, index_item)
            self.table.setItem(row, 1, name_item)
            self.table.setItem(row, 2, status_item)
        self._status_label.setText(f"Đang hiển thị {len(self._entries)} báo cáo trong {self._base_folder}")
        self.open_button.setEnabled(bool(self._entries) and bool(self.table.selectedItems()))
        self.delete_button.setEnabled(bool(self._entries) and bool(self.table.selectedItems()))

    def append_entries(self, entries: Iterable[ReportEntry]) -> None:
        """Thêm báo cáo mới vào cuối bảng."""

        current = list(self._entries)
        current.extend(entries)
        self.set_entries(current)

    def clear_entries(self) -> None:
        self._entries.clear()
        self.table.clearContents()
        self.table.setRowCount(0)
        self._status_label.setText("Chưa có báo cáo để hiển thị")
        self.open_button.setEnabled(False)
        self.delete_button.setEnabled(False)

    # ------------------------------------------------------------------
    def current_entry_path(self) -> Path | None:
        items = self.table.selectedItems()
        if not items:
            return None
        index_item = items[0]
        data = index_item.data(Qt.ItemDataRole.UserRole)
        if not data:
            return None
        return Path(str(data))

    def set_status(self, message: str) -> None:
        self._status_label.setText(message)

    def set_loading(self, loading: bool) -> None:
        self.refresh_button.setEnabled(not loading)
        self.open_button.setEnabled(not loading and bool(self.current_entry_path()))
        self.delete_button.setEnabled(not loading and bool(self.current_entry_path()))
        if loading:
            self._status_label.setText("Đang quét báo cáo…")

    def set_detail_text(self, text: str) -> None:
        self.detail_output.setPlainText(text)

    def append_detail_line(self, line: str) -> None:
        current = self.detail_output.toPlainText()
        if current:
            self.detail_output.setPlainText(f"{line}\n{current}")
        else:
            self.detail_output.setPlainText(line)

    def clear_detail(self) -> None:
        self.detail_output.clear()

    # ------------------------------------------------------------------
    def _on_selection_changed(self) -> None:
        path = self.current_entry_path()
        enabled = path is not None
        self.open_button.setEnabled(enabled)
        self.delete_button.setEnabled(enabled)
        if path is not None:
            self.selection_changed.emit(str(path))

    def _emit_open(self) -> None:
        path = self.current_entry_path()
        if path is not None:
            self.open_requested.emit(str(path))

    def _emit_delete(self) -> None:
        path = self.current_entry_path()
        if path is not None:
            self.delete_requested.emit(str(path))
