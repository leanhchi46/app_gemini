"""Các hộp thoại tiện ích phục vụ giao diện PyQt6."""

from __future__ import annotations

import json
from typing import Any, Iterable, Optional

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)


class ShutdownDialog(QDialog):
    """Hộp thoại hiển thị tiến trình tắt ứng dụng."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Đang đóng ứng dụng")
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        self.status_label = QLabel("Đang xử lý…", self)
        self.progress_bar = QProgressBar(self)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)

        layout.addWidget(self.status_label)
        layout.addWidget(self.progress_bar)

    def update_progress(self, message: str, percent: float) -> None:
        """Cập nhật thông tin tiến trình và ép giao diện vẽ lại."""

        self.status_label.setText(message)
        clamped = max(0.0, min(100.0, percent))
        self.progress_bar.setValue(int(round(clamped)))
        QApplication.processEvents()

    def close_dialog(self) -> None:
        """Đảm bảo hộp thoại đóng đúng chuẩn Qt."""

        self.accept()


class JsonPreviewDialog(QDialog):
    """Hiển thị nội dung JSON ở dạng chỉ đọc."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Xem JSON")
        self.setModal(True)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        self.text_area = QPlainTextEdit(self)
        self.text_area.setReadOnly(True)
        layout.addWidget(self.text_area)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

    def set_payload(self, payload: Any) -> None:
        """Định dạng dữ liệu và đưa vào khung hiển thị."""

        if isinstance(payload, str):
            text = payload
        else:
            try:
                text = json.dumps(payload, ensure_ascii=False, indent=2)
            except TypeError:
                text = str(payload)
        self.text_area.setPlainText(text)


class DialogProvider:
    """Tập hợp các tiện ích tương tác hộp thoại dành cho PyQt6."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        self._parent = parent

    # ------------------------------------------------------------------
    # File picker helpers
    # ------------------------------------------------------------------
    def open_file(
        self,
        *,
        caption: str,
        directory: str = "",
        filter: str = "",
    ) -> Optional[str]:
        path, _ = QFileDialog.getOpenFileName(self._parent, caption, directory, filter)
        return path or None

    def save_file(
        self,
        *,
        caption: str,
        directory: str = "",
        filter: str = "",
    ) -> Optional[str]:
        path, _ = QFileDialog.getSaveFileName(self._parent, caption, directory, filter)
        return path or None

    def select_directory(self, *, caption: str, directory: str = "") -> Optional[str]:
        path = QFileDialog.getExistingDirectory(self._parent, caption, directory)
        return path or None

    def open_path(self, path: str) -> bool:
        """Mở đường dẫn bằng ứng dụng mặc định của hệ điều hành."""

        return QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    # ------------------------------------------------------------------
    # Message box helpers
    # ------------------------------------------------------------------
    def ask_yes_no(self, *, title: str, message: str) -> bool:
        answer = QMessageBox.question(
            self._parent,
            title,
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def show_info(self, *, title: str, message: str) -> None:
        QMessageBox.information(self._parent, title, message)

    def show_warning(self, *, title: str, message: str) -> None:
        QMessageBox.warning(self._parent, title, message)

    def show_error(self, *, title: str, message: str) -> None:
        QMessageBox.critical(self._parent, title, message)

    # ------------------------------------------------------------------
    # Specialized dialogs
    # ------------------------------------------------------------------
    def create_shutdown_dialog(self) -> ShutdownDialog:
        dialog = ShutdownDialog(self._parent)
        dialog.show()
        QApplication.processEvents()
        return dialog

    def show_json_dialog(self, *, title: str, payload: Any) -> JsonPreviewDialog:
        dialog = JsonPreviewDialog(self._parent)
        dialog.setWindowTitle(title)
        dialog.set_payload(payload)
        dialog.show()
        QApplication.processEvents()
        return dialog


def ensure_dialog_sequence(dialogs: Iterable[QDialog]) -> None:
    """Tiện ích gọi processEvents cho danh sách dialog (phục vụ test)."""

    for dialog in dialogs:
        if dialog.isVisible():
            QApplication.processEvents()

