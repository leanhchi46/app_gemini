from __future__ import annotations
import time
import json
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TYPE_CHECKING

# These imports are necessary for the worker function
import google.generativeai as genai
from google.api_core import exceptions
from . import uploader, no_run, no_trade, auto_trade, report_parser, news, json_saver, md_saver
from .constants import APP_DIR

if TYPE_CHECKING:
    from ..gemini_batch_image_analyzer import GeminiFolderOnceApp
    from .config import RunConfig


def run_analysis_worker(app: "GeminiFolderOnceApp", prompt_no_entry: str, prompt_entry_run: str, model_name: str, cfg: "RunConfig"):
    """
    This is the main analysis worker thread. It handles image uploading,
    context building, Gemini API calls, and post-processing actions.
    Moved from the main app class for better code organization.
    """
    def _tnow():
        return time.perf_counter()

    def _gen_with_retry(_model, _parts, tries=5, base_delay=2.0):
        last = None
        for i in range(tries):
            try:
                return _model.generate_content(_parts, request_options={"timeout": 1200})
            except exceptions.ResourceExhausted as e:
                last = e
                wait_time = base_delay * (2 ** i)
                print(f"Warning: ResourceExhausted error. Retrying in {wait_time:.2f} seconds...")
                time.sleep(wait_time)
                if i == tries - 1:
                    raise
            except Exception as e:
                last = e
                if i == tries - 1:
                    raise
                time.sleep(base_delay)
                base_delay *= 1.7
        raise last

    paths = [r["path"] for r in app.results]
    names = [r["name"] for r in app.results]
    max_files = max(0, int(cfg.max_files))
    if max_files > 0 and len(paths) > max_files:
        paths, names = paths[:max_files], names[:max_files]
    total_imgs = len(paths)
    if total_imgs == 0:
        app.ui_status("Không có ảnh để phân tích.")
        app._enqueue(app._finalize_stopped)
        return

    try:
        model = genai.GenerativeModel(model_name=model_name)
    except Exception as e:
        app.ui_message("error", "Model", str(e))
        app._enqueue(app._finalize_stopped)
        return

    uploaded_files = []
    file_slots     = [None] * len(paths)
    combined_text  = ""
    early_exit     = False

    try:
        # ==================================================================
        # == CHECK 1: NO-RUN CONDITIONS (WEEKEND, KILLZONE, ETC.)
        # ==================================================================
        try:
            should_run, reason = no_run.check_no_run_conditions(app)
            if not should_run:
                app.ui_status(reason)
                app._log_trade_decision({
                    "stage": "no-run-skip",
                    "t": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "reason": reason
                }, folder_override=(app.mt5_symbol_var.get().strip() or None))
                
                app._quick_be_trailing_sweep(cfg)
                raise SystemExit
        except Exception as e:
            app.ui_status(f"Lỗi kiểm tra No-Run: {e}")

        t_up0 = _tnow()
        cache = uploader.UploadCache.load() if cfg.cache_enabled else {}

        prepared_map = {}
        to_upload = []
        for i, (p, n) in enumerate(zip(paths, names)):
            cached_remote = uploader.UploadCache.lookup(cache, p) if cache else ""
            if cached_remote:
                try:
                    f = genai.get_file(cached_remote)
                    if getattr(getattr(f, "state", None), "name", None) == "ACTIVE":
                        file_slots[i] = f
                        prepared_map[i] = None
                        continue
                except Exception:
                    pass
            upath = uploader.prepare_image(p, optimize=bool(cfg.optimize_lossless), app_dir=APP_DIR)
            to_upload.append((i, p, n, upath))
            prepared_map[i] = upath

        if cfg.only_generate_if_changed and len(to_upload) == 0 and all(file_slots):
            plan = None
            composed = ""
            context_block = ""
            try:
                composed = app.compose_context(cfg, budget_chars=max(800, int(cfg.ctx_limit))) or ""
                if composed:
                    try:
                        _obj = json.loads(composed)
                        plan = (_obj.get("CONTEXT_COMPOSED") or {}).get("latest_plan")
                    except Exception:
                        plan = None
                    context_block = "\n\n[CONTEXT_COMPOSED]\n" + composed
            except Exception:
                composed = ""
                plan = None
                context_block = ""

            mt5_ctx_text = app._mt5_build_context(plan=plan, cfg=cfg) if cfg.mt5_enabled else ""
            text = "Ảnh không đổi so với lần gần nhất."
            if context_block:
                text += "\n\n" + context_block
            if mt5_ctx_text:
                text += "\n\n[PHỤ LỤC_MT5_JSON]\n" + mt5_ctx_text

            app.combined_report_text = text
            app.ui_detail_replace(text)
            _ = md_saver.save_md_report(app, text, cfg)
            app.ui_refresh_history_list()

            try:
                mt5_dict_cache = {}
                if mt5_ctx_text:
                    try:
                        mt5_dict_cache = json.loads(mt5_ctx_text).get("MT5_DATA", {})
                    except Exception:
                        mt5_dict_cache = {}
                if mt5_dict_cache:
                    auto_trade.mt5_manage_be_trailing(app,mt5_dict_cache, cfg)
            except Exception:
                pass
            early_exit = True
            raise SystemExit

        for (i, p, n, upath) in to_upload:
            app.results[i]["status"] = "Đang upload..."
            app._update_tree_row(i, "Đang upload...")

        if to_upload:
            max_workers = max(1, min(len(to_upload), int(cfg.upload_workers)))
            with ThreadPoolExecutor(max_workers=max_workers) as ex:
                futs = {
                    ex.submit(uploader.upload_one_file_for_worker, (p, n, upath)): (i, p)
                    for (i, p, n, upath) in to_upload
                }
                done_cnt = 0
                steps_upload   = len(to_upload)
                steps_process  = 1
                total_steps    = steps_upload + steps_process + 1

                for fut in as_completed(futs):
                    if app.stop_flag:
                        for f_cancel in futs:
                            try:
                                f_cancel.cancel()
                            except Exception:
                                pass
                        app._quick_be_trailing_sweep(cfg)
                        early_exit = True
                        raise SystemExit

                    (p_ret, fobj) = fut.result()
                    i, p = futs[fut]
                    file_slots[i] = fobj
                    uploaded_files.append((fobj, p))

                    done_cnt += 1
                    app._update_progress(done_cnt, total_steps)

                    app.results[i]["status"] = "Đã upload"
                    app._update_tree_row(i, "Đã upload")

            app.ui_status(f"Upload xong trong {(_tnow()-t_up0):.2f}s")
        else:
            steps_upload   = 0
            steps_process  = 1
            total_steps    = steps_upload + steps_process + 1

        if cfg.cache_enabled:
            for (f, p) in uploaded_files:
                try:
                    uploader.UploadCache.put(cache, p, f.name)
                except Exception:
                    pass
            uploader.UploadCache.save(cache)

        if app.stop_flag:
            app._quick_be_trailing_sweep(cfg)
            early_exit = True
            raise SystemExit

        all_media = []
        for i in range(len(paths)):
            f = file_slots[i]
            if f is None:
                all_media.append(uploader.as_inline_media_part(prepared_map.get(i) or paths[i]))
            else:
                all_media.append(uploader.file_or_inline_for_model(
                    f,
                    prepared_map.get(i),
                    paths[i]
                ))

        t_ctx0 = _tnow()
        plan = None
        composed = ""
        context_block = ""
        try:
            composed = app.compose_context(cfg, budget_chars=max(800, int(cfg.ctx_limit))) or ""
            if composed:
                try:
                    _obj = json.loads(composed)
                    plan = (_obj.get("CONTEXT_COMPOSED") or {}).get("latest_plan")
                except Exception:
                    plan = None
                context_block = "\n\n[CONTEXT_COMPOSED]\n" + composed
        except Exception:
            composed = ""
            plan = None
            context_block = ""

        # The _mt5_build_context function now returns a SafeMT5Data object directly
        safe_mt5_data = app._mt5_build_context(plan=plan, cfg=cfg) if cfg.mt5_enabled else None
        mt5_dict = (safe_mt5_data.raw if safe_mt5_data and safe_mt5_data.raw else {})
        mt5_json_full = json.dumps({"MT5_DATA": mt5_dict}, ensure_ascii=False) if mt5_dict else ""
        
        # --- Dynamic Prompt Selection (inside worker) ---
        # MODIFIED: Load Vision-based prompts directly.
        prompt = ""
        try:
            if cfg.mt5_enabled and safe_mt5_data and safe_mt5_data.raw and safe_mt5_data.raw.get("positions"):
                prompt_path = APP_DIR / "prompt_entry_run_vision.txt"
                prompt = prompt_path.read_text(encoding="utf-8")
                app.ui_status("Worker: Lệnh đang mở, dùng prompt Vision Quản Lý Lệnh.")
            else:
                prompt_path = APP_DIR / "prompt_no_entry_vision.txt"
                prompt = prompt_path.read_text(encoding="utf-8")
                app.ui_status("Worker: Không có lệnh mở, dùng prompt Vision Tìm Lệnh Mới.")
        except Exception as e:
             app.ui_status(f"Lỗi đọc prompt: {e}")
             # Fallback to old prompts if new ones fail
             if cfg.mt5_enabled and safe_mt5_data and safe_mt5_data.raw.get("positions"):
                prompt = prompt_entry_run
             else:
                prompt = prompt_no_entry
        # --- End Dynamic Prompt Selection ---
        
        # --- Inject News Analysis into MT5_DATA ---
        if mt5_dict:
            try:
                app._refresh_news_cache(ttl=300, async_fetch=False, cfg=cfg)
                
                # Check if currently inside a news window
                is_in_window, reason = news.is_within_news_window(
                    events=app.ff_cache_events_local,
                    symbol=cfg.mt5_symbol,
                    minutes_before=cfg.nt_news_before_mins,
                    minutes_after=cfg.nt_news_after_mins,
                )
                
                # Get next upcoming events
                upcoming = news.next_events_for_symbol(
                    events=app.ff_cache_events_local,
                    symbol=cfg.mt5_symbol,
                    limit=3
                )
                
                mt5_dict["news_analysis"] = {
                    "is_in_news_window": is_in_window,
                    "reason": reason,
                    "upcoming_events": upcoming
                }
            except Exception:
                # Ensure the key exists even if the process fails
                mt5_dict["news_analysis"] = {
                    "is_in_news_window": False, "reason": "News check failed", "upcoming_events": []
                }

        app.ui_status(f"Context+MT5 xong trong {(_tnow()-t_ctx0):.2f}s")

        if cfg.nt_enabled and mt5_dict:
            try:
                app._refresh_news_cache(ttl=300, async_fetch=False, cfg=cfg)
            except Exception:
                pass
            ok, reasons, app.ff_cache_events_local, app.ff_cache_fetch_time, meta = no_trade.evaluate(
                safe_mt5_data,
                cfg,
                cache_events=app.ff_cache_events_local,
                cache_fetch_time=app.ff_cache_fetch_time,
                ttl_sec=300,
            )
            try:
                app.last_no_trade_ok = bool(ok)
                app.last_no_trade_reasons = list(reasons or [])
            except Exception:
                pass
            if not ok:
                try:
                    app._log_trade_decision({
                        "stage": "no-trade",
                        "t": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "reasons": reasons
                    }, folder_override=(app.mt5_symbol_var.get().strip() or None))
                except Exception:
                    pass
                note = "NO-TRADE: Điều kiện giao dịch không thỏa.\n- " + "\n- ".join(reasons)
                if context_block:
                    note += "\n\n" + context_block
                if mt5_json_full:
                    note += "\n\n[PHỤ LỤC_MT5_JSON]\n" + mt5_json_full
                app.combined_report_text = note
                app.ui_detail_replace(note)
                _ = app._auto_save_report(note, cfg)
                app.ui_refresh_history_list()

                try:
                    if mt5_dict:
                        auto_trade.mt5_manage_be_trailing(app,mt5_dict, cfg)
                except Exception:
                    pass
                early_exit = True
                raise SystemExit

        app.ui_status("Đang phân tích toàn bộ thư mục...")
        try:
            tf_section = app._build_timeframe_section([Path(p).name for p in paths]).strip()

            parts_text = []
            if tf_section:
                parts_text.append("### Nhãn khung thời gian (tự nhận từ tên tệp)\n")
                parts_text.append(tf_section)
                parts_text.append("\n\n")
            parts_text.append(prompt)
            # --- Integration of report_parser ---
            # MODIFIED: Generate structured data and inject it into the Vision prompt
            if mt5_dict:
                # The mt5_dict is already parsed from mt5_json_full earlier
                structured_report = report_parser.parse_mt5_data_to_report(safe_mt5_data)
                # Inject the generated data tables into the prompt template
                prompt = prompt.replace(
                    "[Dữ liệu từ `CONCEPT_VALUE_TABLE` và `EXTRACT_JSON` sẽ được chèn vào đây]",
                    "DỮ LIỆU SỐ THAM KHẢO:\n" + structured_report
                )
                # Inject the historical context block if it exists
                if context_block:
                    prompt = prompt.replace(
                        "[Dữ liệu từ `CONTEXT_COMPOSED` sẽ được chèn vào đây]",
                        "DỮ LIỆU LỊCH SỬ (VÒNG TRƯỚC):\n" + context_block
                    )
                else:
                    # Remove the placeholder if there is no historical context
                    prompt = prompt.replace(
                        "**DỮ LIỆU LỊCH SỬ (NẾU CÓ):**\n[Dữ liệu từ `CONTEXT_COMPOSED` sẽ được chèn vào đây]",
                        ""
                    )
                
                # Clear parts_text and add the fully constructed prompt
                parts_text = [prompt]
            else:
                 # Fallback if MT5 data is missing
                parts_text.append(prompt)
                if mt5_json_full:
                    parts_text.append("\n\n[PHỤ LỤC_MT5_JSON]\n")
                    parts_text.append(mt5_json_full)

            # Remove any duplicate prompts that might have been added before
            prompt_final = "".join(list(dict.fromkeys(parts_text)))

            t_llm0 = _tnow()
            parts = all_media + [prompt_final]
            resp = _gen_with_retry(model, parts)

            combined_text = (getattr(resp, "text", "") or "").strip() or "[Không có nội dung trả về]"
            app.ui_status(f"Model trả lời trong {(_tnow()-t_llm0):.2f}s")

            app._update_progress(steps_upload + steps_process, steps_upload + steps_process + 1)

        except Exception as e:
            import traceback
            tb_str = traceback.format_exc()
            app.ui_status(f"Lỗi nghiêm trọng trong worker: {e}")
            combined_text = f"[LỖI PHÂN TÍCH] Đã xảy ra lỗi ở giai đoạn gọi model AI.\n\nChi tiết: {e}\n\nTraceback:\n{tb_str}"

        for p in paths:
            idx_real = next((i for i, r in enumerate(app.results) if r["path"] == p), None)
            if idx_real is not None:
                app.results[idx_real]["status"] = "Hoàn tất"
                app.results[idx_real]["text"] = ""
                app._update_tree_row(idx_real, "Hoàn tất")

        app.combined_report_text = combined_text
        app.ui_detail_replace(combined_text)

        saved_path = md_saver.save_md_report(app, combined_text, cfg)
        try:
            # Pass the composed context to the saving function so it can be logged
            # alongside the proposed trade.
            context_obj = json.loads(composed) if composed else {}
            json_saver.save_json_report(app, combined_text, cfg, names, context_obj)
        except Exception as e:
            app.ui_status(f"Lỗi khi lưu ctx_*.json: {e}")
            # We pass here so the main flow is not interrupted, but the error is now visible.
            pass
        app.ui_refresh_history_list()
        app.ui_refresh_json_list()

        if not app.stop_flag and not early_exit:
            try:
                app._maybe_notify_telegram(combined_text, saved_path, cfg)
            except Exception:
                pass
            try:
                auto_trade.auto_trade_if_high_prob(app,combined_text, mt5_dict, cfg)
            except Exception as e:
                app.ui_status(f"Auto-Trade lỗi: {e}")

            try:
                if mt5_dict:
                    auto_trade.mt5_manage_be_trailing(app,mt5_dict, cfg)
            except Exception:
                pass

        app._update_progress(steps_upload + steps_process + 1, steps_upload + steps_process + 1)

    except SystemExit:
        pass
    except Exception as e:
        app.ui_message("error", "Lỗi", str(e))

    finally:
        if not cfg.cache_enabled and cfg.delete_after:
            for uf, _ in uploaded_files:
                try:
                    app._maybe_delete(uf)
                except Exception:
                    pass
        app._enqueue(app._finalize_done if not app.stop_flag else app._finalize_stopped)
