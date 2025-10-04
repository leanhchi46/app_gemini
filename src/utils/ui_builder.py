"""
Module này chịu trách nhiệm xây dựng toàn bộ giao diện người dùng (GUI) cho ứng dụng
sử dụng thư viện tkinter.

Cấu trúc được chia thành các hàm con để tăng tính module hóa và dễ bảo trì.
Hàm chính `build_ui` sẽ điều phối việc gọi các hàm xây dựng từng phần.
"""
import importlib.util
import logging
import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText
from typing import Any  # Thêm import Any

from src.core.chart_tab import ChartTabTV

logger = logging.getLogger(__name__)

# Kiểm tra xem thư viện matplotlib có tồn tại không để quyết định hiển thị tab Chart.
# Đây là một dạng "lazy import" hoặc kiểm tra phụ thuộc (dependency check) lúc runtime.
if importlib.util.find_spec("matplotlib"):
    HAS_MPL = True
    logger.debug("Matplotlib có sẵn.")
else:
    HAS_MPL = False
    logger.warning("Không thể import matplotlib. Tab Chart sẽ bị vô hiệu hóa.")

# =====================================================================================
# HÀM XÂY DỰNG CÁC THÀNH PHẦN UI
# =====================================================================================

def _build_top_frame(app: Any):
    """
    Xây dựng khu vực điều khiển trên cùng của giao diện người dùng.

    Args:
        app: Đối tượng ứng dụng chính chứa các biến và phương thức cần thiết.
    """
    logger.debug("Bắt đầu _build_top_frame.")
    top = ttk.Frame(app.root, padding=(10, 8, 10, 6))
    top.grid(row=0, column=0, sticky="ew")
    top.columnconfigure(1, weight=1) # Cột chứa Entry/Combobox sẽ co giãn

    # --- Dòng 1: Quản lý API Key ---
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
    logger.debug("Đã xây dựng API Key frame.")

    # --- Dòng 2: Cấu hình Phân tích (Model & Thư mục) ---
    config_frame = ttk.Frame(top)
    config_frame.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 4))
    config_frame.columnconfigure(1, weight=1)

    ttk.Label(config_frame, text="Model:").grid(row=0, column=0, sticky="w")
    app.model_combo = ttk.Combobox(
        config_frame,
        textvariable=app.model_var,
        values=[], # Khởi tạo rỗng, sẽ được điền sau
        state="readonly",
        width=40,
    )
    app.model_combo.grid(row=0, column=1, sticky="w", padx=6)
    
    # Gọi hàm để cập nhật danh sách mô hình sau khi combobox được tạo
    app._update_model_list_in_ui()
    logger.debug("Đã xây dựng Model Combobox và cập nhật danh sách model.")

    ttk.Label(config_frame, text="Thư mục ảnh:").grid(row=0, column=2, sticky="w", padx=(10, 0))
    app.folder_label = ttk.Entry(config_frame, textvariable=app.folder_path, state="readonly")
    app.folder_label.grid(row=0, column=3, sticky="ew", padx=6)
    config_frame.columnconfigure(3, weight=1) # Cột thư mục ảnh co giãn
    ttk.Button(config_frame, text="Chọn thư mục…", command=app.choose_folder).grid(row=0, column=4, sticky="w")
    logger.debug("Đã xây dựng Folder Path Entry và nút chọn thư mục.")

    # --- Dòng 3: Hành động & Workspace ---
    action_frame = ttk.Frame(top)
    action_frame.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))
    action_frame.columnconfigure(1, weight=1) # Tạo khoảng trống ở giữa

    # Cụm Workspace bên trái
    ws_frame = ttk.Frame(action_frame)
    ws_frame.grid(row=0, column=0, sticky="w")
    ttk.Label(ws_frame, text="Workspace:").pack(side="left", anchor="center")
    ttk.Button(ws_frame, text="Lưu", command=app._save_workspace).pack(side="left", padx=(6,0))
    ttk.Button(ws_frame, text="Khôi phục", command=app._load_workspace).pack(side="left", padx=6)
    ttk.Button(ws_frame, text="Xoá", command=app._delete_workspace).pack(side="left")
    logger.debug("Đã xây dựng Workspace buttons.")

    # Cụm Chạy & Tự động chạy bên phải
    run_frame = ttk.Frame(action_frame)
    run_frame.grid(row=0, column=2, sticky="e")
    ttk.Button(run_frame, text="► Bắt đầu", command=app.start_analysis).pack(side="left")
    app.stop_btn = ttk.Button(run_frame, text="□ Dừng", command=app.stop_analysis, state="disabled")
    app.stop_btn.pack(side="left", padx=6)

    ttk.Separator(run_frame, orient='vertical').pack(side='left', fill='y', padx=4, pady=2)

    ttk.Checkbutton(run_frame, text="Tự động chạy", variable=app.autorun_var, command=app._toggle_autorun).pack(side="left")
    app.autorun_interval_spin = ttk.Spinbox(
        run_frame, from_=5, to=86400, textvariable=app.autorun_seconds_var, width=7,
        command=app._autorun_interval_changed
    )
    app.autorun_interval_spin.pack(side="left", padx=(4, 0))
    app.autorun_interval_spin.bind("<FocusOut>", lambda e: app._autorun_interval_changed())
    ttk.Label(run_frame, text="giây").pack(side="left", padx=(2,0))
    logger.debug("Đã xây dựng Run/Autorun controls.")
    logger.debug("Kết thúc _build_top_frame.")


def _build_progress_frame(app: Any):
    """
    Xây dựng khu vực hiển thị thanh tiến trình và trạng thái của ứng dụng.

    Args:
        app: Đối tượng ứng dụng chính chứa các biến và phương thức cần thiết.
    """
    logger.debug("Bắt đầu _build_progress_frame.")
    prog = ttk.Frame(app.root, padding=(10, 0, 10, 6))
    prog.grid(row=1, column=0, sticky="ew")
    prog.columnconfigure(0, weight=1)
    ttk.Progressbar(prog, variable=app.progress_var, maximum=100).grid(row=0, column=0, sticky="ew")
    ttk.Label(prog, textvariable=app.status_var).grid(row=1, column=0, sticky="w", pady=(3, 0))
    logger.debug("Đã xây dựng Progress frame.")
    logger.debug("Kết thúc _build_progress_frame.")

def _build_report_tab(app: Any):
    """
    Xây dựng tab "Report" chứa kết quả phân tích và các công cụ quản lý báo cáo.

    Args:
        app: Đối tượng ứng dụng chính chứa các biến và phương thức cần thiết.
    """
    logger.debug("Bắt đầu _build_report_tab.")
    tab_report = ttk.Frame(app.nb, padding=8)
    app.nb.add(tab_report, text="Report")
    logger.debug("Đã thêm tab 'Report' vào Notebook.")

    # Chia tab thành 2 cột: panel trái (danh sách) và panel phải (chi tiết)
    tab_report.columnconfigure(0, weight=1)
    tab_report.columnconfigure(1, weight=2) # Cột chi tiết rộng hơn
    tab_report.rowconfigure(0, weight=1)

    # --- Panel Trái ---
    left_panel = ttk.Frame(tab_report)
    left_panel.grid(row=0, column=0, sticky="nsew")
    left_panel.columnconfigure(0, weight=1)
    left_panel.rowconfigure(0, weight=1) # Treeview co giãn
    left_panel.rowconfigure(1, weight=1) # Khu vực History/JSON co giãn

    # Bảng danh sách ảnh và trạng thái
    cols = ("#", "name", "status")
    app.tree = ttk.Treeview(left_panel, columns=cols, show="headings", selectmode="browse")
    app.tree.heading("#", text="#")
    app.tree.heading("name", text="Tệp ảnh")
    app.tree.heading("status", text="Trạng thái")
    app.tree.column("#", width=56, anchor="e")
    app.tree.column("name", width=320, anchor="w")
    app.tree.column("status", width=180, anchor="w")
    app.tree.grid(row=0, column=0, sticky="nsew")
    scr_y = ttk.Scrollbar(left_panel, orient="vertical", command=app.tree.yview)
    app.tree.configure(yscrollcommand=scr_y.set)
    scr_y.grid(row=0, column=0, sticky="nse")
    # Binding sự kiện chọn một dòng trong Treeview sẽ gọi hàm _on_tree_select
    app.tree.bind("<<TreeviewSelect>>", app._on_tree_select)
    logger.debug("Đã xây dựng Treeview cho danh sách ảnh.")

    # Khu vực chứa History và JSON
    archives = ttk.LabelFrame(left_panel, text="History & JSON", padding=6)
    archives.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
    archives.columnconfigure(0, weight=1)
    archives.columnconfigure(1, weight=1)
    archives.rowconfigure(1, weight=1)

    # Cột History (.md)
    hist_col = ttk.Frame(archives)
    hist_col.grid(row=0, column=0, rowspan=2, sticky="nsew", padx=(0, 6))
    hist_col.columnconfigure(0, weight=1)
    hist_col.rowconfigure(1, weight=1)
    ttk.Label(hist_col, text="History (.md)").grid(row=0, column=0, sticky="w")
    app.history_list = tk.Listbox(hist_col, exportselection=False)
    app.history_list.grid(row=1, column=0, sticky="nsew")
    hist_scr = ttk.Scrollbar(hist_col, orient="vertical", command=app.history_list.yview)
    app.history_list.configure(yscrollcommand=hist_scr.set)
    hist_scr.grid(row=1, column=1, sticky="ns")
    hist_btns = ttk.Frame(hist_col)
    hist_btns.grid(row=2, column=0, sticky="ew", pady=(6,0))
    ttk.Button(hist_btns, text="Mở", command=app._open_history_selected).pack(side="left")
    ttk.Button(hist_btns, text="Xoá", command=app._delete_history_selected).pack(side="left", padx=(6,0))
    ttk.Button(hist_btns, text="Thư mục", command=app._open_reports_folder).pack(side="left", padx=(6,0))
    app.history_list.bind("<<ListboxSelect>>", lambda e: app._preview_history_selected())
    app.history_list.bind("<Double-Button-1>", lambda e: app._open_history_selected())
    logger.debug("Đã xây dựng History panel.")

    # Cột JSON (context)
    json_col = ttk.Frame(archives)
    json_col.grid(row=0, column=1, rowspan=2, sticky="nsew", padx=(6, 0))
    json_col.columnconfigure(0, weight=1)
    json_col.rowconfigure(1, weight=1)
    ttk.Label(json_col, text="JSON (ctx_*.json)").grid(row=0, column=0, sticky="w")
    app.json_list = tk.Listbox(json_col, exportselection=False)
    app.json_list.grid(row=1, column=0, sticky="nsew")
    json_scr = ttk.Scrollbar(json_col, orient="vertical", command=app.json_list.yview)
    app.json_list.configure(yscrollcommand=json_scr.set)
    json_scr.grid(row=1, column=1, sticky="ns")
    json_btns = ttk.Frame(json_col)
    json_btns.grid(row=2, column=0, sticky="ew", pady=(6,0))
    ttk.Button(json_btns, text="Mở", command=app._load_json_selected).pack(side="left")
    ttk.Button(json_btns, text="Xoá", command=app._delete_json_selected).pack(side="left", padx=(6,0))
    ttk.Button(json_btns, text="Thư mục", command=app._open_json_folder).pack(side="left", padx=(6,0))
    app.json_list.bind("<<ListboxSelect>>", lambda e: app._preview_json_selected())
    app.json_list.bind("<Double-Button-1>", lambda e: app._load_json_selected())
    logger.debug("Đã xây dựng JSON panel.")

    # --- Panel Phải ---
    detail_box = ttk.LabelFrame(tab_report, text="Chi tiết (Báo cáo Tổng hợp)", padding=8)
    detail_box.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
    detail_box.rowconfigure(0, weight=1)
    detail_box.columnconfigure(0, weight=1)
    app.detail_text = ScrolledText(detail_box, wrap="word")
    app.detail_text.grid(row=0, column=0, sticky="nsew")
    app.detail_text.insert("1.0", "Báo cáo tổng hợp sẽ hiển thị tại đây sau khi phân tích.")
    logger.debug("Đã xây dựng Detail Text area.")
    logger.debug("Kết thúc _build_report_tab.")

def _build_chart_tab(app: Any):
    """
    Xây dựng tab "Chart" để hiển thị biểu đồ.
    Nếu thư viện matplotlib không có sẵn, sẽ hiển thị thông báo hướng dẫn cài đặt.

    Args:
        app: Đối tượng ứng dụng chính chứa các biến và phương thức cần thiết.
    """
    logger.debug("Bắt đầu _build_chart_tab.")
    if HAS_MPL:
        # Giao việc xây dựng tab này cho một class chuyên biệt
        app.chart_tab_tv = ChartTabTV(app, app.nb)
        logger.debug("Đã xây dựng ChartTabTV.")
    else:
        tab_chart_placeholder = ttk.Frame(app.nb, padding=8)
        app.nb.add(tab_chart_placeholder, text="Chart")
        ttk.Label(
            tab_chart_placeholder,
            text="Chức năng Chart yêu cầu matplotlib + mplfinance.\n"
                 "Cài: pip install matplotlib mplfinance",
            foreground="#666"
        ).pack(anchor="w")
        logger.warning("Matplotlib không có sẵn, hiển thị placeholder cho tab Chart.")
    logger.debug("Kết thúc _build_chart_tab.")

def _build_prompt_tab(app: Any):
    """
    Xây dựng tab "Prompt" để quản lý và chỉnh sửa các prompt cho mô hình AI.

    Args:
        app: Đối tượng ứng dụng chính chứa các biến và phương thức cần thiết.
    """
    logger.debug("Bắt đầu _build_prompt_tab.")
    tab_prompt = ttk.Frame(app.nb, padding=8)
    app.nb.add(tab_prompt, text="Prompt")
    tab_prompt.columnconfigure(0, weight=1)
    tab_prompt.rowconfigure(1, weight=1)
    logger.debug("Đã thêm tab 'Prompt' vào Notebook.")

    # Các nút hành động: Tải lại, Lưu, Định dạng
    pr_actions = ttk.Frame(tab_prompt)
    pr_actions.grid(row=0, column=0, sticky="ew", pady=(0, 6))
    ttk.Button(pr_actions, text="Tải lại prompt từ file", command=app._load_prompts_from_disk).pack(side="left")
    ttk.Button(pr_actions, text="Lưu prompt hiện tại", command=app._save_current_prompt_to_disk).pack(side="left", padx=(6,0))
    ttk.Button(pr_actions, text="Định dạng lại", command=app._reformat_prompt_area).pack(side="left", padx=(6, 0))
    logger.debug("Đã xây dựng Prompt action buttons.")

    # Notebook con để chia các loại prompt
    app.prompt_nb = ttk.Notebook(tab_prompt)
    app.prompt_nb.grid(row=1, column=0, sticky="nsew")
    logger.debug("Đã xây dựng Prompt Notebook con.")

    # Tab 1: Prompt "No Entry"
    prompt_tab_no_entry = ttk.Frame(app.prompt_nb, padding=(0, 8, 0, 0))
    app.prompt_nb.add(prompt_tab_no_entry, text="Tìm Lệnh Mới (No Entry)")
    prompt_tab_no_entry.columnconfigure(0, weight=1)
    prompt_tab_no_entry.rowconfigure(0, weight=1)
    app.prompt_no_entry_text = ScrolledText(prompt_tab_no_entry, wrap="word", height=18)
    app.prompt_no_entry_text.grid(row=0, column=0, sticky="nsew")
    logger.debug("Đã xây dựng tab 'Tìm Lệnh Mới (No Entry)'.")

    # Tab 2: Prompt "Entry Run"
    prompt_tab_entry_run = ttk.Frame(app.prompt_nb, padding=(0, 8, 0, 0))
    app.prompt_nb.add(prompt_tab_entry_run, text="Quản Lý Lệnh (Entry Run)")
    prompt_tab_entry_run.columnconfigure(0, weight=1)
    prompt_tab_entry_run.rowconfigure(0, weight=1)
    app.prompt_entry_run_text = ScrolledText(prompt_tab_entry_run, wrap="word", height=18)
    app.prompt_entry_run_text.grid(row=0, column=0, sticky="nsew")
    logger.debug("Đã xây dựng tab 'Quản Lý Lệnh (Entry Run)'.")
    logger.debug("Kết thúc _build_prompt_tab.")

def _build_options_tab(app: Any):
    """
    Xây dựng tab "Options" chứa các cài đặt nâng cao cho ứng dụng.

    Args:
        app: Đối tượng ứng dụng chính chứa các biến và phương thức cần thiết.
    """
    logger.debug("Bắt đầu _build_options_tab.")
    tab_opts = ttk.Frame(app.nb, padding=8)
    app.nb.add(tab_opts, text="Options")
    tab_opts.columnconfigure(0, weight=1)
    tab_opts.rowconfigure(0, weight=1)
    logger.debug("Đã thêm tab 'Options' vào Notebook.")

    # Dùng Notebook con để nhóm các tùy chọn
    opts_nb = ttk.Notebook(tab_opts)
    opts_nb.grid(row=0, column=0, sticky="nsew")
    logger.debug("Đã xây dựng Options Notebook con.")

    # --- Tab con: Run ---
    _build_opts_run(app, opts_nb)
    # --- Tab con: Context ---
    _build_opts_context(app, opts_nb)
    # --- Tab con: Telegram ---
    _build_opts_telegram(app, opts_nb)
    # --- Tab con: MT5 ---
    _build_opts_mt5(app, opts_nb)
    # --- Tab con: No Run ---
    _build_opts_norun(app, opts_nb)
    logger.debug("Đã xây dựng các tab con trong Options.")
    logger.debug("Kết thúc _build_options_tab.")


def _build_opts_run(app: Any, parent_notebook: ttk.Notebook):
    """
    Xây dựng các tùy chọn trong tab Options -> Run.

    Args:
        app: Đối tượng ứng dụng chính chứa các biến và phương thức cần thiết.
        parent_notebook: Notebook cha để thêm tab "Run" vào.
    """
    logger.debug("Bắt đầu _build_opts_run.")
    run_tab = ttk.Frame(parent_notebook, padding=8)
    parent_notebook.add(run_tab, text="Run")
    run_tab.columnconfigure(0, weight=1)
    logger.debug("Đã thêm tab con 'Run' vào Options Notebook.")

    # Card: Upload & Giới hạn
    card_upload = ttk.LabelFrame(run_tab, text="Upload & Giới hạn", padding=8)
    card_upload.grid(row=0, column=0, sticky="ew", pady=(8, 0))
    ttk.Checkbutton(card_upload, text="Xoá file trên Gemini sau khi phân tích", variable=app.delete_after_var).grid(row=0, column=0, sticky="w")
    row_ul = ttk.Frame(card_upload)
    row_ul.grid(row=1, column=0, sticky="w", pady=(6, 0))
    ttk.Label(row_ul, text="Giới hạn số ảnh tối đa (0 = không giới hạn):").pack(side="left")
    ttk.Spinbox(row_ul, from_=0, to=1000, textvariable=app.max_files_var, width=8).pack(side="left", padx=(6, 0))
    logger.debug("Đã xây dựng card 'Upload & Giới hạn'.")

    # Card: Tăng tốc & Cache
    card_fast = ttk.LabelFrame(run_tab, text="Tăng tốc & Cache", padding=8)
    card_fast.grid(row=2, column=0, sticky="ew", pady=(8, 0))
    row_w = ttk.Frame(card_fast)
    row_w.grid(row=0, column=0, sticky="w")
    ttk.Label(row_w, text="Số luồng upload song song:").pack(side="left")
    ttk.Spinbox(row_w, from_=1, to=16, textvariable=app.upload_workers_var, width=6).pack(side="left", padx=(6, 0))
    ttk.Checkbutton(card_fast, text="Bật cache ảnh (tái dùng file đã upload nếu chưa đổi)", variable=app.cache_enabled_var).grid(row=1, column=0, sticky="w", pady=(6, 0))
    ttk.Checkbutton(card_fast, text="Tối ưu ảnh lossless trước khi upload (PNG)", variable=app.optimize_lossless_var).grid(row=2, column=0, sticky="w", pady=(6, 0))
    ttk.Checkbutton(card_fast, text="Chỉ gọi model nếu bộ ảnh không đổi", variable=app.only_generate_if_changed_var).grid(row=3, column=0, sticky="w", pady=(6, 0))
    logger.debug("Đã xây dựng card 'Tăng tốc & Cache'.")

    # Card: NO-TRADE cứng
    card_nt = ttk.LabelFrame(run_tab, text="NO-TRADE cứng (chặn gọi model nếu điều kiện xấu)", padding=8)
    card_nt.grid(row=3, column=0, sticky="ew", pady=(8, 0))
    ttk.Checkbutton(card_nt, text="Bật NO-TRADE cứng", variable=app.no_trade_enabled_var).grid(row=0, column=0, columnspan=3, sticky="w")
    r1 = ttk.Frame(card_nt)
    r1.grid(row=1, column=0, sticky="w", pady=(4, 0))
    ttk.Label(r1, text="Ngưỡng spread > p90 ×").pack(side="left")
    ttk.Spinbox(r1, from_=1.0, to=3.0, increment=0.1, textvariable=app.nt_spread_factor_var, width=6).pack(side="left", padx=(6, 12))
    r2 = ttk.Frame(card_nt)
    r2.grid(row=2, column=0, sticky="w", pady=(4, 0))
    ttk.Label(r2, text="ATR M5 tối thiểu (pips):").pack(side="left")
    ttk.Spinbox(r2, from_=0.5, to=50.0, increment=0.5, textvariable=app.nt_min_atr_m5_pips_var, width=6).pack(side="left", padx=(6, 12))
    r3 = ttk.Frame(card_nt)
    r3.grid(row=3, column=0, sticky="w", pady=(4, 0))
    ttk.Label(r3, text="Ticks mỗi phút tối thiểu (5m):").pack(side="left")
    ttk.Spinbox(r3, from_=0, to=200, textvariable=app.nt_min_ticks_per_min_var, width=6).pack(side="left", padx=(6, 12))
    logger.debug("Đã xây dựng card 'NO-TRADE cứng'.")
    logger.debug("Kết thúc _build_opts_run.")

def _build_opts_context(app: Any, parent_notebook: ttk.Notebook):
    """
    Xây dựng các tùy chọn trong tab Options -> Context.

    Args:
        app: Đối tượng ứng dụng chính chứa các biến và phương thức cần thiết.
        parent_notebook: Notebook cha để thêm tab "Context" vào.
    """
    logger.debug("Bắt đầu _build_opts_context.")
    ctx_tab = ttk.Frame(parent_notebook, padding=8)
    parent_notebook.add(ctx_tab, text="Context")
    ctx_tab.columnconfigure(0, weight=1)
    logger.debug("Đã thêm tab con 'Context' vào Options Notebook.")

    # Card: Ngữ cảnh từ Text Reports
    card_ctx_text = ttk.LabelFrame(ctx_tab, text="Ngữ cảnh từ lịch sử (Text Reports)", padding=8)
    card_ctx_text.grid(row=0, column=0, sticky="ew")
    ttk.Checkbutton(card_ctx_text, text="Dùng ngữ cảnh từ báo cáo trước (text)", variable=app.remember_context_var).grid(row=0, column=0, columnspan=3, sticky="w")
    rowt = ttk.Frame(card_ctx_text)
    rowt.grid(row=1, column=0, sticky="w", pady=(6, 0))
    ttk.Label(rowt, text="Số báo cáo gần nhất:").pack(side="left")
    ttk.Spinbox(rowt, from_=1, to=10, textvariable=app.context_n_reports_var, width=6).pack(side="left", padx=(6, 12))
    ttk.Label(rowt, text="Giới hạn ký tự/report:").pack(side="left")
    ttk.Spinbox(rowt, from_=500, to=8000, increment=250, textvariable=app.context_limit_chars_var, width=8).pack(side="left", padx=(6, 0))
    logger.debug("Đã xây dựng card 'Ngữ cảnh từ Text Reports'.")

    # Card: Ngữ cảnh từ JSON
    card_ctx_json = ttk.LabelFrame(ctx_tab, text="Ngữ cảnh tóm tắt JSON", padding=8)
    card_ctx_json.grid(row=1, column=0, sticky="ew", pady=(8, 0))
    ttk.Checkbutton(card_ctx_json, text="Tự tạo tóm tắt JSON sau mỗi lần phân tích", variable=app.create_ctx_json_var).grid(row=0, column=0, sticky="w")
    ttk.Checkbutton(card_ctx_json, text="Ưu tiên dùng tóm tắt JSON làm bối cảnh", variable=app.prefer_ctx_json_var).grid(row=1, column=0, sticky="w", pady=(4, 0))
    rowj = ttk.Frame(card_ctx_json)
    rowj.grid(row=2, column=0, sticky="w", pady=(6, 0))
    ttk.Label(rowj, text="Số JSON gần nhất:").pack(side="left")
    ttk.Spinbox(rowj, from_=1, to=20, textvariable=app.ctx_json_n_var, width=6).pack(side="left", padx=(6, 0))
    logger.debug("Đã xây dựng card 'Ngữ cảnh từ JSON'.")
    logger.debug("Kết thúc _build_opts_context.")

def _build_opts_telegram(app: Any, parent_notebook: ttk.Notebook):
    """
    Xây dựng các tùy chọn trong tab Options -> Telegram.

    Args:
        app: Đối tượng ứng dụng chính chứa các biến và phương thức cần thiết.
        parent_notebook: Notebook cha để thêm tab "Telegram" vào.
    """
    logger.debug("Bắt đầu _build_opts_telegram.")
    tg_tab = ttk.Frame(parent_notebook, padding=8)
    parent_notebook.add(tg_tab, text="Telegram")
    tg_tab.columnconfigure(1, weight=1)
    logger.debug("Đã thêm tab con 'Telegram' vào Options Notebook.")

    ttk.Checkbutton(tg_tab, text="Bật thông báo khi có setup xác suất cao", variable=app.telegram_enabled_var).grid(row=0, column=0, columnspan=3, sticky="w")
    ttk.Label(tg_tab, text="Bot Token:").grid(row=1, column=0, sticky="w", pady=(6, 0))
    tk.Entry(tg_tab, textvariable=app.telegram_token_var, show="*", width=48).grid(row=1, column=1, sticky="ew", padx=(6, 0), pady=(6, 0))
    ttk.Label(tg_tab, text="Chat ID:").grid(row=2, column=0, sticky="w", pady=(6, 0))
    tk.Entry(tg_tab, textvariable=app.telegram_chat_id_var, width=24).grid(row=2, column=1, sticky="w", padx=(6, 0), pady=(6, 0))
    ttk.Button(tg_tab, text="Gửi thử", command=app._telegram_test).grid(row=2, column=2, sticky="e", padx=(8, 0), pady=(6, 0))
    ttk.Label(tg_tab, text="CA bundle (.pem/.crt):").grid(row=3, column=0, sticky="w", pady=(6, 0))
    tk.Entry(tg_tab, textvariable=app.telegram_ca_path_var).grid(row=3, column=1, sticky="ew", padx=(6, 0), pady=(6, 0))
    ttk.Button(tg_tab, text="Chọn…", command=app._pick_ca_bundle).grid(row=3, column=2, sticky="e", padx=(8, 0), pady=(6, 0))
    ttk.Checkbutton(tg_tab, text="Bỏ qua kiểm tra chứng chỉ (KHÔNG KHUYẾN NGHỊ)", variable=app.telegram_skip_verify_var).grid(row=4, column=0, columnspan=3, sticky="w", pady=(6, 0))
    logger.debug("Đã xây dựng Telegram options.")
    logger.debug("Kết thúc _build_opts_telegram.")

def _build_opts_mt5(app: Any, parent_notebook: ttk.Notebook):
    """
    Xây dựng các tùy chọn trong tab Options -> MT5.

    Args:
        app: Đối tượng ứng dụng chính chứa các biến và phương thức cần thiết.
        parent_notebook: Notebook cha để thêm tab "MT5" vào.
    """
    logger.debug("Bắt đầu _build_opts_mt5.")
    mt5_tab = ttk.Frame(parent_notebook, padding=8)
    parent_notebook.add(mt5_tab, text="MT5")
    mt5_tab.columnconfigure(1, weight=1)
    logger.debug("Đã thêm tab con 'MT5' vào Options Notebook.")

    # Cài đặt kết nối MT5
    ttk.Checkbutton(mt5_tab, text="Bật lấy dữ liệu nến từ MT5 và đưa vào phân tích", variable=app.mt5_enabled_var).grid(row=0, column=0, columnspan=3, sticky="w")
    ttk.Label(mt5_tab, text="MT5 terminal (tùy chọn):").grid(row=1, column=0, sticky="w", pady=(6, 0))
    tk.Entry(mt5_tab, textvariable=app.mt5_term_path_var).grid(row=1, column=1, sticky="ew", padx=(6, 0), pady=(6, 0))
    ttk.Button(mt5_tab, text="Chọn…", command=app._pick_mt5_terminal).grid(row=1, column=2, sticky="e", padx=(8, 0), pady=(6, 0))
    ttk.Label(mt5_tab, text="Symbol:").grid(row=2, column=0, sticky="w", pady=(6, 0))
    tk.Entry(mt5_tab, textvariable=app.mt5_symbol_var, width=18).grid(row=2, column=1, sticky="w", padx=(6, 0), pady=(6, 0))
    ttk.Button(mt5_tab, text="Tự nhận từ tên ảnh", command=app._mt5_guess_symbol).grid(row=2, column=2, sticky="e", padx=(8, 0), pady=(6, 0))
    logger.debug("Đã xây dựng MT5 connection settings.")

    # Cài đặt số nến
    rowc = ttk.Frame(mt5_tab)
    rowc.grid(row=3, column=0, columnspan=3, sticky="w", pady=(6, 0))
    ttk.Label(rowc, text="Số nến:").pack(side="left")
    timeframes = {"M1": app.mt5_n_M1, "M5": app.mt5_n_M5, "M15": app.mt5_n_M15, "H1": app.mt5_n_H1}
    for tf, var in timeframes.items():
        ttk.Label(rowc, text=tf).pack(side="left", padx=(10, 2))
        ttk.Spinbox(rowc, from_=20, to=2000, textvariable=var, width=6).pack(side="left")
    logger.debug("Đã xây dựng MT5 candle count settings.")

    # Nút kiểm tra kết nối và snapshot
    btns_mt5 = ttk.Frame(mt5_tab)
    btns_mt5.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(6, 0))
    btns_mt5.columnconfigure(0, weight=1)
    btns_mt5.columnconfigure(1, weight=1)
    ttk.Button(btns_mt5, text="Kết nối/kiểm tra MT5", command=app._mt5_connect).grid(row=0, column=0, sticky="ew")
    ttk.Button(btns_mt5, text="Chụp snapshot ngay", command=app._mt5_snapshot_popup).grid(row=0, column=1, sticky="ew", padx=(6, 0))
    ttk.Label(mt5_tab, textvariable=app.mt5_status_var, foreground="#555").grid(row=5, column=0, columnspan=3, sticky="w", pady=(6, 0))
    logger.debug("Đã xây dựng MT5 connection/snapshot buttons.")

    # Card: Auto-Trade
    _build_opts_autotrade(app, mt5_tab)
    logger.debug("Kết thúc _build_opts_mt5.")

def _build_opts_autotrade(app: Any, parent_tab: ttk.Frame):
    """
    Xây dựng khu vực cài đặt Auto-Trade trong tab MT5.

    Args:
        app: Đối tượng ứng dụng chính chứa các biến và phương thức cần thiết.
        parent_tab: Tab cha để thêm các cài đặt Auto-Trade vào.
    """
    logger.debug("Bắt đầu _build_opts_autotrade.")
    auto_card = ttk.LabelFrame(parent_tab, text="Auto-Trade khi có Thiết lập xác suất cao", padding=8)
    auto_card.grid(row=6, column=0, columnspan=3, sticky="ew", pady=(8, 0))

    # Các dòng cài đặt (r0, r1, ...)
    r0 = ttk.Frame(auto_card)
    r0.grid(row=0, column=0, columnspan=3, sticky="w")
    ttk.Checkbutton(r0, text="Bật Auto-Trade", variable=app.auto_trade_enabled_var).pack(side="left")
    ttk.Checkbutton(r0, text="KHÔNG trade nếu NGƯỢC bias H1", variable=app.trade_strict_bias_var).pack(side="left", padx=(12,0))
    logger.debug("Đã xây dựng Auto-Trade r0.")

    r1 = ttk.Frame(auto_card)
    r1.grid(row=1, column=0, columnspan=3, sticky="w", pady=(6,0))
    ttk.Label(r1, text="Khối lượng:").pack(side="left")
    ttk.Radiobutton(r1, text="Lots cố định", value="lots", variable=app.trade_size_mode_var).pack(side="left", padx=(6,0))
    ttk.Radiobutton(r1, text="% Equity", value="percent", variable=app.trade_size_mode_var).pack(side="left", padx=(6,0))
    ttk.Radiobutton(r1, text="Tiền rủi ro", value="money", variable=app.trade_size_mode_var).pack(side="left", padx=(6,0))
    logger.debug("Đã xây dựng Auto-Trade r1.")

    r2 = ttk.Frame(auto_card)
    r2.grid(row=2, column=0, columnspan=3, sticky="w", pady=(4,0))
    ttk.Label(r2, text="Lots:").pack(side="left")
    ttk.Spinbox(r2, from_=0.01, to=100.0, increment=0.01, textvariable=app.trade_lots_total_var, width=8).pack(side="left", padx=(6,12))
    ttk.Label(r2, text="% Equity rủi ro:").pack(side="left")
    ttk.Spinbox(r2, from_=0.1, to=10.0, increment=0.1, textvariable=app.trade_equity_risk_pct_var, width=6).pack(side="left", padx=(6,12))
    ttk.Label(r2, text="Tiền rủi ro:").pack(side="left")
    ttk.Spinbox(r2, from_=1.0, to=1_000_000.0, increment=1.0, textvariable=app.trade_money_risk_var, width=10).pack(side="left", padx=(6,12))
    logger.debug("Đã xây dựng Auto-Trade r2.")

    r3 = ttk.Frame(auto_card)
    r3.grid(row=3, column=0, columnspan=3, sticky="w", pady=(4,0))
    ttk.Label(r3, text="Chia TP1 (%):").pack(side="left")
    ttk.Spinbox(r3, from_=1, to=99, textvariable=app.trade_split_tp1_pct_var, width=6).pack(side="left", padx=(6,12))
    ttk.Label(r3, text="Deviation (points):").pack(side="left")
    ttk.Spinbox(r3, from_=5, to=200, textvariable=app.trade_deviation_points_var, width=6).pack(side="left", padx=(6,12))
    ttk.Label(r3, text="Ngưỡng pending (points):").pack(side="left")
    ttk.Spinbox(r3, from_=5, to=2000, textvariable=app.trade_pending_threshold_points_var, width=8).pack(side="left", padx=(6,12))
    logger.debug("Đã xây dựng Auto-Trade r3.")

    r4 = ttk.Frame(auto_card)
    r4.grid(row=4, column=0, columnspan=3, sticky="w", pady=(4,0))
    ttk.Label(r4, text="Magic:").pack(side="left")
    ttk.Spinbox(r4, from_=1, to=2_147_000_000, textvariable=app.trade_magic_var, width=12).pack(side="left", padx=(6,12))
    ttk.Label(r4, text="Comment:").pack(side="left")
    tk.Entry(r4, textvariable=app.trade_comment_prefix_var, width=18).pack(side="left", padx=(6,0))
    logger.debug("Đã xây dựng Auto-Trade r4.")

    r5 = ttk.Frame(auto_card)
    r5.grid(row=5, column=0, columnspan=3, sticky="w", pady=(4,0))
    ttk.Checkbutton(r5, text="Dry-run (không gửi lệnh)", variable=app.auto_trade_dry_run_var).pack(side="left")
    ttk.Checkbutton(r5, text="Pending theo ATR", variable=app.trade_dynamic_pending_var).pack(side="left", padx=(12,0))
    ttk.Checkbutton(r5, text="BE sau TP1", variable=app.trade_move_to_be_after_tp1_var).pack(side="left", padx=(12,0))
    logger.debug("Đã xây dựng Auto-Trade r5.")

    r6 = ttk.Frame(auto_card)
    r6.grid(row=6, column=0, columnspan=3, sticky="w", pady=(4,0))
    ttk.Label(r6, text="TTL pending (phút):").pack(side="left")
    ttk.Spinbox(r6, from_=1, to=1440, textvariable=app.trade_pending_ttl_min_var, width=6).pack(side="left", padx=(6,12))
    ttk.Label(r6, text="RR tối thiểu TP2:").pack(side="left")
    ttk.Spinbox(r6, from_=1.0, to=10.0, increment=0.1, textvariable=app.trade_min_rr_tp2_var, width=6).pack(side="left", padx=(6,12))
    ttk.Label(r6, text="Khoảng cách key lvl (pips):").pack(side="left")
    ttk.Spinbox(r6, from_=0.0, to=200.0, increment=0.5, textvariable=app.trade_min_dist_keylvl_pips_var, width=8).pack(side="left", padx=(6,12))
    ttk.Label(r6, text="Cooldown (phút):").pack(side="left")
    ttk.Spinbox(r6, from_=0, to=360, textvariable=app.trade_cooldown_min_var, width=6).pack(side="left", padx=(6,12))
    logger.debug("Đã xây dựng Auto-Trade r6.")

    r7 = ttk.Frame(auto_card)
    r7.grid(row=7, column=0, columnspan=3, sticky="w", pady=(4,0))
    ttk.Label(r7, text="Trailing ATR ×").pack(side="left")
    ttk.Spinbox(r7, from_=0.1, to=3.0, increment=0.1, textvariable=app.trade_trailing_atr_mult_var, width=6).pack(side="left", padx=(6,12))
    logger.debug("Đã xây dựng Auto-Trade r7.")

    r8 = ttk.Frame(auto_card)
    r8.grid(row=8, column=0, columnspan=3, sticky="w", pady=(4,0))
    ttk.Label(r8, text="Phiên cho phép:").pack(side="left")
    ttk.Checkbutton(r8, text="Asia", variable=app.trade_allow_session_asia_var).pack(side="left", padx=(6,0))
    ttk.Checkbutton(r8, text="London", variable=app.trade_allow_session_london_var).pack(side="left", padx=(6,0))
    ttk.Checkbutton(r8, text="New York", variable=app.trade_allow_session_ny_var).pack(side="left", padx=(6,0))
    logger.debug("Đã xây dựng Auto-Trade r8.")

    r9 = ttk.Frame(auto_card)
    r9.grid(row=9, column=0, columnspan=3, sticky="w", pady=(4,0))
    ttk.Label(r9, text="Chặn quanh news:").pack(side="left")
    ttk.Label(r9, text="Trước (phút):").pack(side="left", padx=(8,2))
    ttk.Spinbox(r9, from_=0, to=180, textvariable=app.trade_news_block_before_min_var, width=6).pack(side="left")
    ttk.Label(r9, text="Sau (phút):").pack(side="left", padx=(8,2))
    ttk.Spinbox(r9, from_=0, to=180, textvariable=app.trade_news_block_after_min_var, width=6).pack(side="left")
    ttk.Label(r9, text="Nguồn: Forex Factory (High)").pack(side="left", padx=(12,0))
    logger.debug("Đã xây dựng Auto-Trade r9.")
    logger.debug("Kết thúc _build_opts_autotrade.")

def _build_opts_norun(app: Any, parent_notebook: ttk.Notebook):
    """
    Xây dựng các tùy chọn trong tab Options -> No Run.

    Args:
        app: Đối tượng ứng dụng chính chứa các biến và phương thức cần thiết.
        parent_notebook: Notebook cha để thêm tab "No Run" vào.
    """
    logger.debug("Bắt đầu _build_opts_norun.")
    norun_tab = ttk.Frame(parent_notebook, padding=8)
    parent_notebook.add(norun_tab, text="No Run")
    norun_tab.columnconfigure(0, weight=1)
    card_norun = ttk.LabelFrame(norun_tab, text="Điều kiện không chạy phân tích tự động", padding=8)
    card_norun.grid(row=0, column=0, sticky="ew")
    ttk.Checkbutton(card_norun, text="Không chạy vào Thứ 7 và Chủ Nhật", variable=app.no_run_weekend_enabled_var).grid(row=0, column=0, sticky="w")
    ttk.Checkbutton(card_norun, text="Chỉ chạy trong thời gian Kill Zone", variable=app.norun_killzone_var).grid(row=1, column=0, sticky="w", pady=(4, 0))
    logger.debug("Đã xây dựng card 'No Run'.")
    logger.debug("Kết thúc _build_opts_norun.")


# =====================================================================================
# HÀM CHÍNH
# =====================================================================================

def build_ui(app: Any):
    """
    Hàm chính để xây dựng toàn bộ giao diện người dùng.
    Nó gọi các hàm con để xây dựng từng phần của giao diện một cách tuần tự.

    Args:
        app: Đối tượng ứng dụng chính chứa các biến và phương thức cần thiết.
    """
    logger.debug("Bắt đầu build_ui.")
    # Cấu hình cột chính của cửa sổ gốc để co giãn
    app.root.columnconfigure(0, weight=1)

    # 1. Xây dựng khu vực điều khiển trên cùng
    _build_top_frame(app)

    # 2. Xây dựng khu vực thanh tiến trình
    _build_progress_frame(app)

    # 3. Xây dựng khu vực Notebook chính chứa các tab
    app.nb = ttk.Notebook(app.root)
    app.nb.grid(row=2, column=0, sticky="nsew", padx=8, pady=(0, 8))
    # Cấu hình hàng chứa Notebook để co giãn theo chiều dọc
    app.root.rowconfigure(2, weight=1)
    logger.debug("Đã xây dựng Notebook chính.")

    # 4. Xây dựng các tab bên trong Notebook
    _build_report_tab(app)
    _build_chart_tab(app)
    _build_prompt_tab(app)
    _build_options_tab(app)
    logger.debug("Đã xây dựng các tab chính.")

    # 5. Tải dữ liệu ban đầu sau khi UI đã được xây dựng
    app._refresh_history_list()
    app._refresh_json_list()
    app._load_prompts_from_disk()
    logger.debug("Đã tải dữ liệu ban đầu.")
    logger.debug("Kết thúc build_ui.")
