# -*- coding: utf-8 -*-
import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

try:
    import matplotlib
    HAS_MPL = True
except ImportError:
    HAS_MPL = False

from src.core.chart_tab import ChartTabTV

def build_ui(app):
    app.root.columnconfigure(0, weight=1)

    top = ttk.Frame(app.root, padding=(10, 8, 10, 6))
    top.grid(row=0, column=0, sticky="ew")
    for c in (1, 3, 5):
        top.columnconfigure(c, weight=1)

    ttk.Label(top, text="API Key:").grid(row=0, column=0, sticky="w")
    app.api_entry = ttk.Entry(top, textvariable=app.api_key_var, show="*", width=44)
    app.api_entry.grid(row=0, column=1, sticky="ew", padx=(6, 8))
    ttk.Checkbutton(top, text="Hiện", command=app._toggle_api_visibility).grid(row=0, column=2, sticky="w")

    ttk.Button(top, text="Tải .env", command=app._load_env).grid(row=0, column=3, sticky="w")
    ttk.Button(top, text="Lưu an toàn", command=app._save_api_safe).grid(row=0, column=4, sticky="w", padx=(6, 0))
    ttk.Button(top, text="Xoá đã lưu", command=app._delete_api_safe).grid(row=0, column=5, sticky="w", padx=(6, 0))

    ttk.Label(top, text="Model:").grid(row=1, column=0, sticky="w", pady=(6, 0))
    app.model_combo = ttk.Combobox(
        top,
        textvariable=app.model_var,
        values=["gemini-1.5-flash", "gemini-1.5-pro", "gemini-2.5-flash", "gemini-2.5-pro"],
        state="readonly",
        width=22,
    )
    app.model_combo.grid(row=1, column=1, sticky="w", padx=(6, 8), pady=(6, 0))

    ttk.Label(top, text="Thư mục ảnh:").grid(row=1, column=2, sticky="e", pady=(6, 0))
    app.folder_label = ttk.Entry(top, textvariable=app.folder_path, state="readonly")
    app.folder_label.grid(row=1, column=3, sticky="ew", padx=(6, 8), pady=(6, 0))
    ttk.Button(top, text="Chọn thư mục…", command=app.choose_folder).grid(row=1, column=4, sticky="w", pady=(6, 0))

    actions = ttk.Frame(top)
    actions.grid(row=1, column=5, sticky="e", pady=(6, 0))
    ttk.Button(actions, text="► Bắt đầu", command=app.start_analysis).pack(side="left")
    app.stop_btn = ttk.Button(actions, text="□ Dừng", command=app.stop_analysis, state="disabled")
    app.stop_btn.pack(side="left", padx=(6, 0))
    app.export_btn = ttk.Button(actions, text="↓ Xuất .md", command=app.export_markdown, state="disabled")
    app.export_btn.pack(side="left", padx=(6, 0))
    ttk.Button(actions, text="✖ Xoá kết quả", command=app.clear_results).pack(side="left", padx=(6, 0))

    prog = ttk.Frame(app.root, padding=(10, 0, 10, 6))
    prog.grid(row=1, column=0, sticky="ew")
    prog.columnconfigure(0, weight=1)
    ttk.Progressbar(prog, variable=app.progress_var, maximum=100).grid(row=0, column=0, sticky="ew")
    ttk.Label(prog, textvariable=app.status_var).grid(row=1, column=0, sticky="w", pady=(3, 0))

    app.nb = ttk.Notebook(app.root)
    app.nb.grid(row=2, column=0, sticky="nsew", padx=8, pady=(0, 8))
    app.root.rowconfigure(2, weight=1)

    tab_report = ttk.Frame(app.nb, padding=8)
    app.nb.add(tab_report, text="Report")

    tab_report.columnconfigure(0, weight=1)
    tab_report.columnconfigure(1, weight=2)
    tab_report.rowconfigure(0, weight=1)

    left_panel = ttk.Frame(tab_report)
    left_panel.grid(row=0, column=0, sticky="nsew")
    left_panel.columnconfigure(0, weight=1)
    left_panel.rowconfigure(0, weight=1)
    left_panel.rowconfigure(1, weight=1)

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
    app.tree.configure(yscrollcommand= scr_y.set)
    scr_y.grid(row=0, column=0, sticky="nse", padx=(0,0))
    app.tree.bind("<<TreeviewSelect>>", app._on_tree_select)

    archives = ttk.LabelFrame(left_panel, text="History & JSON", padding=6)
    archives.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
    archives.columnconfigure(0, weight=1)
    archives.columnconfigure(1, weight=1)
    archives.rowconfigure(1, weight=1)

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

    hist_btns = ttk.Frame(hist_col); hist_btns.grid(row=2, column=0, sticky="ew", pady=(6,0))
    ttk.Button(hist_btns, text="Mở",   command=app._open_history_selected).pack(side="left")
    ttk.Button(hist_btns, text="Xoá",  command=app._delete_history_selected).pack(side="left", padx=(6,0))
    ttk.Button(hist_btns, text="Thư mục", command=app._open_reports_folder).pack(side="left", padx=(6,0))

    app.history_list.bind("<<ListboxSelect>>", lambda e: app._preview_history_selected())
    app.history_list.bind("<Double-Button-1>", lambda e: app._open_history_selected())

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

    json_btns = ttk.Frame(json_col); json_btns.grid(row=2, column=0, sticky="ew", pady=(6,0))
    ttk.Button(json_btns, text="Mở",   command=app._load_json_selected).pack(side="left")
    ttk.Button(json_btns, text="Xoá",  command=app._delete_json_selected).pack(side="left", padx=(6,0))
    ttk.Button(json_btns, text="Thư mục", command=app._open_json_folder).pack(side="left", padx=(6,0))

    app.json_list.bind("<<ListboxSelect>>", lambda e: app._preview_json_selected())
    app.json_list.bind("<Double-Button-1>", lambda e: app._load_json_selected())

    detail_box = ttk.LabelFrame(tab_report, text="Chi tiết (Báo cáo Tổng hợp)", padding=8)
    detail_box.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
    detail_box.rowconfigure(0, weight=1)
    detail_box.columnconfigure(0, weight=1)
    app.detail_text = ScrolledText(detail_box, wrap="word")
    app.detail_text.grid(row=0, column=0, sticky="nsew")
    app.detail_text.insert("1.0", "Báo cáo tổng hợp sẽ hiển thị tại đây sau khi phân tích.")

    app._refresh_history_list()
    app._refresh_json_list()

    if HAS_MPL:
        app.chart_tab_tv = ChartTabTV(app, app.nb)
    else:
        tab_chart_placeholder = ttk.Frame(app.nb, padding=8)
        app.nb.add(tab_chart_placeholder, text="Chart")
        ttk.Label(
            tab_chart_placeholder,
            text="Chức năng Chart yêu cầu matplotlib + mplfinance.\n"
                 "Cài: pip install matplotlib",
            foreground="#666"
        ).pack(anchor="w")

    tab_prompt = ttk.Frame(app.nb, padding=8)
    app.nb.add(tab_prompt, text="Prompt")
    tab_prompt.columnconfigure(0, weight=1)
    tab_prompt.rowconfigure(1, weight=1)

    # --- Prompt Actions ---
    pr_actions = ttk.Frame(tab_prompt)
    pr_actions.grid(row=0, column=0, sticky="ew", pady=(0, 6))
    ttk.Button(pr_actions, text="Tải lại prompt từ file", command=app._load_prompts_from_disk).pack(side="left")
    ttk.Button(pr_actions, text="Lưu prompt hiện tại", command=app._save_current_prompt_to_disk).pack(side="left", padx=(6,0))
    ttk.Button(pr_actions, text="Định dạng lại", command=app._reformat_prompt_area).pack(side="left", padx=(6, 0))

    # --- Prompt Notebook (Tabs) ---
    app.prompt_nb = ttk.Notebook(tab_prompt)
    app.prompt_nb.grid(row=1, column=0, sticky="nsew")

    # --- Tab 1: No Entry ---
    prompt_tab_no_entry = ttk.Frame(app.prompt_nb, padding=(0, 8, 0, 0))
    app.prompt_nb.add(prompt_tab_no_entry, text="Tìm Lệnh Mới (No Entry)")
    prompt_tab_no_entry.columnconfigure(0, weight=1)
    prompt_tab_no_entry.rowconfigure(0, weight=1)
    app.prompt_no_entry_text = ScrolledText(prompt_tab_no_entry, wrap="word", height=18)
    app.prompt_no_entry_text.grid(row=0, column=0, sticky="nsew")

    # --- Tab 2: Entry Run ---
    prompt_tab_entry_run = ttk.Frame(app.prompt_nb, padding=(0, 8, 0, 0))
    app.prompt_nb.add(prompt_tab_entry_run, text="Quản Lý Lệnh (Entry Run)")
    prompt_tab_entry_run.columnconfigure(0, weight=1)
    prompt_tab_entry_run.rowconfigure(0, weight=1)
    app.prompt_entry_run_text = ScrolledText(prompt_tab_entry_run, wrap="word", height=18)
    app.prompt_entry_run_text.grid(row=0, column=0, sticky="nsew")

    app._load_prompts_from_disk()

    tab_opts = ttk.Frame(app.nb, padding=8)
    app.nb.add(tab_opts, text="Options")
    tab_opts.columnconfigure(0, weight=1)
    tab_opts.rowconfigure(0, weight=1)
    opts_nb = ttk.Notebook(tab_opts)
    opts_nb.grid(row=0, column=0, sticky="nsew")

    run_tab = ttk.Frame(opts_nb, padding=8)
    opts_nb.add(run_tab, text="Run")
    run_tab.columnconfigure(0, weight=1)

    card_auto = ttk.LabelFrame(run_tab, text="Auto-run", padding=8)
    card_auto.grid(row=0, column=0, sticky="ew")
    row_ar = ttk.Frame(card_auto)
    row_ar.grid(row=0, column=0, sticky="w")
    ttk.Checkbutton(row_ar, text="Tự động chạy định kỳ", variable=app.autorun_var,
                    command=app._toggle_autorun).pack(side="left")
    ttk.Label(row_ar, text="  mỗi (giây):").pack(side="left")
    app.autorun_interval_spin = ttk.Spinbox(
        row_ar, from_=5, to=86400, textvariable=app.autorun_seconds_var, width=8,
        command=app._autorun_interval_changed
    )
    app.autorun_interval_spin.pack(side="left", padx=(6, 0))
    app.autorun_interval_spin.bind("<FocusOut>", lambda e: app._autorun_interval_changed())

    card_upload = ttk.LabelFrame(run_tab, text="Upload & Giới hạn", padding=8)
    card_upload.grid(row=1, column=0, sticky="ew", pady=(8, 0))
    ttk.Checkbutton(card_upload, text="Xoá file trên Gemini sau khi phân tích",
                    variable=app.delete_after_var).grid(row=0, column=0, sticky="w")
    row_ul = ttk.Frame(card_upload)
    row_ul.grid(row=1, column=0, sticky="w", pady=(6, 0))
    ttk.Label(row_ul, text="Giới hạn số ảnh tối đa (0 = không giới hạn):").pack(side="left")
    ttk.Spinbox(row_ul, from_=0, to=1000, textvariable=app.max_files_var, width=8).pack(side="left", padx=(6, 0))

    card_fast = ttk.LabelFrame(run_tab, text="Tăng tốc & Cache", padding=8)
    card_fast.grid(row=2, column=0, sticky="ew", pady=(8, 0))
    row_w = ttk.Frame(card_fast)
    row_w.grid(row=0, column=0, sticky="w")
    ttk.Label(row_w, text="Số luồng upload song song:").pack(side="left")
    ttk.Spinbox(row_w, from_=1, to=16, textvariable=app.upload_workers_var, width=6).pack(side="left", padx=(6, 0))
    ttk.Checkbutton(card_fast, text="Bật cache ảnh (tái dùng file đã upload nếu chưa đổi)",
                    variable=app.cache_enabled_var).grid(row=1, column=0, sticky="w", pady=(6, 0))
    ttk.Checkbutton(card_fast, text="Tối ưu ảnh lossless trước khi upload (PNG)",
                    variable=app.optimize_lossless_var).grid(row=2, column=0, sticky="w", pady=(6, 0))
    ttk.Checkbutton(card_fast, text="Chỉ gọi model nếu bộ ảnh không đổi",
                    variable=app.only_generate_if_changed_var).grid(row=3, column=0, sticky="w", pady=(6, 0))

    card_nt = ttk.LabelFrame(run_tab, text="NO-TRADE cứng (chặn gọi model nếu điều kiện xấu)", padding=8)
    card_nt.grid(row=3, column=0, sticky="ew", pady=(8, 0))
    ttk.Checkbutton(card_nt, text="Bật NO-TRADE cứng",
                    variable=app.no_trade_enabled_var).grid(row=0, column=0, columnspan=3, sticky="w")
    r1 = ttk.Frame(card_nt); r1.grid(row=1, column=0, sticky="w", pady=(4, 0))
    ttk.Label(r1, text="Ngưỡng spread > p90 ×").pack(side="left")
    ttk.Spinbox(r1, from_=1.0, to=3.0, increment=0.1,
                textvariable=app.nt_spread_factor_var, width=6).pack(side="left", padx=(6, 12))
    r2 = ttk.Frame(card_nt); r2.grid(row=2, column=0, sticky="w", pady=(4, 0))
    ttk.Label(r2, text="ATR M5 tối thiểu (pips):").pack(side="left")
    ttk.Spinbox(r2, from_=0.5, to=50.0, increment=0.5,
                textvariable=app.nt_min_atr_m5_pips_var, width=6).pack(side="left", padx=(6, 12))
    r3 = ttk.Frame(card_nt); r3.grid(row=3, column=0, sticky="w", pady=(4, 0))
    ttk.Label(r3, text="Ticks mỗi phút tối thiểu (5m):").pack(side="left")
    ttk.Spinbox(r3, from_=0, to=200, textvariable=app.nt_min_ticks_per_min_var,
                width=6).pack(side="left", padx=(6, 12))

    ctx_tab = ttk.Frame(opts_nb, padding=8)
    opts_nb.add(ctx_tab, text="Context")
    ctx_tab.columnconfigure(0, weight=1)

    card_ctx_text = ttk.LabelFrame(ctx_tab, text="Ngữ cảnh từ lịch sử (Text Reports)", padding=8)
    card_ctx_text.grid(row=0, column=0, sticky="ew")
    ttk.Checkbutton(card_ctx_text, text="Dùng ngữ cảnh từ báo cáo trước (text)",
                    variable=app.remember_context_var).grid(row=0, column=0, columnspan=3, sticky="w")
    rowt = ttk.Frame(card_ctx_text)
    rowt.grid(row=1, column=0, sticky="w", pady=(6, 0))
    ttk.Label(rowt, text="Số báo cáo gần nhất:").pack(side="left")
    ttk.Spinbox(rowt, from_=1, to=10, textvariable=app.context_n_reports_var, width=6).pack(side="left", padx=(6, 12))
    ttk.Label(rowt, text="Giới hạn ký tự/report:").pack(side="left")
    ttk.Spinbox(rowt, from_=500, to=8000, increment=250, textvariable=app.context_limit_chars_var, width=8).pack(side="left", padx=(6, 0))

    card_ctx_json = ttk.LabelFrame(ctx_tab, text="Ngữ cảnh tóm tắt JSON", padding=8)
    card_ctx_json.grid(row=1, column=0, sticky="ew", pady=(8, 0))
    ttk.Checkbutton(card_ctx_json, text="Tự tạo tóm tắt JSON sau mỗi lần phân tích",
                    variable=app.create_ctx_json_var).grid(row=0, column=0, sticky="w")
    ttk.Checkbutton(card_ctx_json, text="Ưu tiên dùng tóm tắt JSON làm bối cảnh",
                    variable=app.prefer_ctx_json_var).grid(row=1, column=0, sticky="w", pady=(4, 0))
    rowj = ttk.Frame(card_ctx_json)
    rowj.grid(row=2, column=0, sticky="w", pady=(6, 0))
    ttk.Label(rowj, text="Số JSON gần nhất:").pack(side="left")
    ttk.Spinbox(rowj, from_=1, to=20, textvariable=app.ctx_json_n_var, width=6).pack(side="left", padx=(6, 0))

    tg_tab = ttk.Frame(opts_nb, padding=8)
    opts_nb.add(tg_tab, text="Telegram")
    tg_tab.columnconfigure(1, weight=1)

    ttk.Checkbutton(tg_tab, text="Bật thông báo khi có setup xác suất cao",
                    variable=app.telegram_enabled_var).grid(row=0, column=0, columnspan=3, sticky="w")
    ttk.Label(tg_tab, text="Bot Token:").grid(row=1, column=0, sticky="w", pady=(6, 0))
    tk.Entry(tg_tab, textvariable=app.telegram_token_var, show="*", width=48).grid(row=1, column=1, sticky="ew", padx=(6, 0), pady=(6, 0))
    ttk.Label(tg_tab, text="Chat ID:").grid(row=2, column=0, sticky="w", pady=(6, 0))
    tk.Entry(tg_tab, textvariable=app.telegram_chat_id_var, width=24).grid(row=2, column=1, sticky="w", padx=(6, 0), pady=(6, 0))
    ttk.Button(tg_tab, text="Gửi thử", command=app._telegram_test).grid(row=2, column=2, sticky="e", padx=(8, 0), pady=(6, 0))

    ttk.Label(tg_tab, text="CA bundle (.pem/.crt):").grid(row=3, column=0, sticky="w", pady=(6, 0))
    tk.Entry(tg_tab, textvariable=app.telegram_ca_path_var).grid(row=3, column=1, sticky="ew", padx=(6, 0), pady=(6, 0))
    ttk.Button(tg_tab, text="Chọn…", command=app._pick_ca_bundle).grid(row=3, column=2, sticky="e", padx=(8, 0), pady=(6, 0))
    ttk.Checkbutton(tg_tab, text="Bỏ qua kiểm tra chứng chỉ (KHÔNG KHUYẾN NGHỊ)",
                    variable=app.telegram_skip_verify_var).grid(row=4, column=0, columnspan=3, sticky="w", pady=(6, 0))

    mt5_tab = ttk.Frame(opts_nb, padding=8)
    opts_nb.add(mt5_tab, text="MT5")
    mt5_tab.columnconfigure(1, weight=1)

    ttk.Checkbutton(mt5_tab, text="Bật lấy dữ liệu nến từ MT5 và đưa vào phân tích",
                    variable=app.mt5_enabled_var).grid(row=0, column=0, columnspan=3, sticky="w")
    ttk.Label(mt5_tab, text="MT5 terminal (tùy chọn):").grid(row=1, column=0, sticky="w", pady=(6, 0))
    tk.Entry(mt5_tab, textvariable=app.mt5_term_path_var).grid(row=1, column=1, sticky="ew", padx=(6, 0), pady=(6, 0))
    ttk.Button(mt5_tab, text="Chọn…", command=app._pick_mt5_terminal).grid(row=1, column=2, sticky="e", padx=(8, 0), pady=(6, 0))
    ttk.Label(mt5_tab, text="Symbol:").grid(row=2, column=0, sticky="w", pady=(6, 0))
    tk.Entry(mt5_tab, textvariable=app.mt5_symbol_var, width=18).grid(row=2, column=1, sticky="w", padx=(6, 0), pady=(6, 0))
    ttk.Button(mt5_tab, text="Tự nhận từ tên ảnh", command=app._mt5_guess_symbol).grid(row=2, column=2, sticky="e", padx=(8, 0), pady=(6, 0))

    rowc = ttk.Frame(mt5_tab)
    rowc.grid(row=3, column=0, columnspan=3, sticky="w", pady=(6, 0))
    ttk.Label(rowc, text="Số nến:").pack(side="left")
    ttk.Label(rowc, text="M1").pack(side="left", padx=(10, 2))
    ttk.Spinbox(rowc, from_=30, to=2000, textvariable=app.mt5_n_M1, width=6).pack(side="left")
    ttk.Label(rowc, text="M5").pack(side="left", padx=(10, 2))
    ttk.Spinbox(rowc, from_=30, to=2000, textvariable=app.mt5_n_M5, width=6).pack(side="left")
    ttk.Label(rowc, text="M15").pack(side="left", padx=(10, 2))
    ttk.Spinbox(rowc, from_=20, to=2000, textvariable=app.mt5_n_M15, width=6).pack(side="left")
    ttk.Label(rowc, text="H1").pack(side="left", padx=(10, 2))
    ttk.Spinbox(rowc, from_=20, to=2000, textvariable=app.mt5_n_H1, width=6).pack(side="left")

    btns_mt5 = ttk.Frame(mt5_tab)
    btns_mt5.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(6, 0))
    btns_mt5.columnconfigure(0, weight=1)
    btns_mt5.columnconfigure(1, weight=1)
    ttk.Button(btns_mt5, text="Kết nối/kiểm tra MT5", command=app._mt5_connect).grid(row=0, column=0, sticky="ew")
    ttk.Button(btns_mt5, text="Chụp snapshot ngay", command=app._mt5_snapshot_popup).grid(row=0, column=1, sticky="ew", padx=(6, 0))

    ttk.Label(mt5_tab, textvariable=app.mt5_status_var, foreground="#555").grid(row=5, column=0, columnspan=3, sticky="w", pady=(6, 0))

    auto_card = ttk.LabelFrame(mt5_tab, text="Auto-Trade khi có Thiết lập xác suất cao", padding=8)
    auto_card.grid(row=6, column=0, columnspan=3, sticky="ew", pady=(8, 0))
    r0 = ttk.Frame(auto_card); r0.grid(row=0, column=0, columnspan=3, sticky="w")
    ttk.Checkbutton(r0, text="Bật Auto-Trade", variable=app.auto_trade_enabled_var).pack(side="left")
    ttk.Checkbutton(r0, text="KHÔNG trade nếu NGƯỢC bias H1", variable=app.trade_strict_bias_var).pack(side="left", padx=(12,0))

    r1 = ttk.Frame(auto_card); r1.grid(row=1, column=0, columnspan=3, sticky="w", pady=(6,0))
    ttk.Label(r1, text="Khối lượng:").pack(side="left")
    ttk.Radiobutton(r1, text="Lots cố định", value="lots", variable=app.trade_size_mode_var).pack(side="left", padx=(6,0))
    ttk.Radiobutton(r1, text="% Equity", value="percent", variable=app.trade_size_mode_var).pack(side="left", padx=(6,0))
    ttk.Radiobutton(r1, text="Tiền rủi ro", value="money", variable=app.trade_size_mode_var).pack(side="left", padx=(6,0))

    r2 = ttk.Frame(auto_card); r2.grid(row=2, column=0, columnspan=3, sticky="w", pady=(4,0))
    ttk.Label(r2, text="Lots:").pack(side="left")
    ttk.Spinbox(r2, from_=0.01, to=100.0, increment=0.01, textvariable=app.trade_lots_total_var, width=8).pack(side="left", padx=(6,12))
    ttk.Label(r2, text="% Equity rủi ro:").pack(side="left")
    ttk.Spinbox(r2, from_=0.1, to=10.0, increment=0.1, textvariable=app.trade_equity_risk_pct_var, width=6).pack(side="left", padx=(6,12))
    ttk.Label(r2, text="Tiền rủi ro:").pack(side="left")
    ttk.Spinbox(r2, from_=1.0, to=1_000_000.0, increment=1.0, textvariable=app.trade_money_risk_var, width=10).pack(side="left", padx=(6,12))

    r3 = ttk.Frame(auto_card); r3.grid(row=3, column=0, columnspan=3, sticky="w", pady=(4,0))
    ttk.Label(r3, text="Chia TP1 (%):").pack(side="left")
    ttk.Spinbox(r3, from_=1, to=99, textvariable=app.trade_split_tp1_pct_var, width=6).pack(side="left", padx=(6,12))
    ttk.Label(r3, text="Deviation (points):").pack(side="left")
    ttk.Spinbox(r3, from_=5, to=200, textvariable=app.trade_deviation_points_var, width=6).pack(side="left", padx=(6,12))
    ttk.Label(r3, text="Ngưỡng pending (points):").pack(side="left")
    ttk.Spinbox(r3, from_=5, to=2000, textvariable=app.trade_pending_threshold_points_var, width=8).pack(side="left", padx=(6,12))

    r4 = ttk.Frame(auto_card); r4.grid(row=4, column=0, columnspan=3, sticky="w", pady=(4,0))
    ttk.Label(r4, text="Magic:").pack(side="left")
    ttk.Spinbox(r4, from_=1, to=2_147_000_000, textvariable=app.trade_magic_var, width=12).pack(side="left", padx=(6,12))
    ttk.Label(r4, text="Comment:").pack(side="left")
    tk.Entry(r4, textvariable=app.trade_comment_prefix_var, width=18).pack(side="left", padx=(6,0))

    r5 = ttk.Frame(auto_card); r5.grid(row=5, column=0, columnspan=3, sticky="w", pady=(4,0))
    ttk.Checkbutton(r5, text="Dry-run (không gửi lệnh)", variable=app.auto_trade_dry_run_var).pack(side="left")
    ttk.Checkbutton(r5, text="Pending theo ATR", variable=app.trade_dynamic_pending_var).pack(side="left", padx=(12,0))
    ttk.Checkbutton(r5, text="BE sau TP1", variable=app.trade_move_to_be_after_tp1_var).pack(side="left", padx=(12,0))

    r6 = ttk.Frame(auto_card); r6.grid(row=6, column=0, columnspan=3, sticky="w", pady=(4,0))
    ttk.Label(r6, text="TTL pending (phút):").pack(side="left")
    ttk.Spinbox(r6, from_=1, to=1440, textvariable=app.trade_pending_ttl_min_var, width=6).pack(side="left", padx=(6,12))
    ttk.Label(r6, text="RR tối thiểu TP2:").pack(side="left")
    ttk.Spinbox(r6, from_=1.0, to=10.0, increment=0.1, textvariable=app.trade_min_rr_tp2_var, width=6).pack(side="left", padx=(6,12))
    ttk.Label(r6, text="Khoảng cách key lvl (pips):").pack(side="left")
    ttk.Spinbox(r6, from_=0.0, to=200.0, increment=0.5, textvariable=app.trade_min_dist_keylvl_pips_var, width=8).pack(side="left", padx=(6,12))
    ttk.Label(r6, text="Cooldown (phút):").pack(side="left")
    ttk.Spinbox(r6, from_=0, to=360, textvariable=app.trade_cooldown_min_var, width=6).pack(side="left", padx=(6,12))

    r7 = ttk.Frame(auto_card); r7.grid(row=7, column=0, columnspan=3, sticky="w", pady=(4,0))
    ttk.Label(r7, text="Trailing ATR ×").pack(side="left")
    ttk.Spinbox(r7, from_=0.1, to=3.0, increment=0.1, textvariable=app.trade_trailing_atr_mult_var, width=6).pack(side="left", padx=(6,12))

    r8 = ttk.Frame(auto_card); r8.grid(row=8, column=0, columnspan=3, sticky="w", pady=(4,0))
    ttk.Label(r8, text="Phiên cho phép:").pack(side="left")
    ttk.Checkbutton(r8, text="Asia",   variable=app.trade_allow_session_asia_var).pack(side="left", padx=(6,0))
    ttk.Checkbutton(r8, text="London", variable=app.trade_allow_session_london_var).pack(side="left", padx=(6,0))
    ttk.Checkbutton(r8, text="New York", variable=app.trade_allow_session_ny_var).pack(side="left", padx=(6,0))

    r9 = ttk.Frame(auto_card); r9.grid(row=9, column=0, columnspan=3, sticky="w", pady=(4,0))
    ttk.Label(r9, text="Chặn quanh news:").pack(side="left")
    ttk.Label(r9, text="Trước (phút):").pack(side="left", padx=(8,2))
    ttk.Spinbox(r9, from_=0, to=180, textvariable=app.trade_news_block_before_min_var, width=6).pack(side="left")
    ttk.Label(r9, text="Sau (phút):").pack(side="left", padx=(8,2))
    ttk.Spinbox(r9, from_=0, to=180, textvariable=app.trade_news_block_after_min_var, width=6).pack(side="left")
    ttk.Label(r9, text="Nguồn: Forex Factory (High)").pack(side="left", padx=(12,0))

    norun_tab = ttk.Frame(opts_nb, padding=8)
    opts_nb.add(norun_tab, text="No Run")
    norun_tab.columnconfigure(0, weight=1)
    card_norun = ttk.LabelFrame(norun_tab, text="Điều kiện không chạy phân tích tự động", padding=8)
    card_norun.grid(row=0, column=0, sticky="ew")
    ttk.Checkbutton(card_norun, text="Không chạy vào Thứ 7 và Chủ Nhật",
                    variable=app.norun_weekend_var).grid(row=0, column=0, sticky="w")
    ttk.Checkbutton(card_norun, text="Chỉ chạy trong thời gian Kill Zone",
                    variable=app.norun_killzone_var).grid(row=1, column=0, sticky="w", pady=(4, 0))

    ws_tab = ttk.Frame(opts_nb, padding=8)
    opts_nb.add(ws_tab, text="Workspace")
    for i in range(3):
        ws_tab.columnconfigure(i, weight=1)
    ttk.Button(ws_tab, text="Lưu workspace", command=app._save_workspace).grid(row=0, column=0, sticky="ew")
    ttk.Button(ws_tab, text="Khôi phục", command=app._load_workspace).grid(row=0, column=1, sticky="ew", padx=6)
    ttk.Button(ws_tab, text="Xoá workspace", command=app._delete_workspace).grid(row=0, column=2, sticky="ew")

def toggle_api_visibility(app):
    app.api_entry.configure(show="" if app.api_entry.cget("show") == "*" else "*")
