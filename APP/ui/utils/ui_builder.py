from __future__ import annotations

import importlib.util
import logging
import os
import subprocess
import sys
import tkinter as tk
from tkinter import ttk, messagebox
from tkinter.scrolledtext import ScrolledText
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from APP.ui.app_ui import AppUI

logger = logging.getLogger(__name__)

HAS_MPL = bool(importlib.util.find_spec("matplotlib"))

def build_ui(app: "AppUI"):
    """Hàm chính xây dựng toàn bộ giao diện người dùng."""
    logger.debug("Bắt đầu build_ui.")
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

    app.history_manager.refresh_history_list()
    app.history_manager.refresh_json_list()
    app.prompt_manager.load_prompts_from_disk()
    logger.debug("Kết thúc build_ui.")

def _build_top_frame(app: AppUI):
    top = ttk.Frame(app.root, padding=(10, 8, 10, 6))
    top.grid(row=0, column=0, sticky="ew")
    top.columnconfigure(1, weight=1)

    api_frame = ttk.Frame(top)
    api_frame.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 4))
    api_frame.columnconfigure(1, weight=1)
    ttk.Label(api_frame, text="API Key:").grid(row=0, column=0, sticky="w")
    app.api_entry = ttk.Entry(api_frame, textvariable=app.api_key_var, show="*", width=40)
    app.api_entry.grid(row=0, column=1, sticky="ew", padx=6)

    config_frame = ttk.Frame(top)
    config_frame.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 4))
    config_frame.columnconfigure(1, weight=1)
    ttk.Label(config_frame, text="Model:").grid(row=0, column=0, sticky="w")
    app.model_combo = ttk.Combobox(config_frame, textvariable=app.model_var, values=[], state="readonly", width=40)
    app.model_combo.grid(row=0, column=1, sticky="w", padx=6)
    app._update_model_list_in_ui()
    ttk.Label(config_frame, text="Thư mục ảnh:").grid(row=0, column=2, sticky="w", padx=(10, 0))
    app.folder_label = ttk.Entry(config_frame, textvariable=app.folder_path, state="readonly")
    app.folder_label.grid(row=0, column=3, sticky="ew", padx=6)
    config_frame.columnconfigure(3, weight=1)
    ttk.Button(config_frame, text="Chọn thư mục…", command=app.choose_folder).grid(row=0, column=4, sticky="w")

    action_frame = ttk.Frame(top)
    action_frame.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))
    action_frame.columnconfigure(1, weight=1)
    ws_frame = ttk.Frame(action_frame)
    ws_frame.grid(row=0, column=0, sticky="w")
    ttk.Label(ws_frame, text="Workspace:").pack(side="left", anchor="center")
    ttk.Button(ws_frame, text="Lưu", command=app._save_workspace).pack(side="left", padx=(6,0))
    ttk.Button(ws_frame, text="Khôi phục", command=app._load_workspace).pack(side="left", padx=6)

    run_frame = ttk.Frame(action_frame)
    run_frame.grid(row=0, column=2, sticky="e")
    ttk.Button(run_frame, text="► Bắt đầu", command=app.start_analysis).pack(side="left")
    app.stop_btn = ttk.Button(run_frame, text="□ Dừng", command=app.stop_analysis, state="disabled")
    app.stop_btn.pack(side="left", padx=6)

def _build_progress_frame(app: AppUI):
    prog = ttk.Frame(app.root, padding=(10, 0, 10, 6))
    prog.grid(row=1, column=0, sticky="ew")
    prog.columnconfigure(0, weight=1)
    ttk.Progressbar(prog, variable=app.progress_var, maximum=100).grid(row=0, column=0, sticky="ew")
    ttk.Label(prog, textvariable=app.status_var).grid(row=1, column=0, sticky="w", pady=(3, 0))

def _build_report_tab(app: AppUI):
    tab_report = ttk.Frame(app.nb, padding=8)
    app.nb.add(tab_report, text="Report")
    tab_report.columnconfigure(1, weight=2)
    tab_report.rowconfigure(0, weight=1)

    left_panel = ttk.Frame(tab_report)
    left_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
    left_panel.columnconfigure(0, weight=1)
    left_panel.rowconfigure(0, weight=1)
    cols = ("#", "name", "status")
    app.tree = ttk.Treeview(left_panel, columns=cols, show="headings", selectmode="browse")
    app.tree.heading("#", text="#")
    app.tree.heading("name", text="Tệp ảnh")
    app.tree.heading("status", text="Trạng thái")
    app.tree.column("#", width=40, anchor="e")
    app.tree.column("name", width=200, anchor="w")
    app.tree.column("status", width=100, anchor="w")
    app.tree.grid(row=0, column=0, sticky="nsew")
    scr_y = ttk.Scrollbar(left_panel, orient="vertical", command=app.tree.yview)
    app.tree.configure(yscrollcommand=scr_y.set)
    scr_y.grid(row=0, column=1, sticky="ns")

    detail_box = ttk.LabelFrame(tab_report, text="Chi tiết", padding=8)
    detail_box.grid(row=0, column=1, sticky="nsew")
    detail_box.rowconfigure(0, weight=1)
    detail_box.columnconfigure(0, weight=1)
    app.detail_text = ScrolledText(detail_box, wrap="word")
    app.detail_text.grid(row=0, column=0, sticky="nsew")

def _build_chart_tab(app: AppUI):
    if HAS_MPL:
        from APP.ui.components.chart_tab import ChartTab
        app.chart_tab = ChartTab(app, app.nb)
    else:
        tab_chart_placeholder = ttk.Frame(app.nb, padding=8)
        app.nb.add(tab_chart_placeholder, text="Chart")
        ttk.Label(tab_chart_placeholder, text="Chức năng Chart yêu cầu matplotlib.\nCài đặt: pip install matplotlib mplfinance").pack()

def _build_prompt_tab(app: AppUI):
    tab_prompt = ttk.Frame(app.nb, padding=8)
    app.nb.add(tab_prompt, text="Prompt")
    tab_prompt.columnconfigure(0, weight=1)
    tab_prompt.rowconfigure(1, weight=1)

    pr_actions = ttk.Frame(tab_prompt)
    pr_actions.grid(row=0, column=0, sticky="ew", pady=(0, 6))
    ttk.Button(pr_actions, text="Tải lại prompt từ file", command=app.prompt_manager.load_prompts_from_disk).pack(side="left")
    ttk.Button(pr_actions, text="Lưu prompt hiện tại", command=app.prompt_manager.save_current_prompt_to_disk).pack(side="left", padx=(6,0))
    ttk.Button(pr_actions, text="Định dạng lại", command=app.prompt_manager.reformat_prompt_area).pack(side="left", padx=(6, 0))

    app.prompt_nb = ttk.Notebook(tab_prompt)
    app.prompt_nb.grid(row=1, column=0, sticky="nsew")

    prompt_tab_no_entry = ttk.Frame(app.prompt_nb, padding=(0, 8, 0, 0))
    app.prompt_nb.add(prompt_tab_no_entry, text="Tìm Lệnh Mới (No Entry)")
    prompt_tab_no_entry.columnconfigure(0, weight=1)
    prompt_tab_no_entry.rowconfigure(0, weight=1)
    app.prompt_no_entry_text = ScrolledText(prompt_tab_no_entry, wrap="word", height=18)
    app.prompt_no_entry_text.grid(row=0, column=0, sticky="nsew")

    prompt_tab_entry_run = ttk.Frame(app.prompt_nb, padding=(0, 8, 0, 0))
    app.prompt_nb.add(prompt_tab_entry_run, text="Quản Lý Lệnh (Entry Run)")
    prompt_tab_entry_run.columnconfigure(0, weight=1)
    prompt_tab_entry_run.rowconfigure(0, weight=1)
    app.prompt_entry_run_text = ScrolledText(prompt_tab_entry_run, wrap="word", height=18)
    app.prompt_entry_run_text.grid(row=0, column=0, sticky="nsew")

def _build_options_tab(app: AppUI):
    tab_opts = ttk.Frame(app.nb, padding=8)
    app.nb.add(tab_opts, text="Options")
    # This can be filled out later with more options

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
    if sys.platform == "win32":
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])
