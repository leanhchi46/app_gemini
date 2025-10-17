# -*- coding: utf-8 -*-
"""Application entry point."""

from __future__ import annotations

import argparse
import logging
import sys
import warnings
from pathlib import Path
from typing import Any, Optional

# Ensure project root is on sys.path so that relative imports work when running directly
try:
    project_root = Path(__file__).resolve().parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
except (NameError, IndexError):
    project_root = Path.cwd()
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

from APP.configs import workspace_config
from APP.configs.app_config import LoggingConfig
from APP.persistence.log_handler import setup_logging
from APP.ui.pyqt6 import PyQtApplication
from APP.ui.state import UiConfigState

logger = logging.getLogger(__name__)


def parse_arguments() -> argparse.Namespace:
    """Parse command-line arguments for the application."""

    parser = argparse.ArgumentParser(description="Automated Trading & Analysis UI")
    parser.add_argument(
        "--workspace",
        type=str,
        default=None,
        help="Path to workspace.json to load at startup.",
    )
    parser.add_argument(
        "--use-tk",
        action="store_true",
        help="Launch the deprecated Tkinter UI instead of the PyQt6 interface.",
    )
    return parser.parse_args()


def _emit_ui_backend_telemetry(backend: str) -> None:
    """Log lightweight telemetry about the selected UI backend."""

    logger.info("telemetry.ui_backend=%s", backend)


def _run_tk_legacy(initial_config: dict[str, Any]) -> int:
    """Start the legacy Tkinter UI for transitional purposes."""

    warnings.warn(
        "The Tkinter UI is deprecated and will be removed in a future release.",
        DeprecationWarning,
        stacklevel=2,
    )

    try:
        import tkinter as tk  # type: ignore[import-not-found]
    except ModuleNotFoundError as exc:  # pragma: no cover - optional dependency path
        logger.error("Tkinter is not available in this environment: %s", exc)
        return 1

    from APP.ui.app_ui import AppUI  # Local import to avoid importing Tk modules eagerly

    try:
        root = tk.Tk()
    except tk.TclError as exc:
        logger.error("Unable to initialise Tkinter UI: %s", exc)
        logger.info("Headless environment detected; skipping legacy UI startup.")
        return 1

    logger.info("Launching legacy Tkinter UI (deprecated mode).")
    app = AppUI(root, initial_config=initial_config)
    root.protocol("WM_DELETE_WINDOW", app.shutdown)
    root.mainloop()
    return 0


def main(workspace_path: Optional[str] = None, *, use_tk: bool = False) -> int:
    """Initialise logging, load configuration and start the requested UI backend."""

    try:
        workspace_config.setup_workspace()
        initial_config = workspace_config.load_config_from_file(workspace_path)

        logging_dict = initial_config.get("logging", {})
        logging_config = LoggingConfig(**logging_dict)
        setup_logging(config=logging_config)

        logger.info("Application starting...")

        if use_tk:
            _emit_ui_backend_telemetry("tkinter")
            logger.warning("Legacy Tkinter UI requested via --use-tk; this mode is deprecated.")
            return _run_tk_legacy(initial_config)

        config_state = UiConfigState.from_workspace_config(initial_config)
        _emit_ui_backend_telemetry("pyqt6")
        app = PyQtApplication(config_state=config_state)
        exit_code = app.run()
        logger.info("Application closed successfully.")
        return exit_code
    except Exception:
        logger.exception("Fatal exception occurred in main().")
        raise


if __name__ == "__main__":
    args = parse_arguments()
    sys.exit(main(workspace_path=args.workspace, use_tk=args.use_tk))
