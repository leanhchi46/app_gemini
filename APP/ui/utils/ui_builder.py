from __future__ import annotations

import importlib.util
import logging
import tkinter as tk
from tkinter import ttk, messagebox
from tkinter.scrolledtext import ScrolledText
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from APP.ui.app_ui import AppUI

logger = logging.getLogger(__name__)

HAS_MPL = bool(importlib.util.find_spec("matplotlib"))


def build_ui(app: "AppUI"):
    """Hàm chính xây dựng toàn bộ giao diện người dùng."""
    app.root.columnconfigure(0, weight=1)
    _build_top_frame(app)
    _build_progress_frame(app)
    
    app.nb = ttk.Notebook(app.root)
    app.nb.grid(row=2, column=0, sticky="nsew", padx=8, pady=(0, 8))
    app.root.rowconfigure(2, weight=1)

    _build_report_tab(app)
    _build_chart_tab(app)
    _build_prompt_tab(app)
    _build_options_tab(app)

    # Tải dữ liệu ban đầu
    app.history_manager.refresh_history_list()
    app.history_manager.refresh_json_list()
    app.prompt_manager.load_prompts_from_disk()

def _build_top_frame(app: AppUI):
    top = ttk.Frame(app.root, padding=(10, 8, 10, 6))
    top.grid(row=0, column=0, sticky="ew")
    # ... (Full logic from original _build_top_frame)

def _build_progress_frame(app: AppUI):
    prog = ttk.Frame(app.root, padding=(10, 0, 10, 6))
    prog.grid(row=1, column=0, sticky="ew")
    prog.columnconfigure(0, weight=1)
    ttk.Progressbar(prog, variable=app.progress_var, maximum=100).grid(row=0, column=0, sticky="ew")
    ttk.Label(prog, textvariable=app.status_var).grid(row=1, column=0, sticky="w", pady=(3, 0))

def _build_report_tab(app: AppUI):
    # ... (Full logic from original _build_report_tab)
    pass

def _build_chart_tab(app: AppUI):
    if HAS_MPL:
        from APP.ui.components.chart_tab import ChartTab
        app.chart_tab = ChartTab(app, app.nb)
    else:
        tab_chart_placeholder = ttk.Frame(app.nb, padding=8)
        app.nb.add(tab_chart_placeholder, text="Chart")
        ttk.Label(tab_chart_placeholder, text="Chức năng Chart yêu cầu matplotlib.\nCài đặt: pip install matplotlib").pack()

def _build_prompt_tab(app: AppUI):
    # ... (Full logic from original _build_prompt_tab)
    pass

def _build_options_tab(app: AppUI):
    # ... (Full logic from original _build_options_tab)
    pass

# UI utility functions
def enqueue(app: AppUI, action):
    app.ui_queue.put(action)

def message(app: AppUI, level: str, title: str, message: str):
    enqueue(app, lambda: getattr(messagebox, f"show{level}")(title, message))

def detail_replace(app: AppUI, text: str):
    if hasattr(app, "detail_text"):
        enqueue(app, lambda: {
            app.detail_text.config(state="normal"),
            app.detail_text.delete("1.0", "end"),
            app.detail_text.insert("1.0", text)
        })

def open_path(path):
    import os, subprocess, sys
    if sys.platform == "win32":
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])
