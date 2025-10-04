# -*- coding: utf-8 -*-
"""
Module này chịu trách nhiệm xây dựng toàn bộ giao diện người dùng (GUI) cho ứng dụng
sử dụng thư viện tkinter.

Cấu trúc được chia thành các hàm con để tăng tính module hóa và dễ bảo trì.
Hàm chính `build_ui` sẽ điều phối việc gọi các hàm xây dựng từng phần.
"""
from __future__ import annotations

import importlib.util
import logging
import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Tuple

if TYPE_CHECKING:
    from APP.ui.app_ui import AppUI

from APP.ui.components.chart_tab import ChartTabTV

logger = logging.getLogger(__name__)

# Lazy import check for matplotlib
HAS_MPL = bool(importlib.util.find_spec("matplotlib"))
if HAS_MPL:
    logger.debug("Matplotlib có sẵn.")
else:
    logger.warning("Không thể import matplotlib. Tab Chart sẽ bị vô hiệu hóa.")

# =====================================================================================
# WIDGET FACTORY (Helpers to create common widgets)
# =====================================================================================


def _create_labeled_spinbox(
    parent: ttk.Frame,
    label_text: str,
    textvariable: tk.Variable,
    from_: float,
    to: float,
    **kwargs: Any,
) -> ttk.Frame:
    """Tạo một cặp Label và Spinbox bên trong một Frame mới và trả về Frame đó."""
    frame = ttk.Frame(parent)
    label = ttk.Label(frame, text=label_text)
    label.pack(side="left", padx=(0, 4))
    spinbox = ttk.Spinbox(frame, from_=from_, to=to, textvariable=textvariable, **kwargs)
    spinbox.pack(side="left")
    return frame


def _create_listbox_with_controls(
    parent: ttk.Frame,
    title: str,
    listbox_attr_name: str,
    callbacks: Dict[str, Callable[[], None]],
) -> ttk.Frame:
    """Tạo một cột chứa Listbox và các nút điều khiển, trả về Frame chứa chúng."""
    col_frame = ttk.Frame(parent)
    col_frame.columnconfigure(0, weight=1)
    col_frame.rowconfigure(1, weight=1)

    ttk.Label(col_frame, text=title).grid(row=0, column=0, sticky="w")

    listbox = tk.Listbox(col_frame, exportselection=False)
    listbox.grid(row=1, column=0, sticky="nsew")
    setattr(parent, listbox_attr_name, listbox)

    scrollbar = ttk.Scrollbar(col_frame, orient="vertical", command=listbox.yview)
    listbox.configure(yscrollcommand=scrollbar.set)
    scrollbar.grid(row=1, column=1, sticky="ns")

    buttons_frame = ttk.Frame(col_frame)
    buttons_frame.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(6, 0))

    listbox.bind("<<ListboxSelect>>", lambda e: callbacks.get("preview", lambda: None)())
    listbox.bind("<Double-Button-1>", lambda e: callbacks.get("open", lambda: None)())

    ttk.Button(buttons_frame, text="Mở", command=callbacks.get("open")).pack(side="left")
    ttk.Button(buttons_frame, text="Xoá", command=callbacks.get("delete")).pack(side="left", padx=6)
    ttk.Button(buttons_frame, text="Thư mục", command=callbacks.get("folder")).pack(side="left", padx=6)

    return col_frame


# =====================================================================================
# UI BUILDER FUNCTIONS
# =====================================================================================


def _build_top_frame(app: "AppUI") -> None:
    """Xây dựng khu vực điều khiển trên cùng của giao diện người dùng."""
    top = ttk.Frame(app.root, padding=(10, 8, 10, 6))
    top.grid(row=0, column=0, sticky="ew")
    top.columnconfigure(1, weight=1)

    # --- Row 1: API Key ---
    api_frame = ttk.Frame(top)
    api_frame.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 4))
    api_frame.columnconfigure(1, weight=1)
    ttk.Label(api_frame, text="API Key:").grid(row=0, column=0, sticky="w")
    app.api_entry = ttk.Entry(api_frame, textvariable=app.api_key_var, show="*", width=40)
    app.api_entry.grid(row=0, column=1, sticky="ew", padx=6)
    ttk.Checkbutton(api_frame, text="Hiện", command=app._toggle_api_visibility).grid(row=0, column=2, sticky="w", padx=(0, 10))
    ttk.Button(api_frame, text="Tải .env", command=app._load_env).grid(row=0, column=3, sticky="w")
    ttk.Button(api_frame, text="Lưu an toàn", command=app._save_api_safe).grid(row=0, column=4, sticky="w", padx=6)
    ttk.Button(api_frame, text="Xoá đã lưu", command=app._delete_api_safe).grid(row=0, column=5, sticky="w")

    # --- Row 2: Analysis Config ---
    config_frame = ttk.Frame(top)
    config_frame.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 4))
    config_frame.columnconfigure(3, weight=1)
    ttk.Label(config_frame, text="Model:").grid(row=0, column=0, sticky="w")
    app.model_combo = ttk.Combobox(config_frame, textvariable=app.model_var, state="readonly", width=40)
    app.model_combo.grid(row=0, column=1, sticky="w", padx=6)
    app._update_model_list_in_ui()
    ttk.Label(config_frame, text="Thư mục ảnh:").grid(row=0, column=2, sticky="w", padx=(10, 0))
    app.folder_label = ttk.Entry(config_frame, textvariable=app.folder_path, state="readonly")
    app.folder_label.grid(row=0, column=3, sticky="ew", padx=6)
    ttk.Button(config_frame, text="Chọn thư mục…", command=app.choose_folder).grid(row=0, column=4, sticky="w")

    # --- Row 3: Actions & Workspace ---
    action_frame = ttk.Frame(top)
    action_frame.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))
    action_frame.columnconfigure(1, weight=1)
    ws_frame = ttk.Frame(action_frame)
    ws_frame.grid(row=0, column=0, sticky="w")
    ttk.Label(ws_frame, text="Workspace:").pack(side="left", anchor="center")
    ttk.Button(ws_frame, text="Lưu", command=app._save_workspace).pack(side="left", padx=(6, 0))
    ttk.Button(ws_frame, text="Khôi phục", command=app._load_workspace).pack(side="left", padx=6)
    ttk.Button(ws_frame, text="Xoá", command=app._delete_workspace).pack(side="left")

    run_frame = ttk.Frame(action_frame)
    run_frame.grid(row=0, column=2, sticky="e")
    ttk.Button(run_frame, text="► Bắt đầu", command=app.start_analysis).pack(side="left")
    app.stop_btn = ttk.Button(run_frame, text="□ Dừng", command=app.stop_analysis, state="disabled")
    app.stop_btn.pack(side="left", padx=6)
    ttk.Separator(run_frame, orient="vertical").pack(side="left", fill="y", padx=4, pady=2)
    ttk.Checkbutton(run_frame, text="Tự động chạy", variable=app.autorun_var, command=app._toggle_autorun).pack(side="left")
    spin = ttk.Spinbox(run_frame, from_=5, to=86400, textvariable=app.autorun_seconds_var, width=7, command=app._autorun_interval_changed)
    spin.pack(side="left", padx=(4, 0))
    spin.bind("<FocusOut>", lambda e: app._autorun_interval_changed())
    app.autorun_interval_spin = spin
    ttk.Label(run_frame, text="giây").pack(side="left", padx=(2, 0))


def _build_progress_frame(app: "AppUI") -> None:
    """Xây dựng khu vực hiển thị thanh tiến trình và trạng thái."""
    prog = ttk.Frame(app.root, padding=(10, 0, 10, 6))
    prog.grid(row=1, column=0, sticky="ew")
    prog.columnconfigure(0, weight=1)
    ttk.Progressbar(prog, variable=app.progress_var, maximum=100).grid(row=0, column=0, sticky="ew")
    ttk.Label(prog, textvariable=app.status_var).grid(row=1, column=0, sticky="w", pady=(3, 0))


def _build_report_tab(app: "AppUI") -> None:
    """Xây dựng tab "Report"."""
    tab = ttk.Frame(app.nb, padding=8)
    app.nb.add(tab, text="Report")
    tab.columnconfigure(0, weight=1)
    tab.columnconfigure(1, weight=2)
    tab.rowconfigure(0, weight=1)

    # Left Panel
    left_panel = ttk.Frame(tab)
    left_panel.grid(row=0, column=0, sticky="nsew")
    left_panel.columnconfigure(0, weight=1)
    left_panel.rowconfigure(0, weight=1)
    left_panel.rowconfigure(1, weight=1)

    cols = ("#", "name", "status")
    app.tree = ttk.Treeview(left_panel, columns=cols, show="headings", selectmode="browse")
    for col, text, width, anchor in [("#", "#", 56, "e"), ("name", "Tệp ảnh", 320, "w"), ("status", "Trạng thái", 180, "w")]:
        app.tree.heading(col, text=text)
        app.tree.column(col, width=width, anchor=anchor)
    app.tree.grid(row=0, column=0, sticky="nsew")
    scr_y = ttk.Scrollbar(left_panel, orient="vertical", command=app.tree.yview)
    app.tree.configure(yscrollcommand=scr_y.set)
    scr_y.grid(row=0, column=0, sticky="nse")
    app.tree.bind("<<TreeviewSelect>>", app._on_tree_select)

    archives = ttk.LabelFrame(left_panel, text="History & JSON", padding=6)
    archives.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
    archives.columnconfigure(0, weight=1)
    archives.columnconfigure(1, weight=1)
    archives.rowconfigure(0, weight=1)

    hist_frame = _create_listbox_with_controls(archives, "History (.md)", "history_list", {"preview": app._preview_history_selected, "open": app._open_history_selected, "delete": app._delete_history_selected, "folder": app._open_reports_folder})
    hist_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 3))

    json_frame = _create_listbox_with_controls(archives, "JSON (ctx_*.json)", "json_list", {"preview": app._preview_json_selected, "open": app._load_json_selected, "delete": app._delete_json_selected, "folder": app._open_json_folder})
    json_frame.grid(row=0, column=1, sticky="nsew", padx=(3, 0))

    # Right Panel
    right_panel = ttk.Frame(tab)
    right_panel.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
    right_panel.rowconfigure(0, weight=1)
    right_panel.columnconfigure(0, weight=1)
    detail_box = ttk.LabelFrame(right_panel, text="Chi tiết (Báo cáo Tổng hợp)", padding=8)
    detail_box.grid(row=0, column=0, sticky="nsew")
    detail_box.rowconfigure(0, weight=1)
    detail_box.columnconfigure(0, weight=1)
    app.detail_text = ScrolledText(detail_box, wrap="word")
    app.detail_text.grid(row=0, column=0, sticky="nsew")
    app.detail_text.insert("1.0", "Báo cáo tổng hợp sẽ hiển thị tại đây.")


def _build_chart_tab(app: "AppUI") -> None:
    """Xây dựng tab "Chart"."""
    if HAS_MPL:
        app.chart_tab_tv = ChartTabTV(app, app.nb)
    else:
        placeholder = ttk.Frame(app.nb, padding=8)
        app.nb.add(placeholder, text="Chart")
        ttk.Label(placeholder, text="Chức năng Chart yêu cầu: pip install matplotlib mplfinance", foreground="#666").pack(anchor="w")


def _build_prompt_tab(app: "AppUI") -> None:
    """Xây dựng tab "Prompt"."""
    tab = ttk.Frame(app.nb, padding=8)
    app.nb.add(tab, text="Prompt")
    tab.columnconfigure(0, weight=1)
    tab.rowconfigure(1, weight=1)

    actions = ttk.Frame(tab)
    actions.grid(row=0, column=0, sticky="ew", pady=(0, 6))
    ttk.Button(actions, text="Tải lại", command=app.prompt_manager.load_prompts_from_disk).pack(side="left")
    ttk.Button(actions, text="Lưu", command=app.prompt_manager.save_current_prompt_to_disk).pack(side="left", padx=6)

    prompt_nb = ttk.Notebook(tab)
    prompt_nb.grid(row=1, column=0, sticky="nsew")
    app.prompt_nb = prompt_nb

    for key, text in [("no_entry", "Tìm Lệnh Mới (No Entry)"), ("entry_run", "Quản Lý Lệnh (Entry Run)")]:
        prompt_frame = ttk.Frame(prompt_nb, padding=(0, 8, 0, 0))
        prompt_nb.add(prompt_frame, text=text)
        prompt_frame.columnconfigure(0, weight=1)
        prompt_frame.rowconfigure(0, weight=1)
        text_widget = ScrolledText(prompt_frame, wrap="word", height=18)
        text_widget.grid(row=0, column=0, sticky="nsew")
        setattr(app, f"prompt_{key}_text", text_widget)


def _build_opts_run(app: "AppUI", parent: ttk.Notebook) -> None:
    """Xây dựng tab Options -> Run."""
    tab = ttk.Frame(parent, padding=8)
    parent.add(tab, text="Run")
    card1 = ttk.LabelFrame(tab, text="Upload & Giới hạn", padding=8)
    card1.pack(fill="x", pady=(0, 8))
    ttk.Checkbutton(card1, text="Xoá file trên Gemini sau khi phân tích", variable=app.delete_after_var).pack(anchor="w")
    _create_labeled_spinbox(card1, "Giới hạn số ảnh (0=vô hạn):", app.max_files_var, 0, 1000, width=8).pack(anchor="w", pady=(4,0))
    card2 = ttk.LabelFrame(tab, text="Tăng tốc & Cache", padding=8)
    card2.pack(fill="x")
    _create_labeled_spinbox(card2, "Số luồng upload song song:", app.upload_workers_var, 1, 16, width=6).pack(anchor="w")
    ttk.Checkbutton(card2, text="Bật cache ảnh (tái dùng file đã upload)", variable=app.cache_enabled_var).pack(anchor="w", pady=(4,0))
    ttk.Checkbutton(card2, text="Chỉ gọi model nếu bộ ảnh không đổi", variable=app.only_generate_if_changed_var).pack(anchor="w")


def _build_opts_context(app: "AppUI", parent: ttk.Notebook) -> None:
    """Xây dựng tab Options -> Context."""
    tab = ttk.Frame(parent, padding=8)
    parent.add(tab, text="Context")
    card1 = ttk.LabelFrame(tab, text="Ngữ cảnh từ lịch sử (Text Reports)", padding=8)
    card1.pack(fill="x", pady=(0, 8))
    ttk.Checkbutton(card1, text="Dùng ngữ cảnh từ báo cáo trước (text)", variable=app.remember_context_var).pack(anchor="w")
    _create_labeled_spinbox(card1, "Số báo cáo gần nhất:", app.context_n_reports_var, 1, 10, width=6).pack(anchor="w", pady=(4,0))
    _create_labeled_spinbox(card1, "Giới hạn ký tự/report:", app.context_limit_chars_var, 500, 8000, increment=250, width=8).pack(anchor="w", pady=(4,0))
    card2 = ttk.LabelFrame(tab, text="Ngữ cảnh tóm tắt JSON", padding=8)
    card2.pack(fill="x")
    ttk.Checkbutton(card2, text="Tự tạo tóm tắt JSON sau mỗi lần phân tích", variable=app.create_ctx_json_var).pack(anchor="w")
    ttk.Checkbutton(card2, text="Ưu tiên dùng tóm tắt JSON làm bối cảnh", variable=app.prefer_ctx_json_var).pack(anchor="w", pady=(4,0))
    _create_labeled_spinbox(card2, "Số JSON gần nhất:", app.ctx_json_n_var, 1, 20, width=6).pack(anchor="w", pady=(4,0))


def _build_opts_telegram(app: "AppUI", parent: ttk.Notebook) -> None:
    """Xây dựng tab Options -> Telegram."""
    tab = ttk.Frame(parent, padding=8)
    parent.add(tab, text="Telegram")
    tab.columnconfigure(1, weight=1)
    ttk.Checkbutton(tab, text="Bật thông báo khi có setup xác suất cao", variable=app.telegram_enabled_var).grid(row=0, column=0, columnspan=3, sticky="w")
    ttk.Label(tab, text="Bot Token:").grid(row=1, column=0, sticky="w", pady=6)
    tk.Entry(tab, textvariable=app.telegram_token_var, show="*", width=48).grid(row=1, column=1, sticky="ew", padx=6, pady=6)
    ttk.Label(tab, text="Chat ID:").grid(row=2, column=0, sticky="w", pady=6)
    tk.Entry(tab, textvariable=app.telegram_chat_id_var, width=24).grid(row=2, column=1, sticky="w", padx=6, pady=6)
    ttk.Button(tab, text="Gửi thử", command=app._telegram_test).grid(row=2, column=2, sticky="e", padx=8, pady=6)


def _build_opts_mt5(app: "AppUI", parent: ttk.Notebook) -> None:
    """Xây dựng tab Options -> MT5."""
    tab = ttk.Frame(parent, padding=8)
    parent.add(tab, text="MT5")
    tab.columnconfigure(1, weight=1)
    ttk.Checkbutton(tab, text="Bật lấy dữ liệu nến từ MT5", variable=app.mt5_enabled_var).grid(row=0, column=0, columnspan=3, sticky="w")
    ttk.Label(tab, text="MT5 terminal (tùy chọn):").grid(row=1, column=0, sticky="w", pady=6)
    tk.Entry(tab, textvariable=app.mt5_term_path_var).grid(row=1, column=1, sticky="ew", padx=6, pady=6)
    ttk.Button(tab, text="Chọn…", command=app._pick_mt5_terminal).grid(row=1, column=2, sticky="e", padx=8, pady=6)
    ttk.Label(tab, text="Symbol:").grid(row=2, column=0, sticky="w", pady=6)
    tk.Entry(tab, textvariable=app.mt5_symbol_var, width=18).grid(row=2, column=1, sticky="w", padx=6, pady=6)
    ttk.Button(tab, text="Tự nhận từ tên ảnh", command=app._mt5_guess_symbol).grid(row=2, column=2, sticky="e", padx=8, pady=6)
    
    candles_frame = ttk.Frame(tab)
    candles_frame.grid(row=3, column=0, columnspan=3, sticky="w", pady=6)
    ttk.Label(candles_frame, text="Số nến:").pack(side="left")
    for tf, var in [("M1", app.mt5_n_M1), ("M5", app.mt5_n_M5), ("M15", app.mt5_n_M15), ("H1", app.mt5_n_H1)]:
        _create_labeled_spinbox(candles_frame, tf, var, 20, 2000, width=6).pack(side="left", padx=(5,0))

    btns_mt5 = ttk.Frame(tab)
    btns_mt5.grid(row=4, column=0, columnspan=3, sticky="ew", pady=6)
    btns_mt5.columnconfigure(0, weight=1)
    btns_mt5.columnconfigure(1, weight=1)
    ttk.Button(btns_mt5, text="Kết nối/kiểm tra MT5", command=app._mt5_connect).grid(row=0, column=0, sticky="ew")
    ttk.Button(btns_mt5, text="Chụp snapshot ngay", command=app._mt5_snapshot_popup).grid(row=0, column=1, sticky="ew", padx=6)
    ttk.Label(tab, textvariable=app.mt5_status_var, foreground="#555").grid(row=5, column=0, columnspan=3, sticky="w", pady=6)


def _build_opts_norun(app: "AppUI", parent: ttk.Notebook) -> None:
    """Xây dựng tab Options -> No Run."""
    tab = ttk.Frame(parent, padding=8)
    parent.add(tab, text="No Run")
    card = ttk.LabelFrame(tab, text="Điều kiện không chạy phân tích tự động", padding=8)
    card.pack(fill="x")
    ttk.Checkbutton(card, text="Không chạy vào Thứ 7 và Chủ Nhật", variable=app.no_run_weekend_enabled_var).pack(anchor="w")
    ttk.Checkbutton(card, text="Chỉ chạy trong thời gian Kill Zone", variable=app.norun_killzone_var).pack(anchor="w", pady=4)


def _build_options_tab(app: "AppUI") -> None:
    """Xây dựng tab "Options"."""
    tab = ttk.Frame(app.nb, padding=8)
    app.nb.add(tab, text="Options")
    tab.columnconfigure(0, weight=1)
    tab.rowconfigure(0, weight=1)

    opts_nb = ttk.Notebook(tab)
    opts_nb.grid(row=0, column=0, sticky="nsew")

    _build_opts_run(app, opts_nb)
    _build_opts_context(app, opts_nb)
    _build_opts_telegram(app, opts_nb)
    _build_opts_mt5(app, opts_nb)
    _build_opts_norun(app, opts_nb)


def build_ui(app: "AppUI") -> None:
    """Hàm chính để xây dựng toàn bộ giao diện người dùng."""
    logger.debug("Bắt đầu build_ui.")
    app.root.columnconfigure(0, weight=1)
    app.root.rowconfigure(2, weight=1)

    _build_top_frame(app)
    _build_progress_frame(app)

    notebook = ttk.Notebook(app.root)
    notebook.grid(row=2, column=0, sticky="nsew", padx=8, pady=(0, 8))
    app.nb = notebook

    _build_report_tab(app)
    _build_chart_tab(app)
    _build_prompt_tab(app)
    _build_options_tab(app)

    logger.debug("Kết thúc build_ui.")
