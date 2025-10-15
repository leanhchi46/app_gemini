from __future__ import annotations

import json

import pytest

PyQt6 = pytest.importorskip("PyQt6")
from PyQt6.QtWidgets import QApplication, QFileDialog
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtCore import QUrl

from APP.ui.pyqt6.dialogs import DialogProvider, JsonPreviewDialog, ShutdownDialog


@pytest.fixture()
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_shutdown_dialog_clamps_progress(qapp) -> None:
    dialog = ShutdownDialog()
    dialog.update_progress("Bước 1", 150)
    assert dialog.progress_bar.value() == 100
    dialog.update_progress("Bước 2", -10)
    assert dialog.progress_bar.value() == 0
    dialog.close_dialog()


def test_dialog_provider_file_methods(monkeypatch, tmp_path, qapp) -> None:
    provider = DialogProvider()

    open_target = tmp_path / "input.json"
    save_target = tmp_path / "output.json"
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        staticmethod(lambda *args, **kwargs: (str(open_target), "JSON")),
    )
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *args, **kwargs: (str(save_target), "JSON")),
    )

    opened = provider.open_file(caption="Chọn", directory=str(tmp_path), filter="*.json")
    saved = provider.save_file(caption="Lưu", directory=str(tmp_path), filter="*.json")

    assert opened == str(open_target)
    assert saved == str(save_target)


def test_dialog_provider_show_json_and_open_path(monkeypatch, tmp_path, qapp) -> None:
    provider = DialogProvider()

    captured_url: list[QUrl] = []
    monkeypatch.setattr(
        QDesktopServices,
        "openUrl",
        lambda url: captured_url.append(url) or True,
    )

    payload = {"hello": "world"}
    dialog = provider.show_json_dialog(title="Kiểm tra", payload=payload)
    assert isinstance(dialog, JsonPreviewDialog)
    assert json.dumps(payload, ensure_ascii=False, indent=2) in dialog.text_area.toPlainText()
    dialog.close()

    path = tmp_path / "demo"
    path.mkdir()
    assert provider.open_path(str(path))
    assert captured_url and captured_url[0] == QUrl.fromLocalFile(str(path))
