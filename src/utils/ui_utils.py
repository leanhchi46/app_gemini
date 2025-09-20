from __future__ import annotations
import tkinter as tk
from tkinter import messagebox
from typing import TYPE_CHECKING
import queue
import json
import os
from datetime import datetime
from src.config.constants import APP_DIR

if TYPE_CHECKING:
    from scripts.tool import TradingToolApp

def _enqueue(app: "TradingToolApp", func):
    app.ui_queue.put(func)

def _log_status(app: "TradingToolApp", text: str):
    def _do_log():
        try:
            folder_override = app.mt5_symbol_var.get().strip() or None
            app._log_trade_decision({
                "stage": "status_update",
                "t": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "message": text
            }, folder_override=folder_override)
        except Exception:
            pass
    
    import threading
    threading.Thread(target=_do_log, daemon=True).start()

def ui_status(app: "TradingToolApp", text: str):
    _enqueue(app, lambda: app.status_var.set(text))
    _log_status(app, text)

def ui_detail_replace(app: "TradingToolApp", text: str):
    _enqueue(app, lambda: (
        app.detail_text.config(state="normal"),
        app.detail_text.delete("1.0", "end"),
        app.detail_text.insert("1.0", text),
        app.detail_text.see("end")
    ))

def ui_message(app: "TradingToolApp", kind: str, title: str, text: str):
    _enqueue(app, lambda: getattr(messagebox, f"show{kind}", messagebox.showinfo)(title, text))

def _log_ui_message(app: "TradingToolApp", data: dict, folder_override: str | None = None):
    try:
        d = app._get_reports_dir(folder_override=folder_override)
        if not d:
            d = APP_DIR / "Logs"
            d.mkdir(parents=True, exist_ok=True)

        p = d / f"ui_log_{datetime.now().strftime('%Y%m%d')}.jsonl"
        line = (json.dumps(data, ensure_ascii=False, separators=(',', ':')) + "\n").encode("utf-8")

        p.parent.mkdir(parents=True, exist_ok=True)
        with app._ui_log_lock:
            need_leading_newline = False
            if p.exists():
                try:
                    sz = p.stat().st_size
                    if sz > 0:
                        with open(p, "rb") as fr:
                            fr.seek(-1, os.SEEK_END)
                            need_leading_newline = (fr.read(1) != b"\n")
                except Exception:
                    need_leading_newline = False
            with open(p, "ab") as f:
                if need_leading_newline:
                    f.write(b"\n")
                f.write(line)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except Exception:
                    pass
    except Exception:
        pass

def ui_widget_state(app: "TradingToolApp", widget, state: str):
    _enqueue(app, lambda: widget.configure(state=state))

def ui_progress(app: "TradingToolApp", pct: float, status: str = None):
    def _act():
        app.progress_var.set(pct)
        if status is not None:
            app.status_var.set(status)
    _enqueue(app, _act)

def ui_detail_clear(app: "TradingToolApp", placeholder: str = None):
    _enqueue(app, lambda: (
        app.detail_text.delete("1.0", "end"),
        app.detail_text.insert("1.0", placeholder or "")
    ))

def ui_refresh_history_list(app: "TradingToolApp"):
    _enqueue(app, app._refresh_history_list)

def ui_refresh_json_list(app: "TradingToolApp"):
    _enqueue(app, app._refresh_json_list)

def _poll_ui_queue(app: "TradingToolApp"):
    try:
        while True:
            func = app.ui_queue.get_nowait()
            try:
                func()
            except Exception:
                pass
    except queue.Empty:
        pass
    app.root.after(80, lambda: _poll_ui_queue(app))

def ui_set_var(app: "TradingToolApp", tk_var, value):
    _enqueue(app, lambda v=tk_var, val=value: v.set(val))

def ui_set_text(app: "TradingToolApp", widget, text: str):
    _enqueue(app, lambda w=widget, t=text: (
        w.config(state="normal"),
        w.delete("1.0", "end"),
        w.insert("1.0", t)
    ))
