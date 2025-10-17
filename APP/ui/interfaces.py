"""Protocol definitions for toolkit-agnostic UI adapters."""

from __future__ import annotations

import queue
from typing import Any, Protocol, runtime_checkable


class SupportsVar(Protocol):
    """Minimal interface for variable-like objects exposed by UI layers."""

    def get(self) -> Any:
        ...

    def set(self, value: Any) -> None:
        ...


class SupportsPromptManager(Protocol):
    """Subset of methods required from a prompt manager implementation."""

    def get_prompts(self) -> dict[str, str]:
        ...

    def load_prompts_from_disk(self, silent: bool = False) -> None:
        ...


class SupportsHistoryManager(Protocol):
    """Subset of methods required from a history manager implementation."""

    def refresh_all_lists(self) -> None:
        ...


@runtime_checkable
class AnalysisUi(Protocol):
    """Public contract expected by analysis controllers and workers."""

    ui_queue: queue.Queue[Any]
    threading_manager: Any
    prompt_manager: SupportsPromptManager
    history_manager: SupportsHistoryManager
    timeframe_detector: Any
    results: list[dict[str, Any]]
    combined_report_text: str
    stop_flag: bool
    folder_path: SupportsVar
    api_key_var: SupportsVar
    model_var: SupportsVar

    def ui_status(self, message: str) -> None:
        ...

    def ui_progress(self, value: float | None, *, indeterminate: bool = False) -> None:
        ...

    def ui_detail_replace(self, text: str) -> None:
        ...

    def show_error_message(self, title: str, message: str) -> None:
        ...

    def _update_tree_row(self, index: int, status: str) -> None:
        ...

    def _update_progress(self, current_step: int, total_steps: int) -> None:
        ...

    def _finalize_done(self) -> None:
        ...

    def _finalize_stopped(self) -> None:
        ...
