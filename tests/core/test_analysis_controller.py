# -*- coding: utf-8 -*-
"""Unit test cho AnalysisController và cancel token."""

from __future__ import annotations

from concurrent.futures import Future
from pathlib import Path

import sys

sys.path.append(str(Path(__file__).resolve().parents[2]))

import pytest

from APP.core.analysis_controller import AnalysisController
from APP.utils.threading_utils import CancelToken, TaskRecord


class DummyThreadingManager:
    def __init__(self) -> None:
        self.submitted: list[dict] = []
        self.cancelled: list[str] = []

    def new_cancel_token(self) -> CancelToken:
        return CancelToken()

    def submit(self, **kwargs):  # type: ignore[no-untyped-def]
        future: Future = Future()
        record = TaskRecord(
            future=future,
            token=kwargs["cancel_token"],
            name=kwargs.get("name", ""),
            group=kwargs.get("group", ""),
            metadata=kwargs.get("metadata", {}),
        )
        self.submitted.append({"kwargs": kwargs, "record": record})
        return record

    def cancel_group(self, group: str) -> None:
        self.cancelled.append(group)


class DummyWorker:
    def __init__(self, *args, **kwargs):
        pass

    def run(self, cancel_token: CancelToken | None = None):  # type: ignore[override]
        return {"status": "completed"}


@pytest.fixture()
def controller(monkeypatch: pytest.MonkeyPatch):
    from APP.core import analysis_controller

    monkeypatch.setattr(analysis_controller, "AnalysisWorker", DummyWorker)
    tm = DummyThreadingManager()
    import queue

    ui_queue = queue.Queue()
    ctrl = AnalysisController(threading_manager=tm, ui_queue=ui_queue)
    return ctrl, tm


def test_start_session_records_metadata(controller):
    ctrl, tm = controller
    ctrl.start_session("sess-1", app=None, cfg=None)
    assert tm.submitted[0]["kwargs"]["group"] == "analysis.session"
    assert tm.submitted[0]["kwargs"]["metadata"]["session_id"] == "sess-1"


def test_stop_session_triggers_cancel(controller):
    ctrl, tm = controller
    ctrl.start_session("sess-2", app=None, cfg=None)
    ctrl.stop_session("sess-2")
    assert "analysis.upload" in tm.cancelled
    assert "analysis.session" in tm.cancelled
