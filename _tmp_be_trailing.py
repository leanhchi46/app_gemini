    def _mt5_manage_be_trailing(self, mt5_ctx: dict, cfg: RunConfig):
        """
        Mục đích: Tương tác với MetaTrader 5 (kết nối, lấy dữ liệu nến, tính toán chỉ số, snapshot...).
        Tham số:
          - mt5_ctx: dict — (tự suy luận theo ngữ cảnh sử dụng).
          - cfg: RunConfig — (tự suy luận theo ngữ cảnh sử dụng).
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        if not (cfg.mt5_enabled and mt5 and cfg.auto_trade_enabled):
            return
        try:
            info = mt5.account_info()
            if not info:
                return
            magic = int(cfg.trade_magic)

            atr = None
            point = None
            try:
                point = float(((mt5_ctx.get("info") or {}).get("point")) or 0.0)
                atr = (((mt5_ctx.get("volatility") or {}).get("ATR") or {}).get("M5"))
            except Exception:
                pass
            atr_pts = (atr / point) if (atr and point) else None
            atr_mult = float(cfg.trade_trailing_atr_mult or 0.0)

            positions = mt5.positions_get()
            if not positions:
                return

            from datetime import timedelta
            now = datetime.now()
            deals = mt5.history_deals_get(now - timedelta(days=2), now) or []
            tp1_closed = set()
            for d in deals:
                try:
                    if int(getattr(d, "magic", 0)) == magic and "-TP1" in str(getattr(d, "comment", "")):
                        tp1_closed.add((getattr(d, "symbol", ""), int(getattr(d, "position_id", 0))))
                except Exception:
                    pass

            for p in positions:
                try:
                    if int(p.magic) != magic:
                        continue
                    if "-TP2" not in p.comment:
                        continue
                    sym = p.symbol
                    entry = float(p.price_open)
                    sl    = float(p.sl) if p.sl else None
                    pos_id = int(p.ticket)

                    tick = mt5.symbol_info_tick(sym)
                    if not tick:
                        continue
                    bid = float(getattr(tick, "bid", 0.0))
                    ask = float(getattr(tick, "ask", 0.0))
                    cur = ask if p.type == mt5.POSITION_TYPE_BUY else bid
                    if not cur:
                        continue

                    move_to_be = False
                    if cfg.trade_move_to_be_after_tp1:

                        if (sym, pos_id) in tp1_closed:
                            move_to_be = True
                        else:

                            if sl is not None and point:
                                half = abs(entry - sl) * 0.5
                                if (p.type == mt5.POSITION_TYPE_BUY and cur - entry >= half) or\
                                (p.type == mt5.POSITION_TYPE_SELL and entry - cur >= half):
                                    move_to_be = True

                    new_sl = sl
                    if move_to_be:

                        buf = (point * 2)
                        new_sl = entry - buf if p.type == mt5.POSITION_TYPE_BUY else entry + buf

                    if atr_pts and atr_mult > 0 and point:
                        trail = atr_pts * atr_mult * point
                        if p.type == mt5.POSITION_TYPE_BUY:
                            cand = cur - trail
                            if new_sl is None or cand > new_sl:
                                new_sl = cand
                        else:
                            cand = cur + trail
                            if new_sl is None or cand < new_sl:
                                new_sl = cand

                    if new_sl and (sl is None or abs(new_sl - sl) > point*1.5):

                        req = dict(action=mt5.TRADE_ACTION_SLTP, position=pos_id, symbol=sym,
                                sl=round(new_sl, mt5.symbol_info(sym).digits),
                                tp=p.tp)
                        _ = self._order_send_safe(req, retry=2)
                except Exception:
                    continue
        except Exception:
            pass

    def _maybe_delete(self, uploaded_file):
        """
        Mục đích: Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
        Tham số:
          - uploaded_file — (tự suy luận theo ngữ cảnh sử dụng).
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        try:
            genai.delete_file(uploaded_file.name)
        except Exception:
            pass

    def _update_progress(self, done_steps, total_steps):
        """
        Mục đích: Cập nhật UI theo cơ chế thread-safe (hàng đợi, status, progress, khu vực chi tiết).
        Tham số:
          - done_steps — (tự suy luận theo ngữ cảnh sử dụng).
          - total_steps — (tự suy luận theo ngữ cảnh sử dụng).
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        pct = (done_steps / max(total_steps, 1)) * 100.0
        self._enqueue(lambda: (self.progress_var.set(pct), self.status_var.set(f"Tiến độ: {pct:.1f}%")))

    def _update_tree_row(self, idx, status):
        """
        Mục đích: Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
        Tham số:
          - idx — (tự suy luận theo ngữ cảnh sử dụng).
          - status — (tự suy luận theo ngữ cảnh sử dụng).
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        def action():
            """
            Mục đích: Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
            Tham số: (không)
            Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
            Ghi chú:
              - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
            """
            iid = str(idx)
            if self.tree.exists(iid):
                vals = list(self.tree.item(iid, "values"))
                vals = [idx + 1, self.results[idx]["name"], status] if len(vals) < 3 else [vals[0], vals[1], status]
                self.tree.item(iid, values=vals)
        self._enqueue(action)

    def _finalize_done(self):

        """
        Mục đích: Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
        Tham số: (không)
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        try:
            self._log_trade_decision({
                "stage": "run-end",
                "t": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }, folder_override=(self.mt5_symbol_var.get().strip() or None))
        except Exception:
            pass

        self.is_running = False
        self.stop_flag = False
        self.stop_btn.configure(state="disabled")
        self.export_btn.configure(state="normal")
        self.ui_status("Đã hoàn tất phân tích toàn bộ thư mục.")
        self._schedule_next_autorun()

    def _finalize_stopped(self):
        """
        Mục đích: Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
        Tham số: (không)
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        self.is_running = False
        self.stop_flag = False
        self.stop_btn.configure(state="disabled")
        self.export_btn.configure(state="normal")
        self.ui_status("Đã dừng.")
        self._schedule_next_autorun()

    def _on_tree_select(self, _evt):
        """
        Mục đích: Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
        Tham số:
          - _evt — (tự suy luận theo ngữ cảnh sử dụng).
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        self.detail_text.delete("1.0", "end")
        if self.combined_report_text.strip():
            self.detail_text.insert("1.0", self.combined_report_text)
        else:
            self.detail_text.insert("1.0", "Chưa có báo cáo. Hãy bấm 'Bắt đầu'.")

    def export_markdown(self):
        """
        Mục đích: Ghi/Xuất dữ liệu (báo cáo .md, JSON tóm tắt, cache...).
        Tham số: (không)
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        report_text = self.combined_report_text or ""
        folder = self.folder_path.get()
        files = [r["name"] for r in self.results if r.get("path")]
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        md = [
            f"# Báo cáo phân tích toàn bộ thư mục",
            f"- Thời gian: {ts}",
            f"- Model: {self.model_var.get()}",
            f"- Thư mục: {folder}",
            f"- Số ảnh: {len(files)}",
            "",
            "## Danh sách ảnh",
        ]
        md += [f"- {name}" for name in files]
        md += ["", "## Kết quả phân tích tổng hợp", report_text or "_(trống)_"]
        out_path = filedialog.asksaveasfilename(
            title="Lưu báo cáo Markdown",
            defaultextension=".md",
            filetypes=[("Markdown", "*.md")],
            initialfile="bao_cao_gemini_folder.md",
        )
        if not out_path:
            return
        try:
            Path(out_path).write_text("\n".join(md), encoding="utf-8")
            self.ui_message("info", "Thành công", f"Đã lưu: {out_path}")
        except Exception as e:
            self.ui_message("error", "Lỗi ghi file", str(e))

    def _auto_save_report(self, combined_text: str, cfg: RunConfig) -> Path:
        """
        Mục đích: Ghi/Xuất dữ liệu (báo cáo .md, JSON tóm tắt, cache...).
        Tham số:
          - combined_text: str — (tự suy luận theo ngữ cảnh sử dụng).
          - cfg: RunConfig — (tự suy luận theo ngữ cảnh sử dụng).
        Trả về: Path
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        d = self._get_reports_dir(cfg.folder)
        if not d:
            return None
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = d / f"report_{ts}.md"
        out.write_text(combined_text or "", encoding="utf-8")
        return out

    def clear_results(self):
        """
        Mục đích: Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
        Tham số: (không)
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        self.results.clear()
        self.combined_report_text = ""
        if hasattr(self, "tree"):
            self.tree.delete(*self.tree.get_children())
        if hasattr(self, "detail_text"):
            self.ui_detail_replace("Báo cáo tổng hợp sẽ hiển thị tại đây sau khi phân tích.")
        self.ui_progress(0)
        self.ui_status("Đã xoá kết quả khỏi giao diện.")

    def _enqueue(self, func):
        """
        Mục đích: Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
        Tham số:
          - func — (tự suy luận theo ngữ cảnh sử dụng).
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        self.ui_queue.put(func)

    def ui_status(self, text: str):

        """
        Mục đích: Cập nhật UI theo cơ chế thread-safe (hàng đợi, status, progress, khu vực chi tiết).
        Tham số:
          - text: str — (tự suy luận theo ngữ cảnh sử dụng).
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        self._enqueue(lambda: self.status_var.set(text))

    def ui_detail_replace(self, text: str):
        """
        Mục đích: Cập nhật UI theo cơ chế thread-safe (hàng đợi, status, progress, khu vực chi tiết).
        Tham số:
          - text: str — (tự suy luận theo ngữ cảnh sử dụng).
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        self._enqueue(lambda: (
            self.detail_text.config(state="normal"),
            self.detail_text.delete("1.0", "end"),
            self.detail_text.insert("1.0", text)
        ))

    def ui_message(self, kind: str, title: str, text: str, auto_close_ms: int = 60000, log: bool = True):
        """
        Mục đích: Cập nhật UI theo cơ chế thread-safe (hàng đợi, status, progress, khu vực chi tiết).
        Tham số:
          - kind: str — (tự suy luận theo ngữ cảnh sử dụng).
          - title: str — (tự suy luận theo ngữ cảnh sử dụng).
          - text: str — (tự suy luận theo ngữ cảnh sử dụng).
          - auto_close_ms: int — (tự suy luận theo ngữ cảnh sử dụng).
          - log: bool — (tự suy luận theo ngữ cảnh sử dụng).
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        def _show():

            """
            Mục đích: Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
            Tham số: (không)
            Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
            Ghi chú:
              - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
            """
            if log:
                try:
                    self._log_ui_message({"t": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                          "kind": kind, "title": title, "text": text})
                except Exception:
                    pass

            top = tk.Toplevel(self.root)
            try:
                top.transient(self.root)
            except Exception:
                pass
            top.resizable(False, False)
            top.title(title or {"info": "Thông báo", "warning": "Cảnh báo", "error": "Lỗi"}.get(kind, "Thông báo"))
            try:
                top.attributes("-topmost", True)
            except Exception:
                pass

            frm = ttk.Frame(top, padding=12)
            frm.pack(fill="both", expand=True)

            ttk.Label(frm, text=title or "", font=("TkDefaultFont", 10, "bold")).pack(anchor="w", pady=(0, 4))
            ttk.Label(frm, text=text or "", justify="left", wraplength=480).pack(anchor="w")
            ttk.Label(frm, text=f"Sẽ tự đóng trong {auto_close_ms//1000}s", foreground="#666").pack(anchor="w", pady=(8, 0))
            ttk.Button(frm, text="Đóng", command=top.destroy).pack(anchor="e", pady=(8, 0))

            try:
                top.update_idletasks()
                x = self.root.winfo_rootx() + self.root.winfo_width() - top.winfo_width() - 24
                y = self.root.winfo_rooty() + 24
                x = max(0, x); y = max(0, y)
                top.geometry(f"+{x}+{y}")

                def _drop_topmost():
                    """
                    Mục đích: Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
                    Tham số: (không)
                    Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
                    Ghi chú:
                      - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
                    """
                    try: top.attributes("-topmost", False)
                    except Exception: pass
                top.after(200, _drop_topmost)
            except Exception:
                pass

            def _safe_destroy():
                """
                Mục đích: Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
                Tham số: (không)
                Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
                Ghi chú:
                  - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
                """
                try: top.destroy()
                except Exception: pass
            top.after(max(1000, int(auto_close_ms)), _safe_destroy)

        self._enqueue(_show)

    def _log_ui_message(self, data: dict, folder_override: str | None = None):
        """
        Mục đích: Cập nhật UI theo cơ chế thread-safe (hàng đợi, status, progress, khu vực chi tiết).
        Tham số:
          - data: dict — (tự suy luận theo ngữ cảnh sử dụng).
          - folder_override: str | None — (tự suy luận theo ngữ cảnh sử dụng).
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        try:
            d = self._get_reports_dir(folder_override=folder_override)
            if not d:
                d = APP_DIR / "Logs"
                d.mkdir(parents=True, exist_ok=True)

            p = d / f"ui_log_{datetime.now().strftime('%Y%m%d')}.jsonl"
            line = (json.dumps(data, ensure_ascii=False, separators=(',', ':')) + "\n").encode("utf-8")

            p.parent.mkdir(parents=True, exist_ok=True)
            with self._ui_log_lock:
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

    def ui_widget_state(self, widget, state: str):
        """
        Mục đích: Cập nhật UI theo cơ chế thread-safe (hàng đợi, status, progress, khu vực chi tiết).
        Tham số:
          - widget — (tự suy luận theo ngữ cảnh sử dụng).
          - state: str — (tự suy luận theo ngữ cảnh sử dụng).
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        self._enqueue(lambda: widget.configure(state=state))

    def ui_progress(self, pct: float, status: str = None):
        """
        Mục đích: Cập nhật UI theo cơ chế thread-safe (hàng đợi, status, progress, khu vực chi tiết).
        Tham số:
          - pct: float — (tự suy luận theo ngữ cảnh sử dụng).
          - status: str — (tự suy luận theo ngữ cảnh sử dụng).
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        def _act():
            """
            Mục đích: Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
            Tham số: (không)
            Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
            Ghi chú:
              - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
            """
            self.progress_var.set(pct)
            if status is not None:
                self.status_var.set(status)
        self._enqueue(_act)

    def ui_detail_clear(self, placeholder: str = None):
        """
        Mục đích: Cập nhật UI theo cơ chế thread-safe (hàng đợi, status, progress, khu vực chi tiết).
        Tham số:
          - placeholder: str — (tự suy luận theo ngữ cảnh sử dụng).
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        self._enqueue(lambda: (
            self.detail_text.delete("1.0", "end"),
            self.detail_text.insert("1.0", placeholder or "")
        ))

    def ui_refresh_history_list(self):
        """
        Mục đích: Cập nhật UI theo cơ chế thread-safe (hàng đợi, status, progress, khu vực chi tiết).
        Tham số: (không)
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        self._enqueue(self._refresh_history_list)

    def ui_refresh_json_list(self):
        """
        Mục đích: Cập nhật UI theo cơ chế thread-safe (hàng đợi, status, progress, khu vực chi tiết).
        Tham số: (không)
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        self._enqueue(self._refresh_json_list)

    def _poll_ui_queue(self):
        """
        Mục đích: Cập nhật UI theo cơ chế thread-safe (hàng đợi, status, progress, khu vực chi tiết).
        Tham số: (không)
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        try:
            while True:
                func = self.ui_queue.get_nowait()
                try:
                    func()
                except Exception:
                    pass
        except queue.Empty:
            pass
        self.root.after(80, self._poll_ui_queue)

    def ui_set_var(self, tk_var, value):
        """
        Mục đích: Cập nhật UI theo cơ chế thread-safe (hàng đợi, status, progress, khu vực chi tiết).
        Tham số:
          - tk_var — (tự suy luận theo ngữ cảnh sử dụng).
          - value — (tự suy luận theo ngữ cảnh sử dụng).
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        self._enqueue(lambda v=tk_var, val=value: v.set(val))

    def ui_set_text(self, widget, text: str):
        """
        Mục đích: Cập nhật UI theo cơ chế thread-safe (hàng đợi, status, progress, khu vực chi tiết).
        Tham số:
          - widget — (tự suy luận theo ngữ cảnh sử dụng).
          - text: str — (tự suy luận theo ngữ cảnh sử dụng).
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        self._enqueue(lambda w=widget, t=text: (
            w.config(state="normal"),
            w.delete("1.0", "end"),
            w.insert("1.0", t)
        ))

    def _refresh_history_list(self):
        """
        Mục đích: Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
        Tham số: (không)
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        if not hasattr(self, "history_list"):
            return
        self.history_list.delete(0, "end")
        d = self._get_reports_dir()
        files = sorted(d.glob("report_*.md"), reverse=True) if d else []
        self._history_files = list(files)
        for p in files:
            self.history_list.insert("end", p.name)

    def _preview_history_selected(self):
        """
        Mục đích: Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
        Tham số: (không)
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        sel = getattr(self, "history_list", None).curselection() if hasattr(self, "history_list") else None
        if not sel:
            return
        p = self._history_files[sel[0]]
        try:
            txt = p.read_text(encoding="utf-8", errors="ignore")
            self.detail_text.config(state="normal")
            self.detail_text.delete("1.0", "end")
            self.detail_text.insert("1.0", txt)
            self.ui_status(f"Xem: {p.name}")
        except Exception as e:
            self.ui_message("error", "History", str(e))

    def _open_history_selected(self):
        """
        Mục đích: Làm việc với file/thư mục (chọn, nạp, xem trước, xoá, cập nhật danh sách).
        Tham số: (không)
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        sel = self.history_list.curselection()
        if not sel:
            return
        p = self._history_files[sel[0]]
        try:
            self._open_path(p)
        except Exception as e:
            self.ui_message("error", "History", str(e))

    def _delete_history_selected(self):
        """
        Mục đích: Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
        Tham số: (không)
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        sel = self.history_list.curselection()
        if not sel:
            return
        p = self._history_files[sel[0]]
        try:
            p.unlink()
            self._refresh_history_list()
            self.detail_text.delete("1.0", "end")
        except Exception as e:
            self.ui_message("error", "History", str(e))

    def _open_reports_folder(self):
        """
        Mục đích: Làm việc với file/thư mục (chọn, nạp, xem trước, xoá, cập nhật danh sách).
        Tham số: (không)
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        d = self._get_reports_dir()
        if d:
            self._open_path(d)

    def _refresh_json_list(self):
        """
        Mục đích: Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
        Tham số: (không)
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        if not hasattr(self, "json_list"):
            return
        self.json_list.delete(0, "end")
        d = self._get_reports_dir()
        files = sorted(d.glob("ctx_*.json"), reverse=True) if d else []
        self.json_files = list(files)
        for p in files:
            self.json_list.insert("end", p.name)

    def _preview_json_selected(self):
        """
        Mục đích: Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
        Tham số: (không)
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        sel = getattr(self, "json_list", None).curselection() if hasattr(self, "json_list") else None
        if not sel:
            return
        p = self.json_files[sel[0]]
        try:
            txt = p.read_text(encoding="utf-8", errors="ignore")
            self.detail_text.config(state="normal")
            self.detail_text.delete("1.0", "end")
            self.detail_text.insert("1.0", txt)
            self.ui_status(f"Xem JSON: {p.name}")
        except Exception as e:
            self.ui_message("error", "JSON", str(e))

    def _load_json_selected(self):
        """
        Mục đích: Làm việc với file/thư mục (chọn, nạp, xem trước, xoá, cập nhật danh sách).
        Tham số: (không)
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        sel = self.json_list.curselection()
        if not sel:
            return
        p = self.json_files[sel[0]]
        try:
            self._open_path(p)
        except Exception as e:
            self.ui_message("error", "JSON", str(e))

    def _delete_json_selected(self):
        """
        Mục đích: Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
        Tham số: (không)
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        sel = self.json_list.curselection()
        if not sel:
            return
        p = self.json_files[sel[0]]
        try:
            p.unlink()
            self._refresh_json_list()
            self.detail_text.delete("1.0", "end")
        except Exception as e:
            self.ui_message("error", "JSON", str(e))

    def _open_json_folder(self):
        """
        Mục đích: Làm việc với file/thư mục (chọn, nạp, xem trước, xoá, cập nhật danh sách).
        Tham số: (không)
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        d = self._get_reports_dir()
        if d:
            self._open_path(d)

    def _detect_timeframe_from_name(self, name: str) -> str:
        """
        Mục đích: Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
        Tham số:
          - name: str — (tự suy luận theo ngữ cảnh sử dụng).
        Trả về: str
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        s = Path(name).stem.lower()

        patterns = [
            ("MN1", r"(?<![a-z0-9])(?:mn1|1mo|monthly)(?![a-z0-9])"),
            ("W1",  r"(?<![a-z0-9])(?:w1|1w|weekly)(?![a-z0-9])"),
            ("D1",  r"(?<![a-z0-9])(?:d1|1d|daily)(?![a-z0-9])"),
            ("H4",  r"(?<![a-z0-9])(?:h4|4h)(?![a-z0-9])"),
            ("H1",  r"(?<![a-z0-9])(?:h1|1h)(?![a-z0-9])"),
            ("M30", r"(?<![a-z0-9])(?:m30|30m)(?![a-z0-9])"),
            ("M15", r"(?<![a-z0-9])(?:m15|15m)(?![a-z0-9])"),
            ("M5",  r"(?<![a-z0-9])(?:m5|5m)(?![a-z0-9])"),

            ("M1",  r"(?<![a-z0-9])(?:m1|1m)(?![a-z0-9])"),
        ]

        for tf, pat in patterns:
            if re.search(pat, s):
                return tf
        return "?"

    def _build_timeframe_section(self, names):
        """
        Mục đích: Khởi tạo/cấu hình thành phần giao diện hoặc cấu trúc dữ liệu nội bộ.
        Tham số:
          - names — (tự suy luận theo ngữ cảnh sử dụng).
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        lines = []
        for n in names:
            tf = self._detect_timeframe_from_name(n)
            lines.append(f"- {n} ⇒ {tf}")
        return "\n".join(lines)

    def _toggle_autorun(self):
        """
        Mục đích: Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
        Tham số: (không)
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        if self.autorun_var.get():
            self._schedule_next_autorun()
        else:
            if self._autorun_job:
                self.root.after_cancel(self._autorun_job)
                self._autorun_job = None
            self.ui_status("Đã tắt auto-run.")

    def _autorun_interval_changed(self):
        """
        Mục đích: Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
        Tham số: (không)
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        if self.autorun_var.get():
            self._schedule_next_autorun()

    def _schedule_next_autorun(self):
        """
        Mục đích: Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
        Tham số: (không)
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        if not self.autorun_var.get():
            return
        if self._autorun_job:
            self.root.after_cancel(self._autorun_job)
        secs = max(5, int(self.autorun_seconds_var.get()))
        self._autorun_job = self.root.after(secs * 1000, self._autorun_tick)
        self.ui_status(f"Tự động chạy sau {secs}s.")

    def _autorun_tick(self):
        """
        Mục đích: Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
        Tham số: (không)
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        self._autorun_job = None
        if not self.is_running:
            self.start_analysis()
        else:

            if self.mt5_enabled_var.get() and self.auto_trade_enabled_var.get():

                cfg_snapshot = self._snapshot_config()
                def _sweep(c):
                    """
                    Mục đích: Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
                    Tham số:
                      - c — (tự suy luận theo ngữ cảnh sử dụng).
                    Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
                    Ghi chú:
                      - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
                    """
                    try:
                        ctx = self._mt5_build_context(plan=None, cfg=c) or ""
                        if ctx:
                            data = json.loads(ctx).get("MT5_DATA", {})
                            if data:
                                self._mt5_manage_be_trailing(data, c)
                    except Exception:
                        pass
                threading.Thread(target=_sweep, args=(cfg_snapshot,), daemon=True).start()
            self._schedule_next_autorun()

    def _pick_mt5_terminal(self):
        """
        Mục đích: Tương tác với MetaTrader 5 (kết nối, lấy dữ liệu nến, tính toán chỉ số, snapshot...).
        Tham số: (không)
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        p = filedialog.askopenfilename(
            title="Chọn terminal64.exe hoặc terminal.exe",
            filetypes=[("MT5 terminal", "terminal*.exe"), ("Tất cả", "*.*")],
        )
        if p:
            self.mt5_term_path_var.set(p)

    def _mt5_guess_symbol(self):
        """
        Mục đích: Tương tác với MetaTrader 5 (kết nối, lấy dữ liệu nến, tính toán chỉ số, snapshot...).
        Tham số: (không)
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        try:
            tfs = {"M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1", "MN1"}
            names = [r["name"] for r in self.results]
            cands = []
            for n in names:
                base = Path(n).stem
                parts = base.split("_")
                if len(parts) >= 2 and parts[-1].upper() in tfs:
                    cands.append("_".join(parts[:-1]))
            if not cands:
                for n in names:
                    s = Path(n).stem
                    head = "".join([ch for ch in s if ch.isalpha()])
                    if head:
                        cands.append(head)
            if cands:
                from collections import Counter
                self.mt5_symbol_var.set(Counter(cands).most_common(1)[0][0])
                self.ui_status(f"Đã đoán symbol: {self.mt5_symbol_var.get()}")
            else:
                self.ui_message("info", "MT5", "Không đoán được symbol từ tên file.")
        except Exception:
            pass

    def _mt5_connect(self):
        """
        Mục đích: Tương tác với MetaTrader 5 (kết nối, lấy dữ liệu nến, tính toán chỉ số, snapshot...).
        Tham số: (không)
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        if mt5 is None:
            self.ui_message("error", "MT5", "Chưa cài thư viện MetaTrader5.\nHãy chạy: pip install MetaTrader5")
            return
        term = self.mt5_term_path_var.get().strip() or None
        try:
            ok = mt5.initialize(path=term) if term else mt5.initialize()
            self.mt5_initialized = bool(ok)
            if not ok:
                err = f"MT5: initialize() thất bại: {mt5.last_error()}"
                self._enqueue(lambda: self.mt5_status_var.set(err))
                self.ui_message("error", "MT5", f"initialize() lỗi: {mt5.last_error()}")
            else:
                v = mt5.version()
                self._enqueue(lambda: self.mt5_status_var.set(f"MT5: đã kết nối (build {v[0]})"))
                self.ui_message("info", "MT5", "Kết nối thành công.")
        except Exception as e:
            self._enqueue(lambda: self.mt5_status_var.set(f"MT5: lỗi kết nối: {e}"))
            self.ui_message("error", "MT5", f"Lỗi kết nối: {e}")

    def _mt5_build_context(self, plan=None, cfg: RunConfig | None = None):
        """
        Mục đích: Tương tác với MetaTrader 5 (kết nối, lấy dữ liệu nến, tính toán chỉ số, snapshot...).
        Tham số:
          - plan — (tự suy luận theo ngữ cảnh sử dụng).
          - cfg: RunConfig | None — (tự suy luận theo ngữ cảnh sử dụng).
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        sym = (cfg.mt5_symbol if cfg else (self.mt5_symbol_var.get() or "").strip())
        if not ((cfg.mt5_enabled if cfg else self.mt5_enabled_var.get()) and sym) or mt5 is None:
            return ""
        if not self.mt5_initialized:
            self._mt5_connect()
            if not self.mt5_initialized:
                return ""

        # Delegate to mt5_utils for building the MT5 context JSON
        try:
            return mt5_utils.build_context(
                sym,
                n_m1=(cfg.mt5_n_M1 if cfg else int(self.mt5_n_M1.get())),
                n_m5=(cfg.mt5_n_M5 if cfg else int(self.mt5_n_M5.get())),
                n_m15=(cfg.mt5_n_M15 if cfg else int(self.mt5_n_M15.get())),
                n_h1=(cfg.mt5_n_H1 if cfg else int(self.mt5_n_H1.get())),
                plan=plan,
                return_json=True,
            ) or ""
        except Exception:
            return ""

    def _mt5_snapshot_popup(self):
        """
        Mục đích: Tương tác với MetaTrader 5 (kết nối, lấy dữ liệu nến, tính toán chỉ số, snapshot...).
        Tham số: (không)
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        txt = self._mt5_build_context(plan=None)
        if not txt:
            self.ui_message("warning", "MT5", "Không thể lấy dữ liệu. Kiểm tra kết nối/biểu tượng (Symbol).")
            return
        win = tk.Toplevel(self.root)
        win.title("MT5 snapshot")
        win.geometry("760x520")
        st = ScrolledText(win, wrap="none")
        st.pack(fill="both", expand=True)
        st.insert("1.0", txt)

    def _extract_text_from_obj(self, obj):
        """
        Mục đích: Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
        Tham số:
          - obj — (tự suy luận theo ngữ cảnh sử dụng).
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        parts = []

        def walk(x):
            """
            Mục đích: Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
            Tham số:
              - x — (tự suy luận theo ngữ cảnh sử dụng).
            Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
            Ghi chú:
              - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
            """
            if isinstance(x, str):
                parts.append(x)
                return
            if isinstance(x, dict):

                for k in ("text", "content", "prompt", "body", "value"):
                    v = x.get(k)
                    if isinstance(v, str) and v.strip():
                        parts.append(v)
                for v in x.values():
                    if v is not None and not isinstance(v, str):
                        walk(v)
            elif isinstance(x, list):
                for v in x:
                    walk(v)

        walk(obj)
        text = "\n\n".join(t.strip() for t in parts if t and t.strip())

        if text and text.count("") > 0 and text.count("\n") <= text.count(""):
            text = (text.replace("", "\n")
                        .replace("\\t", "\t")
                        .replace('\\"', '"')
                        .replace("\\'", "'"))
        return text or json.dumps(obj, ensure_ascii=False, indent=2)

    def _normalize_prompt_text(self, raw: str) -> str:
        """
        Mục đích: Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
        Tham số:
          - raw: str — (tự suy luận theo ngữ cảnh sử dụng).
        Trả về: str
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        s = raw.strip()

        try:
            obj = json.loads(s)
            return self._extract_text_from_obj(obj)
        except Exception:
            pass

        try:
            obj = ast.literal_eval(s)
            return self._extract_text_from_obj(obj)
        except Exception:
            pass

        if s.count("") >= 3 and s.count("\n") <= s.count(""):
            s = (s.replace("", "\n")
                 .replace("\\t", "\t")
                 .replace('\\"', '"')
                 .replace("\\'", "'"))
        return s

    def _reformat_prompt_area(self):
        """
        Mục đích: Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
        Tham số: (không)
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        raw = self.prompt_text.get("1.0", "end")
        pretty = self._normalize_prompt_text(raw)
        self.prompt_text.delete("1.0", "end")
        self.prompt_text.insert("1.0", pretty)

    def _find_prompt_file(self):
        """
        Mục đích: Làm việc với file/thư mục (chọn, nạp, xem trước, xoá, cập nhật danh sách).
        Tham số: (không)
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        cand = []
        pfp = self.prompt_file_path_var.get().strip()
        if pfp:
            cand.append(Path(pfp))
        folder = self.folder_path.get().strip()
        if folder:
            for name in ("PROMPT.txt", "Prompt.txt", "prompt.txt"):
                cand.append(Path(folder) / name)
        cand.append(APP_DIR / "PROMPT.txt")
        for p in cand:
            try:
                if p and p.exists() and p.is_file():
                    return p
            except Exception:
                pass
        return None

    def _load_prompt_from_file(self, path=None, silent=False):
        """
        Mục đích: Làm việc với file/thư mục (chọn, nạp, xem trước, xoá, cập nhật danh sách).
        Tham số:
          - path — (tự suy luận theo ngữ cảnh sử dụng).
          - silent — (tự suy luận theo ngữ cảnh sử dụng).
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        try:
            p = Path(path) if path else self._find_prompt_file()
            if not p:
                if not silent:
                    self.ui_message("warning", "Prompt", "Không tìm thấy PROMPT.txt trong thư mục đã chọn hoặc APP_DIR.")
                return False
            raw = p.read_text(encoding="utf-8", errors="ignore")
            text = self._normalize_prompt_text(raw)
            self.prompt_text.delete("1.0", "end")
            self.prompt_text.insert("1.0", text)
            self.prompt_file_path_var.set(str(p))
            self.ui_status(f"Đã nạp prompt từ: {p.name}")
            return True
        except Exception as e:
            if not silent:
                self.ui_message("error", "Prompt", f"Lỗi nạp PROMPT.txt: {e}")
            return False

    def _pick_prompt_file(self):
        """
        Mục đích: Làm việc với file/thư mục (chọn, nạp, xem trước, xoá, cập nhật danh sách).
        Tham số: (không)
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        path = filedialog.askopenfilename(
            title="Chọn PROMPT.txt",
            filetypes=[("Text", "*.txt"), ("Tất cả", "*.*")]
        )
        if not path:
            return
        self._load_prompt_from_file(path)

    def _auto_load_prompt_for_current_folder(self):
        """
        Mục đích: Làm việc với file/thư mục (chọn, nạp, xem trước, xoá, cập nhật danh sách).
        Tham số: (không)
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        if self.auto_load_prompt_txt_var.get():
            self._load_prompt_from_file(silent=True)

    def _save_workspace(self):
        """
        Mục đích: Ghi/Xuất dữ liệu (báo cáo .md, JSON tóm tắt, cache...).
        Tham số: (không)
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        data = {
            "prompt_file_path": self.prompt_file_path_var.get().strip(),
            "auto_load_prompt_txt": bool(self.auto_load_prompt_txt_var.get()),
            "folder_path": self.folder_path.get().strip(),
            "model": self.model_var.get(),
            "delete_after": bool(self.delete_after_var.get()),
            "max_files": int(self.max_files_var.get()),
            "autorun": bool(self.autorun_var.get()),
            "autorun_secs": int(self.autorun_seconds_var.get()),
            "remember_ctx": bool(self.remember_context_var.get()),
            "ctx_n_reports": int(self.context_n_reports_var.get()),
            "ctx_limit_chars": int(self.context_limit_chars_var.get()),
            "create_ctx_json": bool(self.create_ctx_json_var.get()),
            "prefer_ctx_json": bool(self.prefer_ctx_json_var.get()),
            "ctx_json_n": int(self.ctx_json_n_var.get()),

            "telegram_enabled": bool(self.telegram_enabled_var.get()),
            "telegram_token_enc": obfuscate_text(self.telegram_token_var.get().strip())
            if self.telegram_token_var.get().strip()
            else "",
            "telegram_chat_id": self.telegram_chat_id_var.get().strip(),
            "telegram_skip_verify": bool(self.telegram_skip_verify_var.get()),
            "telegram_ca_path": self.telegram_ca_path_var.get().strip(),

            "mt5_enabled": bool(self.mt5_enabled_var.get()),
            "mt5_term_path": self.mt5_term_path_var.get().strip(),
            "mt5_symbol": self.mt5_symbol_var.get().strip(),
            "mt5_n_M1": int(self.mt5_n_M1.get()),
            "mt5_n_M5": int(self.mt5_n_M5.get()),
            "mt5_n_M15": int(self.mt5_n_M15.get()),
            "mt5_n_H1": int(self.mt5_n_H1.get()),

            "no_trade_enabled": bool(self.no_trade_enabled_var.get()),
            "nt_spread_factor": float(self.nt_spread_factor_var.get()),
            "nt_min_atr_m5_pips": float(self.nt_min_atr_m5_pips_var.get()),
            "nt_min_ticks_per_min": int(self.nt_min_ticks_per_min_var.get()),

            "upload_workers": int(self.upload_workers_var.get()),
            "cache_enabled": bool(self.cache_enabled_var.get()),
            "opt_lossless": bool(self.optimize_lossless_var.get()),
            "only_generate_if_changed": bool(self.only_generate_if_changed_var.get()),

            "auto_trade_enabled": bool(self.auto_trade_enabled_var.get()),
            "trade_strict_bias": bool(self.trade_strict_bias_var.get()),
            "trade_size_mode": self.trade_size_mode_var.get(),
            "trade_lots_total": float(self.trade_lots_total_var.get()),
            "trade_equity_risk_pct": float(self.trade_equity_risk_pct_var.get()),
            "trade_money_risk": float(self.trade_money_risk_var.get()),
            "trade_split_tp1_pct": int(self.trade_split_tp1_pct_var.get()),
            "trade_deviation_points": int(self.trade_deviation_points_var.get()),
            "trade_pending_threshold_points": int(self.trade_pending_threshold_points_var.get()),
            "trade_magic": int(self.trade_magic_var.get()),
            "trade_comment_prefix": self.trade_comment_prefix_var.get(),

            "trade_pending_ttl_min": int(self.trade_pending_ttl_min_var.get()),
            "trade_min_rr_tp2": float(self.trade_min_rr_tp2_var.get()),
            "trade_min_dist_keylvl_pips": float(self.trade_min_dist_keylvl_pips_var.get()),
            "trade_cooldown_min": int(self.trade_cooldown_min_var.get()),
            "trade_dynamic_pending": bool(self.trade_dynamic_pending_var.get()),
            "auto_trade_dry_run": bool(self.auto_trade_dry_run_var.get()),
            "trade_move_to_be_after_tp1": bool(self.trade_move_to_be_after_tp1_var.get()),
            "trade_trailing_atr_mult": float(self.trade_trailing_atr_mult_var.get()),
            "trade_allow_session_asia": bool(self.trade_allow_session_asia_var.get()),
            "trade_allow_session_london": bool(self.trade_allow_session_london_var.get()),
            "trade_allow_session_ny": bool(self.trade_allow_session_ny_var.get()),
            "news_block_before_min": int(self.trade_news_block_before_min_var.get()),
            "news_block_after_min": int(self.trade_news_block_after_min_var.get()),

        }
        try:
            WORKSPACE_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            self.ui_message("info", "Workspace", "Đã lưu workspace.")
        except Exception as e:
            self.ui_message("error", "Workspace", str(e))

    def _load_workspace(self):
        """
        Mục đích: Làm việc với file/thư mục (chọn, nạp, xem trước, xoá, cập nhật danh sách).
        Tham số: (không)
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        if not WORKSPACE_JSON.exists():
            return
        try:
            data = json.loads(WORKSPACE_JSON.read_text(encoding="utf-8"))
        except Exception:
            return

        self.prompt_file_path_var.set(data.get("prompt_file_path", ""))
        self.auto_load_prompt_txt_var.set(bool(data.get("auto_load_prompt_txt", True)))
        folder = data.get("folder_path", "")
        if folder and Path(folder).exists():
            self.folder_path.set(folder)
            self._load_files(folder)
            self._refresh_history_list()
            self._refresh_json_list()

        self.model_var.set(data.get("model", DEFAULT_MODEL))
        self.delete_after_var.set(bool(data.get("delete_after", True)))
        self.max_files_var.set(int(data.get("max_files", 0)))
        self.autorun_var.set(bool(data.get("autorun", False)))
        self.autorun_seconds_var.set(int(data.get("autorun_secs", 60)))

        self.remember_context_var.set(bool(data.get("remember_ctx", True)))
        self.context_n_reports_var.set(int(data.get("ctx_n_reports", 1)))
        self.context_limit_chars_var.set(int(data.get("ctx_limit_chars", 2000)))
        self.create_ctx_json_var.set(bool(data.get("create_ctx_json", True)))
        self.prefer_ctx_json_var.set(bool(data.get("prefer_ctx_json", True)))
        self.ctx_json_n_var.set(int(data.get("ctx_json_n", 5)))

        self.telegram_enabled_var.set(bool(data.get("telegram_enabled", False)))
        self.telegram_token_var.set(deobfuscate_text(data.get("telegram_token_enc", "")))
        self.telegram_chat_id_var.set(data.get("telegram_chat_id", ""))
        self.telegram_skip_verify_var.set(bool(data.get("telegram_skip_verify", False)))
        self.telegram_ca_path_var.set(data.get("telegram_ca_path", ""))

        self.mt5_enabled_var.set(bool(data.get("mt5_enabled", False)))
        self.mt5_term_path_var.set(data.get("mt5_term_path", ""))
        self.mt5_symbol_var.set(data.get("mt5_symbol", ""))
        self.mt5_n_M1.set(int(data.get("mt5_n_M1", 120)))
        self.mt5_n_M5.set(int(data.get("mt5_n_M5", 180)))
        self.mt5_n_M15.set(int(data.get("mt5_n_M15", 96)))
        self.mt5_n_H1.set(int(data.get("mt5_n_H1", 120)))

        self.no_trade_enabled_var.set(bool(data.get("no_trade_enabled", True)))
        self.nt_spread_factor_var.set(float(data.get("nt_spread_factor", 1.2)))
        self.nt_min_atr_m5_pips_var.set(float(data.get("nt_min_atr_m5_pips", 3.0)))
        self.nt_min_ticks_per_min_var.set(int(data.get("nt_min_ticks_per_min", 5)))

        self.upload_workers_var.set(int(data.get("upload_workers", 4)))
        self.cache_enabled_var.set(bool(data.get("cache_enabled", True)))
        self.optimize_lossless_var.set(bool(data.get("opt_lossless", False)))
        self.only_generate_if_changed_var.set(bool(data.get("only_generate_if_changed", False)))

        self.auto_trade_enabled_var.set(bool(data.get("auto_trade_enabled", False)))
        self.trade_strict_bias_var.set(bool(data.get("trade_strict_bias", True)))
        self.trade_size_mode_var.set(data.get("trade_size_mode", "lots"))
        self.trade_lots_total_var.set(float(data.get("trade_lots_total", 0.10)))
        self.trade_equity_risk_pct_var.set(float(data.get("trade_equity_risk_pct", 1.0)))
        self.trade_money_risk_var.set(float(data.get("trade_money_risk", 10.0)))
        self.trade_split_tp1_pct_var.set(int(data.get("trade_split_tp1_pct", 50)))
        self.trade_deviation_points_var.set(int(data.get("trade_deviation_points", 20)))
        self.trade_pending_threshold_points_var.set(int(data.get("trade_pending_threshold_points", 60)))
        self.trade_magic_var.set(int(data.get("trade_magic", 26092025)))
        self.trade_comment_prefix_var.set(data.get("trade_comment_prefix", "AI-ICT"))

        before_val = data.get("news_block_before_min")
        after_val  = data.get("news_block_after_min")
        legacy_val = data.get("trade_news_block_min")

        try:
            before = int(before_val) if before_val is not None else None
        except Exception:
            before = None
        try:
            after = int(after_val) if after_val is not None else None
        except Exception:
            after = None
        try:
            legacy = int(legacy_val) if legacy_val is not None else None
        except Exception:
            legacy = None

        if before is None and legacy is not None:
            before = legacy
        if after is None and legacy is not None:
            after = legacy

        if before is None:
            before = 15
        if after is None:
            after = 15

        self.trade_news_block_before_min_var.set(before)
        self.trade_news_block_after_min_var.set(after)

    def _delete_workspace(self):
        """
        Mục đích: Đọc/ghi cấu hình workspace, cache upload và các trạng thái phiên làm việc.
        Tham số: (không)
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        try:
            if WORKSPACE_JSON.exists():
                WORKSPACE_JSON.unlink()
            self.ui_message("info", "Workspace", "Đã xoá workspace.")
        except Exception as e:
            self.ui_message("error", "Workspace", str(e))

    def _load_workspace(self):
        """
        Mục đích: Làm việc với file/thư mục (chọn, nạp, xem trước, xoá, cập nhật danh sách).
        Tham số: (không)
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        if not WORKSPACE_JSON.exists():
            return
        try:
            data = json.loads(WORKSPACE_JSON.read_text(encoding="utf-8"))
        except Exception:
            return

        self.prompt_file_path_var.set(data.get("prompt_file_path", ""))
        self.auto_load_prompt_txt_var.set(bool(data.get("auto_load_prompt_txt", True)))
        folder = data.get("folder_path", "")
        if folder and Path(folder).exists():
            self.folder_path.set(folder)
            self._load_files(folder)
            self._refresh_history_list()
            self._refresh_json_list()

        self.model_var.set(data.get("model", DEFAULT_MODEL))
        self.delete_after_var.set(bool(data.get("delete_after", True)))
        self.max_files_var.set(int(data.get("max_files", 0)))
        self.autorun_var.set(bool(data.get("autorun", False)))
        self.autorun_seconds_var.set(int(data.get("autorun_secs", 60)))

        self.remember_context_var.set(bool(data.get("remember_ctx", True)))
        self.context_n_reports_var.set(int(data.get("ctx_n_reports", 1)))
        self.context_limit_chars_var.set(int(data.get("ctx_limit_chars", 2000)))
        self.create_ctx_json_var.set(bool(data.get("create_ctx_json", True)))
        self.prefer_ctx_json_var.set(bool(data.get("prefer_ctx_json", True)))
        self.ctx_json_n_var.set(int(data.get("ctx_json_n", 5)))

        self.telegram_enabled_var.set(bool(data.get("telegram_enabled", False)))
        self.telegram_token_var.set(deobfuscate_text(data.get("telegram_token_enc", "")))
        self.telegram_chat_id_var.set(data.get("telegram_chat_id", ""))
        self.telegram_skip_verify_var.set(bool(data.get("telegram_skip_verify", False)))
        self.telegram_ca_path_var.set(data.get("telegram_ca_path", ""))

        self.mt5_enabled_var.set(bool(data.get("mt5_enabled", False)))
        self.mt5_term_path_var.set(data.get("mt5_term_path", ""))
        self.mt5_symbol_var.set(data.get("mt5_symbol", ""))
        self.mt5_n_M1.set(int(data.get("mt5_n_M1", 120)))
        self.mt5_n_M5.set(int(data.get("mt5_n_M5", 180)))
        self.mt5_n_M15.set(int(data.get("mt5_n_M15", 96)))
        self.mt5_n_H1.set(int(data.get("mt5_n_H1", 120)))

        self.no_trade_enabled_var.set(bool(data.get("no_trade_enabled", True)))
        self.nt_spread_factor_var.set(float(data.get("nt_spread_factor", 1.2)))
        self.nt_min_atr_m5_pips_var.set(float(data.get("nt_min_atr_m5_pips", 3.0)))
        self.nt_min_ticks_per_min_var.set(int(data.get("nt_min_ticks_per_min", 5)))

        self.upload_workers_var.set(int(data.get("upload_workers", 4)))
        self.cache_enabled_var.set(bool(data.get("cache_enabled", True)))
        self.optimize_lossless_var.set(bool(data.get("opt_lossless", False)))
        self.only_generate_if_changed_var.set(bool(data.get("only_generate_if_changed", False)))

        self.auto_trade_enabled_var.set(bool(data.get("auto_trade_enabled", False)))
        self.trade_strict_bias_var.set(bool(data.get("trade_strict_bias", True)))
        self.trade_size_mode_var.set(data.get("trade_size_mode", "lots"))
        self.trade_lots_total_var.set(float(data.get("trade_lots_total", 0.10)))
        self.trade_equity_risk_pct_var.set(float(data.get("trade_equity_risk_pct", 1.0)))
        self.trade_money_risk_var.set(float(data.get("trade_money_risk", 10.0)))
        self.trade_split_tp1_pct_var.set(int(data.get("trade_split_tp1_pct", 50)))
        self.trade_deviation_points_var.set(int(data.get("trade_deviation_points", 20)))
        self.trade_pending_threshold_points_var.set(int(data.get("trade_pending_threshold_points", 60)))
        self.trade_magic_var.set(int(data.get("trade_magic", 26092025)))
        self.trade_comment_prefix_var.set(data.get("trade_comment_prefix", "AI-ICT"))

        before_val = data.get("news_block_before_min")
        after_val  = data.get("news_block_after_min")
        legacy_val = data.get("trade_news_block_min")

        try:
            before = int(before_val) if before_val is not None else None
        except Exception:
            before = None
        try:
            after = int(after_val) if after_val is not None else None
        except Exception:
            after = None
        try:
            legacy = int(legacy_val) if legacy_val is not None else None
        except Exception:
            legacy = None

        if before is None and legacy is not None:
            before = legacy
        if after is None and legacy is not None:
            after = legacy

        if before is None:
            before = 15
        if after is None:
            after = 15

        self.trade_news_block_before_min_var.set(before)
        self.trade_news_block_after_min_var.set(after)

    def _delete_workspace(self):
        """
        Mục đích: Đọc/ghi cấu hình workspace, cache upload và các trạng thái phiên làm việc.
        Tham số: (không)
        Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
        Ghi chú:
          - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
        """
        try:
            if WORKSPACE_JSON.exists():
                WORKSPACE_JSON.unlink()
            self.ui_message("info", "Workspace", "Đã xoá workspace.")
        except Exception as e:
            self.ui_message("error", "Workspace", str(e))

        # No periodic scheduling needed here; remove stray reference to undefined 'secs' and '_tick'.

def main():
    """
    Mục đích: Hàm/thủ tục tiện ích nội bộ phục vụ workflow tổng thể của ứng dụng.
    Tham số: (không)
    Trả về: None hoặc giá trị nội bộ tuỳ ngữ cảnh.
    Ghi chú:
      - Nên gọi trên main thread nếu tương tác trực tiếp với Tkinter; nếu từ worker thread thì sử dụng hàng đợi UI để tránh đụng độ.
    """
    root = tk.Tk()
    app = GeminiFolderOnceApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()



