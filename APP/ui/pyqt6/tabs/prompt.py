"""Tab quản lý prompt cho giao diện PyQt6."""

from __future__ import annotations

from typing import Dict, Optional

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
    QPlainTextEdit,
)

from APP.ui.state import PromptState, UiConfigState


class PromptTabWidget(QWidget):
    """Tab nhập prompt với hai vùng No Entry/Entry Run."""

    load_requested = pyqtSignal(str)
    save_requested = pyqtSignal(str, dict)
    reformat_requested = pyqtSignal(str, str)
    browse_requested = pyqtSignal()

    def __init__(self, config_state: UiConfigState, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._config_state = config_state

        self.path_edit = QLineEdit(config_state.prompt.file_path, self)
        self.autoload_checkbox = QCheckBox("Tự động nạp prompt khi khởi động", self)
        self.autoload_checkbox.setChecked(config_state.prompt.auto_load_from_disk)

        self.tabs = QTabWidget(self)
        self.no_entry_editor = QPlainTextEdit(self)
        self.no_entry_editor.setPlaceholderText("Prompt No Entry…")
        self.entry_editor = QPlainTextEdit(self)
        self.entry_editor.setPlaceholderText("Prompt Entry Run…")

        self.tabs.addTab(self.no_entry_editor, "No Entry")
        self.tabs.addTab(self.entry_editor, "Entry Run")

        self.load_button = QPushButton("Tải từ tệp", self)
        self.save_button = QPushButton("Lưu prompt", self)
        self.reformat_button = QPushButton("Định dạng lại", self)
        self.browse_button = QPushButton("Chọn tệp…", self)

        self.status_label = QLabel("Chưa tải prompt.", self)

        self._build_layout()
        self._connect_signals()

    # ------------------------------------------------------------------
    def _build_layout(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel("Quản lý Prompt AI", self)
        title.setProperty("class", "h2")
        layout.addWidget(title)

        form = QFormLayout()
        form.addRow("Đường dẫn tệp", self.path_edit)
        form.addRow("Tùy chọn", self.autoload_checkbox)
        layout.addLayout(form)

        button_row = QHBoxLayout()
        button_row.addWidget(self.load_button)
        button_row.addWidget(self.save_button)
        button_row.addWidget(self.reformat_button)
        button_row.addStretch(1)
        button_row.addWidget(self.browse_button)
        layout.addLayout(button_row)

        layout.addWidget(self.tabs)
        layout.addWidget(self.status_label)

    def _connect_signals(self) -> None:
        self.load_button.clicked.connect(lambda: self.load_requested.emit(self.path_edit.text()))
        self.save_button.clicked.connect(lambda: self.save_requested.emit(self.path_edit.text(), self.prompt_payload()))
        self.reformat_button.clicked.connect(lambda: self.reformat_requested.emit(self.current_mode(), self.current_text()))
        self.browse_button.clicked.connect(self.browse_requested)

    # ------------------------------------------------------------------
    def current_mode(self) -> str:
        return "no_entry" if self.tabs.currentIndex() == 0 else "entry_run"

    def current_text(self) -> str:
        editor = self.no_entry_editor if self.current_mode() == "no_entry" else self.entry_editor
        return editor.toPlainText()

    def prompt_payload(self) -> Dict[str, object]:
        return {
            "no_entry": self.no_entry_editor.toPlainText(),
            "entry_run": self.entry_editor.toPlainText(),
            "auto_load": self.autoload_checkbox.isChecked(),
        }

    def prompt_state(self) -> PromptState:
        """Đóng gói đường dẫn và tuỳ chọn auto-load dưới dạng PromptState."""

        return PromptState(
            file_path=self.current_path(),
            auto_load_from_disk=self.autoload_checkbox.isChecked(),
        )

    def current_path(self) -> str:
        return self.path_edit.text().strip()

    def prompt_texts(self) -> Dict[str, str]:
        return {
            "no_entry": self.no_entry_editor.toPlainText(),
            "entry_run": self.entry_editor.toPlainText(),
        }

    def set_prompt_content(self, mode: str, text: str) -> None:
        editor = self.no_entry_editor if mode == "no_entry" else self.entry_editor
        editor.setPlainText(text)

    def set_autoload(self, enabled: bool) -> None:
        self.autoload_checkbox.setChecked(enabled)

    def set_file_path(self, path: str) -> None:
        self.path_edit.setText(path)

    def set_status(self, message: str) -> None:
        self.status_label.setText(message)

    def set_loading(self, loading: bool) -> None:
        for button in (self.load_button, self.save_button, self.reformat_button, self.browse_button):
            button.setEnabled(not loading)

