# -*- coding: utf-8 -*-
"""
Module for the Chart Tab in the application's UI.

This module contains the ChartTab class, which is responsible for creating,
arranging, and managing all the widgets within the 'Chart' tab of the main
application window. This includes controls for running analysis, displaying
reports, and showing trade status.
"""
from __future__ import annotations

import logging
import tkinter as tk
from tkinter import ttk
from typing import TYPE_CHECKING

# Configure logging
logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from APP.configs.app_config import RunConfig
    from APP.ui.app_ui import AppUI
    from APP.ui.controllers.chart_controller import ChartController
    from APP.ui.utils.ui_builder import UiBuilder

# Constants for UI layout and styling
PAD_X = 5
PAD_Y = 5
FONT_BOLD = ("Helvetica", 10, "bold")


class ChartTab:
    """
    Manages the UI components within the 'Chart' tab.

    This class encapsulates the creation and layout of all widgets,
    and connects UI events (like button clicks) to the appropriate
    controller methods.
    """

    def __init__(
        self,
        notebook: ttk.Notebook,
        app_ui: AppUI,
        ui_builder: UiBuilder,
        controller: ChartController,
    ):
        """
        Initializes the ChartTab.

        Args:
            notebook: The parent ttk.Notebook widget.
            app_ui: The main application UI instance.
            ui_builder: An instance of the UiBuilder for creating widgets.
            controller: The controller handling the logic for this tab.
        """
        self.notebook = notebook
        self.app_ui = app_ui
        self.ui_builder = ui_builder
        self.controller = controller

        # Main frame for this tab
        self.frame = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(self.frame, text="Chart")
        logger.debug("ChartTab frame added to the notebook.")

        # Widget references
        self.run_button: ttk.Button | None = None
        self.stop_button: ttk.Button | None = None
        self.report_text: tk.Text | None = None
        self.no_trade_text: tk.Text | None = None
        self.trade_status_var = tk.StringVar(value="STATUS: IDLE")

        # Tooltip handling
        self._tooltip_window: tk.Toplevel | None = None

    def setup_ui(self) -> None:
        """
        Creates and lays out the widgets for the chart tab.
        """
        logger.info("Setting up UI for ChartTab.")
        # Configure grid layout
        self.frame.columnconfigure(0, weight=1)
        self.frame.columnconfigure(1, weight=0, minsize=300)  # Right column fixed size
        self.frame.rowconfigure(0, weight=1)

        # Create main columns
        left_col = ttk.Frame(self.frame)
        left_col.grid(row=0, column=0, sticky="nsew", padx=(0, PAD_X), pady=PAD_Y)
        left_col.rowconfigure(0, weight=1)
        left_col.columnconfigure(0, weight=1)

        right_col = ttk.Frame(self.frame)
        right_col.grid(row=0, column=1, sticky="nsew", padx=(PAD_X, 0), pady=PAD_Y)
        right_col.rowconfigure(1, weight=1)  # Report display
        right_col.rowconfigure(2, weight=1)  # No-trade display
        right_col.columnconfigure(0, weight=1)

        # Populate columns
        self._create_chart_display(left_col)
        self._create_main_controls(right_col)
        self._create_report_display(right_col)
        self._create_no_trade_display(right_col)

    def _create_chart_display(self, parent: ttk.Frame) -> None:
        """Creates the chart display area."""
        chart_wrap = ttk.LabelFrame(parent, text="Chart Display")
        chart_wrap.grid(row=0, column=0, sticky="nsew", pady=(0, PAD_Y))
        chart_wrap.columnconfigure(0, weight=1)
        chart_wrap.rowconfigure(0, weight=1)

        # Placeholder for chart
        placeholder_label = ttk.Label(
            chart_wrap, text="Chart will be displayed here.", anchor="center"
        )
        placeholder_label.grid(row=0, column=0, sticky="nsew")

    def _create_main_controls(self, parent: ttk.Frame) -> None:
        """Creates the main 'Run' and 'Stop' buttons."""
        controls_wrap = ttk.LabelFrame(parent, text="Controls")
        controls_wrap.grid(row=0, column=0, sticky="ew", pady=(0, PAD_Y))
        controls_wrap.columnconfigure(0, weight=1)
        controls_wrap.columnconfigure(1, weight=1)

        self.run_button = ttk.Button(
            controls_wrap, text="RUN", command=self.controller.on_run_clicked
        )
        self.run_button.grid(row=0, column=0, sticky="ew", padx=PAD_X, pady=PAD_Y)

        self.stop_button = ttk.Button(
            controls_wrap, text="STOP", command=self.controller.on_stop_clicked, state="disabled"
        )
        self.stop_button.grid(row=0, column=1, sticky="ew", padx=PAD_X, pady=PAD_Y)

        status_label = ttk.Label(
            controls_wrap, textvariable=self.trade_status_var, anchor="center"
        )
        status_label.grid(row=1, column=0, columnspan=2, sticky="ew", padx=PAD_X, pady=PAD_Y)

    def _create_report_display(self, parent: ttk.Frame) -> None:
        """Creates the text area for displaying analysis reports."""
        report_wrap = ttk.LabelFrame(parent, text="AI Analysis Report")
        report_wrap.grid(row=1, column=0, sticky="nsew", pady=PAD_Y)
        report_wrap.columnconfigure(0, weight=1)
        report_wrap.rowconfigure(0, weight=1)

        self.report_text = tk.Text(
            report_wrap, wrap="word", height=10, state="disabled"
        )
        self.report_text.grid(row=0, column=0, sticky="nsew")

        scrollbar = ttk.Scrollbar(
            report_wrap, orient="vertical", command=self.report_text.yview
        )
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.report_text.config(yscrollcommand=scrollbar.set)

    def _create_no_trade_display(self, parent: ttk.Frame) -> None:
        """Creates the text area for displaying NO-TRADE reasons."""
        nt_box = ttk.LabelFrame(parent, text="NO-TRADE Conditions")
        nt_box.grid(row=2, column=0, sticky="nsew", pady=(PAD_Y, 0))
        nt_box.columnconfigure(0, weight=1)
        nt_box.rowconfigure(0, weight=1)

        self.no_trade_text = tk.Text(
            nt_box, wrap="word", height=5, state="disabled"
        )
        self.no_trade_text.grid(row=0, column=0, sticky="nsew")

        scrollbar = ttk.Scrollbar(
            nt_box, orient="vertical", command=self.no_trade_text.yview
        )
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.no_trade_text.config(yscrollcommand=scrollbar.set)

    def update_report_display(self, report_content: str) -> None:
        """
        Updates the report text widget with new content.

        Args:
            report_content: The new text to display in the report box.
        """
        if not self.report_text:
            return
        self.report_text.config(state="normal")
        self.report_text.delete("1.0", tk.END)
        self.report_text.insert(tk.END, report_content)
        self.report_text.config(state="disabled")
        logger.debug(f"Report display updated with content: {report_content[:100]}...")

    def update_no_trade_display(self, reasons: list[str]) -> None:
        """
        Updates the NO-TRADE text widget with a list of reasons.

        Args:
            reasons: A list of strings, each a reason for not trading.
        """
        if not self.no_trade_text:
            return
        self.no_trade_text.config(state="normal")
        self.no_trade_text.delete("1.0", tk.END)
        if reasons:
            content = "\n".join(f"- {reason}" for reason in reasons)
            self.no_trade_text.insert(tk.END, content)
        else:
            self.no_trade_text.insert(tk.END, "No NO-TRADE conditions met.")
        self.no_trade_text.config(state="disabled")
        logger.debug(f"No-trade display updated with {len(reasons)} reasons.")

    def update_trade_status(self, status: str) -> None:
        """
        Updates the trade status label.

        Args:
            status: The new status text to display.
        """
        self.trade_status_var.set(f"STATUS: {status}")
        logger.info(f"Trade status updated to: {status}")

    def update_ui_from_config(self, config: RunConfig) -> None:
        """
        Updates the UI elements to reflect the given configuration.
        This method is called when a new configuration is loaded.

        Args:
            config: The RunConfig object with the new settings.
        """
        # Placeholder for any UI updates needed when config changes
        # For example, enabling/disabling features based on config
        self.app_ui.root.update_idletasks()
        logger.info("UI updated from new configuration.")

    def set_ui_state(self, is_running: bool) -> None:
        """
        Enables or disables UI elements based on the running state.

        Args:
            is_running: True if analysis is running, False otherwise.
        """
        if self.run_button:
            self.run_button.config(state="disabled" if is_running else "normal")
        if self.stop_button:
            self.stop_button.config(state="normal" if is_running else "disabled")
        
        # Disable other tabs to prevent config changes during a run
        self.app_ui.set_tabs_state(is_running)
        logger.info(f"UI state set to is_running={is_running}.")

    def _bind_hover_events(self, widget: tk.Widget, text: str) -> None:
        """Binds mouse enter and leave events to show/hide a tooltip."""
        widget.bind("<Enter>", lambda event: self._show_tooltip(event, text))
        widget.bind("<Leave>", lambda event: self._hide_tooltip())

    def _show_tooltip(self, event: tk.Event, text: str) -> None:
        """Displays a tooltip window near the widget."""
        if self._tooltip_window:
            self._tooltip_window.destroy()

        x = event.x_root + 20
        y = event.y_root + 10

        self._tooltip_window = tk.Toplevel(self.app_ui.root)
        self._tooltip_window.wm_overrideredirect(True)
        self._tooltip_window.wm_geometry(f"+{x}+{y}")

        label = ttk.Label(
            self._tooltip_window,
            text=text,
            justify="left",
            background="#ffffe0",
            relief="solid",
            borderwidth=1,
            padding=5,
        )
        label.pack(ipadx=1)

    def _hide_tooltip(self) -> None:
        """Destroys the tooltip window."""
        if self._tooltip_window:
            self._tooltip_window.destroy()
            self._tooltip_window = None
