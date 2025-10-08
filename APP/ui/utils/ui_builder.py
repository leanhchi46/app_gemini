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
from typing import TYPE_CHECKING, Any, Callable, Dict, List

if TYPE_CHECKING:
    from APP.ui.app_ui import AppUI

from APP.ui.components.chart_tab import ChartTab

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
    parent: tk.Widget,
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
    parent: tk.Widget,
    app: "AppUI",
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
    # Sửa lỗi nghiêm trọng: Gán widget vào đối tượng `app` chính, không phải `parent`.
    setattr(app, listbox_attr_name, listbox)

    scrollbar = ttk.Scrollbar(col_frame, orient="vertical", command=listbox.yview)
    listbox.configure(yscrollcommand=scrollbar.set)
    scrollbar.grid(row=1, column=1, sticky="ns")

    buttons_frame = ttk.Frame(col_frame)
    buttons_frame.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(6, 0))

    listbox.bind("<<ListboxSelect>>", lambda e: callbacks.get("preview", lambda: None)())
    listbox.bind("<Double-Button-1>", lambda e: callbacks.get("open", lambda: None)())

    open_cmd = callbacks.get("open")
    delete_cmd = callbacks.get("delete")
    folder_cmd = callbacks.get("folder")

    if open_cmd:
        ttk.Button(buttons_frame, text="Mở", command=open_cmd).pack(side="left")
    if delete_cmd:
        ttk.Button(buttons_frame, text="Xoá", command=delete_cmd).pack(side="left", padx=6)
    if folder_cmd:
        ttk.Button(buttons_frame, text="Thư mục", command=folder_cmd).pack(side="left")
    
    # Thêm nút làm mới thủ công để gỡ lỗi
    refresh_cmd = callbacks.get("refresh")
    if refresh_cmd:
        ttk.Button(buttons_frame, text="Làm mới", command=refresh_cmd).pack(side="right", padx=(6, 0))


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

    key_actions_frame = ttk.Frame(api_frame)
    key_actions_frame.grid(row=0, column=3, sticky="w")
    ttk.Button(key_actions_frame, text="Tải .env", command=app._load_env).pack(side="left")
    ttk.Button(key_actions_frame, text="Lưu an toàn", command=app._save_api_safe).pack(side="left", padx=6)
    ttk.Button(key_actions_frame, text="Xoá đã lưu", command=app._delete_api_safe).pack(side="left")

    # --- Row 2: Analysis Config ---
    config_frame = ttk.Frame(top)
    config_frame.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 4))
    config_frame.columnconfigure(3, weight=1)
    ttk.Label(config_frame, text="Model:").grid(row=0, column=0, sticky="w")
    app.model_combo = ttk.Combobox(config_frame, textvariable=app.model_var, state="readonly", width=40)
    app.model_combo.grid(row=0, column=1, sticky="w", padx=6)
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
    if not app.nb:
        return
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
        app.tree.column(col, width=width, anchor=anchor) # type: ignore
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

    # Cập nhật: Loại bỏ callback "preview" vì FileListView đã tự xử lý sự kiện bind.
    # Các callback khác hoạt động nhờ lớp tương thích trong HistoryManager.
    hist_callbacks = {
        "open": app.history_manager.open_history_selected,
        "delete": app.history_manager.delete_history_selected,
        "folder": app.history_manager.open_reports_folder,
        "refresh": app.history_manager.refresh_history_list, # Thêm callback làm mới
    }
    hist_frame = _create_listbox_with_controls(
        archives, app, "History (.md)", "history_list", hist_callbacks
    )
    hist_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 3))

    # Cập nhật: open_json_folder được thay thế bằng open_reports_folder.
    json_callbacks = {
        "open": app.history_manager.open_json_selected,
        "delete": app.history_manager.delete_json_selected,
        "folder": app.history_manager.open_reports_folder,
        "refresh": app.history_manager.refresh_json_list, # Thêm callback làm mới
    }
    json_frame = _create_listbox_with_controls(
        archives, app, "JSON (ctx_*.json)", "json_list", json_callbacks
    )
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
    if not app.nb:
        return
    if HAS_MPL:
        app.chart_tab = ChartTab(app, app.nb)
    else:
        placeholder = ttk.Frame(app.nb, padding=8)
        app.nb.add(placeholder, text="Chart")
        ttk.Label(placeholder, text="Chức năng Chart yêu cầu: pip install matplotlib mplfinance", foreground="#666").pack(anchor="w")


def _build_prompt_tab(app: "AppUI") -> None:
    """Xây dựng tab "Prompt"."""
    if not app.nb:
        return
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


def _build_opts_general(app: "AppUI", parent: ttk.Notebook) -> None:
    """Xây dựng tab Options -> General."""
    tab = ttk.Frame(parent, padding=8)
    parent.add(tab, text="General")
    
    # Cột trái
    left_col = ttk.Frame(tab)
    left_col.pack(side="left", fill="both", expand=True, padx=(0, 5))

    card1 = ttk.LabelFrame(left_col, text="Run & File", padding=8)
    card1.pack(fill="x", pady=(0, 8))
    _create_labeled_spinbox(card1, "Giới hạn số ảnh (0=vô hạn):", app.max_files_var, 0, 1000, width=8).pack(anchor="w", pady=(4,0))
    ttk.Checkbutton(card1, text="Chỉ gọi model nếu bộ ảnh không đổi", variable=app.only_generate_if_changed_var).pack(anchor="w", pady=4)
    _create_labeled_spinbox(card1, "Số báo cáo .md tối đa:", app.persistence_max_md_reports_var, 0, 1000, width=6).pack(anchor="w", pady=(4,0))

    card2 = ttk.LabelFrame(left_col, text="API & Upload", padding=8)
    card2.pack(fill="x")
    _create_labeled_spinbox(card2, "Số lần thử lại API:", app.api_tries_var, 1, 10, width=6).pack(anchor="w")
    _create_labeled_spinbox(card2, "Thời gian chờ API (giây):", app.api_delay_var, 0.5, 30, increment=0.5, width=6).pack(anchor="w", pady=(4,0))
    _create_labeled_spinbox(card2, "Số luồng upload song song:", app.upload_workers_var, 1, 16, width=6).pack(anchor="w", pady=(4,0))
    ttk.Checkbutton(card2, text="Bật cache ảnh (tái dùng file đã upload)", variable=app.cache_enabled_var).pack(anchor="w", pady=(4,0))
    ttk.Checkbutton(card2, text="Xoá file trên Gemini sau khi phân tích", variable=app.delete_after_var).pack(anchor="w", pady=4)

    # Cột phải
    right_col = ttk.Frame(tab)
    right_col.pack(side="left", fill="both", expand=True, padx=(5, 0))

    card3 = ttk.LabelFrame(right_col, text="Xử lý ảnh", padding=8)
    card3.pack(fill="x", pady=(0, 8))
    ttk.Checkbutton(card3, text="Tối ưu hóa ảnh (lossless)", variable=app.optimize_lossless_var).pack(anchor="w")
    _create_labeled_spinbox(card3, "Chiều rộng tối đa:", app.image_max_width_var, 200, 4096, width=8).pack(anchor="w", pady=(4,0))
    _create_labeled_spinbox(card3, "Chất lượng JPEG:", app.image_jpeg_quality_var, 10, 100, width=8).pack(anchor="w", pady=(4,0))


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

    card1 = ttk.LabelFrame(tab, text="Cài đặt chính", padding=8)
    card1.pack(fill="x", pady=(0, 8), expand=True, anchor="n")
    card1.columnconfigure(1, weight=1)

    ttk.Checkbutton(card1, text="Bật thông báo Telegram", variable=app.telegram_enabled_var).grid(row=0, column=0, columnspan=3, sticky="w")
    ttk.Label(card1, text="Bot Token:").grid(row=1, column=0, sticky="w", pady=6)
    tk.Entry(card1, textvariable=app.telegram_token_var, show="*", width=48).grid(row=1, column=1, sticky="ew", padx=6, pady=6)
    ttk.Label(card1, text="Chat ID:").grid(row=2, column=0, sticky="w", pady=6)
    tk.Entry(card1, textvariable=app.telegram_chat_id_var, width=24).grid(row=2, column=1, sticky="w", padx=6, pady=6)
    ttk.Button(card1, text="Gửi thử", command=app._telegram_test).grid(row=2, column=2, sticky="e", padx=8, pady=6)

    card2 = ttk.LabelFrame(tab, text="Cài đặt nâng cao", padding=8)
    card2.pack(fill="x", expand=True, anchor="n")
    card2.columnconfigure(1, weight=1)

    ttk.Checkbutton(card2, text="Thông báo khi phân tích dừng sớm (No-Run/No-Trade)", variable=app.telegram_notify_early_exit_var).grid(row=0, column=0, columnspan=2, sticky="w")
    ttk.Checkbutton(card2, text="Bỏ qua xác thực SSL (không khuyến khích)", variable=app.telegram_skip_verify_var).grid(row=1, column=0, columnspan=2, sticky="w", pady=4)
    
    ca_path_frame = ttk.Frame(card2)
    ca_path_frame.grid(row=2, column=0, columnspan=2, sticky="ew", pady=4)
    ca_path_frame.columnconfigure(1, weight=1)
    ttk.Label(ca_path_frame, text="Đường dẫn CA Bundle (tùy chọn):").grid(row=0, column=0, sticky="w")
    ttk.Entry(ca_path_frame, textvariable=app.telegram_ca_path_var).grid(row=0, column=1, sticky="ew", padx=6)


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


def _build_opts_conditions(app: "AppUI", parent: ttk.Notebook) -> None:
    """Xây dựng tab Options -> Conditions."""
    tab = ttk.Frame(parent, padding=8)
    parent.add(tab, text="Conditions")

    # Chia thành 2 cột
    left_col = ttk.Frame(tab)
    left_col.pack(side="left", fill="both", expand=True, padx=(0, 5), anchor="n")
    right_col = ttk.Frame(tab)
    right_col.pack(side="left", fill="both", expand=True, padx=(5, 0), anchor="n")
    
    # --- CỘT TRÁI ---
    # --- NO RUN ---
    card1 = ttk.LabelFrame(left_col, text="Điều kiện không chạy phân tích (No-Run)", padding=8)
    card1.pack(fill="x", pady=(0, 8))
    card1.columnconfigure(1, weight=1)

    ttk.Checkbutton(card1, text="Không chạy vào Thứ 7 và Chủ Nhật", variable=app.no_run_weekend_enabled_var).grid(row=0, column=0, columnspan=2, sticky="w")
    ttk.Checkbutton(card1, text="Chỉ chạy trong thời gian Kill Zone", variable=app.norun_killzone_var).grid(row=1, column=0, columnspan=2, sticky="w", pady=4)
    ttk.Checkbutton(card1, text="Không chạy vào ngày lễ", variable=app.no_run_holiday_check_var).grid(row=2, column=0, columnspan=2, sticky="w")
    
    holiday_frame = ttk.Frame(card1)
    holiday_frame.grid(row=3, column=0, columnspan=2, sticky="w", pady=(2,0), padx=(20, 0))
    ttk.Label(holiday_frame, text="Mã quốc gia cho ngày lễ:").pack(side="left")
    ttk.Entry(holiday_frame, textvariable=app.no_run_holiday_country_var, width=8).pack(side="left", padx=6)

    tz_frame = ttk.Frame(card1)
    tz_frame.grid(row=4, column=0, columnspan=2, sticky="w", pady=(6,0))
    ttk.Label(tz_frame, text="Múi giờ (Timezone):").pack(side="left")
    ttk.Entry(tz_frame, textvariable=app.no_run_timezone_var, width=25).pack(side="left", padx=6)

    # --- NEWS ---
    card3 = ttk.LabelFrame(left_col, text="Chặn giao dịch theo tin tức (News)", padding=8)
    card3.pack(fill="x")
    
    ttk.Checkbutton(card3, text="Bật chặn giao dịch khi có tin tức quan trọng", variable=app.news_block_enabled_var).pack(anchor="w")
    
    separator_news = ttk.Separator(card3, orient="horizontal")
    separator_news.pack(fill="x", pady=8, padx=2)

    _create_labeled_spinbox(card3, "Chặn trước khi tin ra (phút):", app.trade_news_block_before_min_var, 0, 120, width=8).pack(anchor="w", pady=4)
    _create_labeled_spinbox(card3, "Chặn sau khi tin ra (phút):", app.trade_news_block_after_min_var, 0, 120, width=8).pack(anchor="w", pady=4)
    _create_labeled_spinbox(card3, "Thời gian cache tin tức (giây):", app.news_cache_ttl_var, 60, 3600, width=8).pack(anchor="w", pady=4)

    # --- CỘT PHẢI ---
    # --- NO TRADE ---
    card2 = ttk.LabelFrame(right_col, text="Điều kiện không vào lệnh (No-Trade)", padding=8)
    card2.pack(fill="x", pady=(0, 8))
    
    ttk.Checkbutton(card2, text="Bật kiểm tra điều kiện No-Trade", variable=app.no_trade_enabled_var).pack(anchor="w")
    
    separator = ttk.Separator(card2, orient="horizontal")
    separator.pack(fill="x", pady=8, padx=2)

    _create_labeled_spinbox(card2, "Spread tối đa (pips):", app.nt_spread_max_pips_var, 0.1, 100.0, increment=0.1, width=8).pack(anchor="w", pady=4)
    _create_labeled_spinbox(card2, "ATR M5 tối thiểu (pips):", app.nt_min_atr_m5_pips_var, 0.0, 100.0, increment=0.1, width=8).pack(anchor="w", pady=4)
    _create_labeled_spinbox(card2, "Khoảng cách tối thiểu tới Key Level (pips):", app.trade_min_dist_keylvl_pips_var, 0.0, 100.0, increment=0.5, width=8).pack(anchor="w", pady=4)

    session_frame = ttk.LabelFrame(card2, text="Phiên giao dịch được phép", padding=6)
    session_frame.pack(fill="x", pady=8, anchor="w")
    ttk.Checkbutton(session_frame, text="Phiên Á (Asia)", variable=app.trade_allow_session_asia_var).pack(anchor="w")
    ttk.Checkbutton(session_frame, text="Phiên Âu (London)", variable=app.trade_allow_session_london_var).pack(anchor="w")
    ttk.Checkbutton(session_frame, text="Phiên Mỹ (New York)", variable=app.trade_allow_session_ny_var).pack(anchor="w")


def _build_opts_autotrade(app: "AppUI", parent: ttk.Notebook) -> None:
    """Xây dựng tab Options -> Trading -> Auto Trade."""
    tab = ttk.Frame(parent, padding=8)
    parent.add(tab, text="Auto Trade")
    
    # Chia thành 2 cột
    left_col = ttk.Frame(tab)
    left_col.pack(side="left", fill="both", expand=True, padx=(0, 5))
    right_col = ttk.Frame(tab)
    right_col.pack(side="left", fill="both", expand=True, padx=(5, 0))

    # --- Cột Trái ---
    card1 = ttk.LabelFrame(left_col, text="Kích hoạt & Chế độ", padding=8)
    card1.pack(fill="x", pady=(0, 8))
    ttk.Checkbutton(card1, text="Bật tự động giao dịch", variable=app.auto_trade_enabled_var).pack(anchor="w")
    ttk.Checkbutton(card1, text="Chế độ Dry Run (chỉ ghi log, không vào lệnh thật)", variable=app.auto_trade_dry_run_var).pack(anchor="w", pady=4)
    ttk.Checkbutton(card1, text="Tuân thủ nghiêm ngặt xu hướng (Strict Bias)", variable=app.trade_strict_bias_var).pack(anchor="w")

    card2 = ttk.LabelFrame(left_col, text="Quản lý Rủi ro", padding=8)
    card2.pack(fill="x", pady=(0, 8))
    
    size_mode_frame = ttk.Frame(card2)
    size_mode_frame.pack(anchor="w")
    ttk.Label(size_mode_frame, text="Chế độ kích thước lệnh:").pack(side="left")
    ttk.Combobox(size_mode_frame, textvariable=app.trade_size_mode_var, values=["risk_percent"], state="readonly", width=15).pack(side="left", padx=6)
    
    _create_labeled_spinbox(card2, "Rủi ro/lệnh (% tài khoản):", app.trade_equity_risk_pct_var, 0.01, 100.0, increment=0.01, width=8).pack(anchor="w", pady=4)
    _create_labeled_spinbox(card2, "Tỷ lệ chốt lời TP1 (%):", app.trade_split_tp1_pct_var, 0, 100, width=8).pack(anchor="w", pady=4)
    _create_labeled_spinbox(card2, "Tỷ lệ R:R tối thiểu cho TP2:", app.trade_min_rr_tp2_var, 0.1, 20.0, increment=0.1, width=8).pack(anchor="w", pady=4)

    # --- Cột Phải ---
    card3 = ttk.LabelFrame(right_col, text="Thông số Lệnh", padding=8)
    card3.pack(fill="x", pady=(0, 8))
    _create_labeled_spinbox(card3, "Magic Number:", app.trade_magic_var, 10000, 99999999, width=12).pack(anchor="w")
    _create_labeled_spinbox(card3, "Trượt giá (Deviation):", app.trade_deviation_points_var, 0, 1000, width=12).pack(anchor="w", pady=4)
    
    comment_frame = ttk.Frame(card3)
    comment_frame.pack(anchor="w", pady=4)
    ttk.Label(comment_frame, text="Comment lệnh:").pack(side="left")
    ttk.Entry(comment_frame, textvariable=app.trade_comment_prefix_var, width=15).pack(side="left", padx=6)

    filling_type_frame = ttk.Frame(card3)
    filling_type_frame.pack(anchor="w", pady=4)
    ttk.Label(filling_type_frame, text="Loại khớp lệnh:").pack(side="left")
    ttk.Combobox(filling_type_frame, textvariable=app.trade_filling_type_var, values=["FOK", "IOC"], state="readonly", width=12).pack(side="left", padx=6)

    card4 = ttk.LabelFrame(right_col, text="Quản lý Lệnh Nâng cao", padding=8)
    card4.pack(fill="x", pady=(0, 8))
    ttk.Checkbutton(card4, text="Dời SL về Entry sau khi TP1", variable=app.trade_move_to_be_after_tp1_var).pack(anchor="w")
    _create_labeled_spinbox(card4, "Trailing Stop (ATR multiplier, 0=tắt):", app.trade_trailing_atr_mult_var, 0.0, 10.0, increment=0.1, width=8).pack(anchor="w", pady=4)
    ttk.Checkbutton(card4, text="Lệnh chờ động (Dynamic Pending)", variable=app.trade_dynamic_pending_var).pack(anchor="w", pady=4)
    _create_labeled_spinbox(card4, "Thời gian chờ lệnh (phút):", app.trade_pending_ttl_min_var, 1, 1440, width=8).pack(anchor="w", pady=4)
    _create_labeled_spinbox(card4, "Thời gian nghỉ giữa các lệnh (phút):", app.trade_cooldown_min_var, 0, 1440, width=8).pack(anchor="w", pady=4)




def _build_opts_news(app: "AppUI", parent: ttk.Notebook) -> None:
    """Xây dựng tab Options -> Trading -> News."""
    tab = ttk.Frame(parent, padding=8)
    parent.add(tab, text="News")

    card = ttk.LabelFrame(tab, text="Chặn giao dịch theo tin tức", padding=8)
    card.pack(fill="x", expand=True, anchor="n")
    
    ttk.Checkbutton(card, text="Bật chặn giao dịch khi có tin tức quan trọng", variable=app.news_block_enabled_var).pack(anchor="w")
    
    separator = ttk.Separator(card, orient="horizontal")
    separator.pack(fill="x", pady=8, padx=2)

    _create_labeled_spinbox(card, "Chặn trước khi tin ra (phút):", app.trade_news_block_before_min_var, 0, 120, width=8).pack(anchor="w", pady=4)
    _create_labeled_spinbox(card, "Chặn sau khi tin ra (phút):", app.trade_news_block_after_min_var, 0, 120, width=8).pack(anchor="w", pady=4)
    _create_labeled_spinbox(card, "Thời gian cache tin tức (giây):", app.news_cache_ttl_var, 60, 3600, width=8).pack(anchor="w", pady=4)


def _build_options_tab(app: "AppUI") -> None:
    """Xây dựng tab "Options"."""
    if not app.nb:
        return
    tab = ttk.Frame(app.nb, padding=8)
    app.nb.add(tab, text="Options")
    tab.columnconfigure(0, weight=1)
    tab.rowconfigure(0, weight=1)

    opts_nb = ttk.Notebook(tab)
    opts_nb.grid(row=0, column=0, sticky="nsew")

    # Xây dựng các tab theo cấu trúc logic mới
    _build_opts_general(app, opts_nb)
    _build_opts_context(app, opts_nb)
    _build_opts_conditions(app, opts_nb) # Gộp No-Run, No-Trade, News
    _build_opts_autotrade(app, opts_nb)
    
    # Tab Services (chứa các tab con)
    services_tab = ttk.Frame(opts_nb, padding=8)
    opts_nb.add(services_tab, text="Services")
    services_nb = ttk.Notebook(services_tab)
    services_nb.pack(fill="both", expand=True)
    _build_opts_mt5(app, services_nb)
    _build_opts_telegram(app, services_nb)


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


# =====================================================================================
# UI HELPERS (Safe UI updates and dialogs)
# =====================================================================================

def poll_ui_queue(app: "AppUI") -> None:
    """Lấy và thực thi các hàm cập nhật UI từ hàng đợi một cách an toàn."""
    try:
        while True:
            callback = app.ui_queue.get_nowait()
            callback()
    except Exception:
        pass
    app.root.after(100, lambda: poll_ui_queue(app))


def enqueue(app: "AppUI", callback: Callable[[], Any]) -> None:
    """Thêm một hàm callback vào hàng đợi UI."""
    app.ui_queue.put(callback)


def show_message(
    title: str, message: str, parent: tk.Tk | tk.Widget | None = None
) -> None:
    """Hiển thị một hộp thoại thông báo thông tin."""
    from tkinter import messagebox
    messagebox.showinfo(title, message, parent=parent) # type: ignore


def ask_confirmation(title: str, message: str) -> bool:
    """Hiển thị hộp thoại xác nhận và trả về lựa chọn của người dùng."""
    from tkinter import messagebox
    return messagebox.askyesno(title, message)


def toggle_controls_state(app: "AppUI", state: str) -> None:
    """Bật hoặc tắt các điều khiển chính trên giao diện."""
    if app.stop_btn:
        app.stop_btn.config(state="normal" if state == "disabled" else "disabled")
    
    # Duyệt qua tất cả các widget con của root và thay đổi trạng thái
    # trừ các widget không nên bị vô hiệu hóa (như nút Stop)
    widgets_to_disable: List[tk.Widget] = []
    
    # Hàm đệ quy để thu thập widget
    def collect_widgets(parent: tk.Misc):
        for widget in parent.winfo_children():
            # Không vô hiệu hóa nút Stop hoặc thanh cuộn, v.v.
            if widget != app.stop_btn and isinstance(widget, (ttk.Button, ttk.Checkbutton, ttk.Entry, ttk.Combobox, ttk.Spinbox, tk.Text, tk.Listbox)):
                 widgets_to_disable.append(widget)
            # Đệ quy vào các container
            if isinstance(widget, (ttk.Frame, ttk.LabelFrame, ttk.Notebook)):
                collect_widgets(widget)

    collect_widgets(app.root)
    
    for widget in widgets_to_disable:
        try:
            widget.config(state=state) # type: ignore
        except tk.TclError:
            # Một số widget không có thuộc tính 'state'
            pass


def show_json_popup(parent: tk.Tk | tk.Widget, title: str, data: dict) -> None:
    """Hiển thị một cửa sổ popup với nội dung JSON được định dạng."""
    import json
    popup = tk.Toplevel(parent)
    popup.title(title)
    popup.geometry("600x500")
    text = ScrolledText(popup, wrap="word")
    text.pack(expand=True, fill="both")
    formatted_json = json.dumps(data, indent=2, ensure_ascii=False)
    text.insert("1.0", formatted_json)
    text.config(state="disabled")
