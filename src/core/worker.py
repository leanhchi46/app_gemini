from __future__ import annotations
import time
import json
import logging
import traceback
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TYPE_CHECKING, List, Dict, Any, Tuple

import google.generativeai as genai
from google.api_core import exceptions

from src.services import uploader
from src.core import no_run, no_trade, auto_trade, context_builder
from src.utils import report_parser, json_saver, md_saver, ui_utils
from src.services import news
from src.config.constants import APP_DIR

if TYPE_CHECKING:
    from scripts.tool import TradingToolApp
    from src.config.config import RunConfig
    from src.utils.safe_data import SafeMT5Data

# ==================================================================================
# HÀM TRỢ GIÚP (HELPER FUNCTIONS)
# ==================================================================================

def _tnow() -> float:
    """Trả về thời gian hiện tại với độ chính xác cao."""
    return time.perf_counter()

def _gen_stream_with_retry(_model: genai.GenerativeModel, _parts: List[Any], tries: int = 5, base_delay: float = 2.0) -> Any:
    """
    Tạo một generator để gọi API Gemini streaming với cơ chế thử lại (retry).
    Cơ chế này giúp tăng độ ổn định khi gặp lỗi tạm thời từ API.
    Sử dụng chiến lược exponential backoff: thời gian chờ tăng gấp đôi sau mỗi lần thất bại.
    """
    last_exception = None
    for i in range(tries):
        try:
            response_stream = _model.generate_content(_parts, stream=True, request_options={"timeout": 1200})
            for chunk in response_stream:
                yield chunk
            return  # Thoát khỏi hàm khi stream thành công
        except exceptions.ResourceExhausted as e:
            last_exception = e
            wait_time = base_delay * (2 ** i)
            print(f"Cảnh báo: Lỗi ResourceExhausted. Thử lại sau {wait_time:.2f} giây...")
            time.sleep(wait_time)
        except Exception as e:
            last_exception = e
            # Đối với các lỗi khác, tăng thời gian chờ một cách từ từ hơn
            time.sleep(base_delay)
            base_delay *= 1.7
        
        if i == tries - 1:
            raise last_exception # Ném ra lỗi cuối cùng nếu tất cả các lần thử đều thất bại

def _handle_no_change_scenario(app: "TradingToolApp", cfg: "RunConfig"):
    """
    Xử lý trường hợp không có ảnh nào thay đổi so với lần chạy trước.
    Sẽ tạo một báo cáo ngắn gọn, quản lý các lệnh đang chạy và thoát sớm.
    """
    app.ui_status("Ảnh không đổi, tạo báo cáo nhanh...")
    composed = app.compose_context(cfg, budget_chars=max(800, int(cfg.ctx_limit))) or ""
    plan = None
    if composed:
        try:
            _obj = json.loads(composed)
            plan = (_obj.get("CONTEXT_COMPOSED") or {}).get("latest_plan")
        except Exception:
            pass
    
    context_block = f"\n\n[CONTEXT_COMPOSED]\n{composed}" if composed else ""
    mt5_ctx_text = app._mt5_build_context(plan=plan, cfg=cfg) if cfg.mt5_enabled else ""
    
    report_text = "Ảnh không đổi so với lần gần nhất."
    if context_block:
        report_text += f"\n\n{context_block}"
    if mt5_ctx_text:
        report_text += f"\n\n[PHỤ LỤC_MT5_JSON]\n{mt5_ctx_text}"

    app.combined_report_text = report_text
    ui_utils.ui_detail_replace(app, report_text)
    md_saver.save_md_report(app, report_text, cfg)
    ui_utils.ui_refresh_history_list(app)

    # Vẫn kiểm tra và quản lý các lệnh BE/Trailing dù không phân tích lại
    if mt5_ctx_text:
        try:
            mt5_dict_cache = json.loads(mt5_ctx_text).get("MT5_DATA", {})
            if mt5_dict_cache:
                # auto_trade.mt5_manage_be_trailing(app, mt5_dict_cache, cfg) # Tạm thời vô hiệu hóa
                pass # Giữ khối lệnh hợp lệ sau khi comment
        except Exception as e:
            logging.warning(f"Lỗi khi quản lý BE/Trailing trong kịch bản không thay đổi: {e}")
            
    raise SystemExit # Dừng worker một cách có kiểm soát

def _upload_images_parallel(app: "TradingToolApp", cfg: "RunConfig", to_upload: List[Tuple]) -> Tuple[List, int]:
    """
    Upload các file ảnh song song và cho phép hủy bỏ các tác vụ đang chờ.
    Gán executor vào app.active_executor để luồng chính có thể truy cập và hủy.
    """
    uploaded_files = []
    file_slots = [None] * len(app.results)
    
    if not to_upload:
        return file_slots, 0

    max_workers = max(1, min(len(to_upload), int(cfg.upload_workers)))
    steps_upload = len(to_upload)
    total_steps = steps_upload + 2 # 1 cho xử lý context, 1 cho gọi AI

    try:
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            # Gán executor cho app để luồng chính có thể hủy
            app.active_executor = ex
            
            # Tạo một map từ future sang thông tin file để xử lý kết quả
            futs = {
                ex.submit(uploader.upload_one_file_for_worker, (p, n, upath)): (i, p)
                for (i, p, n, upath) in to_upload
            }

            done_cnt = 0
            for fut in as_completed(futs):
                if app.stop_flag:
                    # Không cần hủy future ở đây nữa vì stop_analysis đã làm
                    raise SystemExit("Người dùng đã dừng quá trình upload.")
                
                try:
                    (p_ret, fobj) = fut.result()
                    i, p = futs[fut]
                    file_slots[i] = fobj
                    uploaded_files.append((fobj, p))
                except Exception:
                    # Bỏ qua lỗi của các future đã bị hủy
                    if app.stop_flag:
                        continue
                    raise # Ném lại lỗi nếu không phải do người dùng dừng

                done_cnt += 1
                app._update_progress(done_cnt, total_steps)
                app.results[i]["status"] = "Đã upload"
                app._update_tree_row(i, "Đã upload")
    finally:
        # Dọn dẹp tham chiếu đến executor
        app.active_executor = None
            
    return file_slots, steps_upload

def _prepare_and_build_context(app: "TradingToolApp", cfg: "RunConfig") -> Tuple[SafeMT5Data, Dict, str, str]:
    """
    Xây dựng toàn bộ ngữ cảnh cần thiết để cung cấp cho model AI.
    Bao gồm: ngữ cảnh lịch sử, dữ liệu MT5, và phân tích tin tức.
    """
    # 1. Xây dựng ngữ cảnh lịch sử từ các lần chạy trước
    composed = app.compose_context(cfg, budget_chars=max(800, int(cfg.ctx_limit))) or ""
    plan = None
    if composed:
        try:
            _obj = json.loads(composed)
            plan = (_obj.get("CONTEXT_COMPOSED") or {}).get("latest_plan")
        except Exception:
            pass
    context_block = f"\n\n[CONTEXT_COMPOSED]\n{composed}" if composed else ""

    # 2. Lấy dữ liệu MT5 thời gian thực
    safe_mt5_data = app._mt5_build_context(plan=plan, cfg=cfg) if cfg.mt5_enabled else None
    mt5_dict = (safe_mt5_data.raw if safe_mt5_data and safe_mt5_data.raw else {})
    
    # 3. Làm giàu dữ liệu MT5 với phân tích tin tức
    if mt5_dict:
        try:
            app._refresh_news_cache(ttl=300, async_fetch=False, cfg=cfg)
            is_in_window, reason = news.is_within_news_window(
                events=app.ff_cache_events_local,
                symbol=cfg.mt5_symbol,
                minutes_before=cfg.nt_news_before_mins,
                minutes_after=cfg.nt_news_after_mins,
            )
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
        except Exception as e:
            logging.error(f"Lỗi khi phân tích tin tức: {e}")
            # Đảm bảo key luôn tồn tại để tránh lỗi downstream
            mt5_dict["news_analysis"] = {
                "is_in_news_window": False, "reason": "News check failed", "upcoming_events": []
            }
            
    mt5_json_full = json.dumps({"MT5_DATA": mt5_dict}, ensure_ascii=False) if mt5_dict else ""
    
    return safe_mt5_data, mt5_dict, context_block, mt5_json_full

def _select_prompt_dynamically(app: "TradingToolApp", cfg: "RunConfig", safe_mt5_data: SafeMT5Data, prompt_no_entry: str, prompt_entry_run: str) -> str:
    """
    Chọn prompt phù hợp dựa trên trạng thái giao dịch hiện tại (có lệnh đang mở hay không).
    """
    prompt_to_use = ""
    has_positions = cfg.mt5_enabled and safe_mt5_data and safe_mt5_data.raw and safe_mt5_data.raw.get("positions")
    
    try:
        if has_positions:
            prompt_path = APP_DIR / "prompt_entry_run_vision.txt"
            prompt_to_use = prompt_path.read_text(encoding="utf-8")
            app.ui_status("Worker: Lệnh đang mở, dùng prompt Vision Quản Lý Lệnh.")
        else:
            prompt_path = APP_DIR / "prompt_no_entry_vision.txt"
            prompt_to_use = prompt_path.read_text(encoding="utf-8")
            app.ui_status("Worker: Không có lệnh mở, dùng prompt Vision Tìm Lệnh Mới.")
    except Exception as e:
        app.ui_status(f"Lỗi đọc prompt từ file: {e}. Sử dụng prompt dự phòng.")
        # Cơ chế dự phòng: sử dụng prompt cũ nếu đọc file lỗi
        prompt_to_use = prompt_entry_run if has_positions else prompt_no_entry
        
    return prompt_to_use

def _construct_final_prompt(app: "TradingToolApp", prompt: str, mt5_dict: Dict, safe_mt5_data: SafeMT5Data, context_block: str, mt5_json_full: str, paths: List[str]) -> str:
    """
    Xây dựng nội dung prompt cuối cùng để gửi đến model AI.
    Tích hợp dữ liệu có cấu trúc từ MT5, ngữ cảnh lịch sử và thông tin timeframe.
    """
    # Bắt đầu với thông tin timeframe từ tên file
    tf_section = app._build_timeframe_section([Path(p).name for p in paths]).strip()
    parts_text = []
    if tf_section:
        parts_text.append(f"### Nhãn khung thời gian (tự nhận từ tên tệp)\n{tf_section}\n\n")

    if mt5_dict:
        # Chuyển đổi dữ liệu MT5 thành báo cáo có cấu trúc
        structured_report = report_parser.parse_mt5_data_to_report(safe_mt5_data)
        
        # Chèn dữ liệu số vào placeholder trong prompt
        prompt = prompt.replace(
            "[Dữ liệu từ `CONCEPT_VALUE_TABLE` và `EXTRACT_JSON` sẽ được chèn vào đây]",
            f"DỮ LIỆU SỐ THAM KHẢO:\n{structured_report}"
        )
        
        # Chèn ngữ cảnh lịch sử (nếu có)
        if context_block:
            prompt = prompt.replace(
                "[Dữ liệu từ `CONTEXT_COMPOSED` sẽ được chèn vào đây]",
                f"DỮ LIỆU LỊCH SỬ (VÒNG TRƯỚC):\n{context_block}"
            )
        else:
            # Xóa placeholder nếu không có ngữ cảnh
            prompt = prompt.replace(
                "**DỮ LIỆU LỊCH SỬ (NẾU CÓ):**\n[Dữ liệu từ `CONTEXT_COMPOSED` sẽ được chèn vào đây]",
                ""
            )
        parts_text.append(prompt)
    else:
        # Trường hợp không có dữ liệu MT5, chỉ dùng prompt gốc và JSON (nếu có)
        parts_text.append(prompt)
        if mt5_json_full:
            parts_text.append(f"\n\n[PHỤ LỤC_MT5_JSON]\n{mt5_json_full}")

    # Dùng dict.fromkeys để loại bỏ các phần tử trùng lặp và giữ nguyên thứ tự
    return "".join(list(dict.fromkeys(parts_text)))

def _stream_and_process_ai_response(app: "TradingToolApp", cfg: "RunConfig", model: genai.GenerativeModel, parts: List[Any], mt5_dict: Dict) -> str:
    """
    Thực hiện gọi API streaming, xử lý các chunk trả về, và kích hoạt auto-trade.
    """
    combined_text = ""
    trade_action_taken = False
    
    ui_utils.ui_detail_replace(app, "Đang nhận dữ liệu từ AI...")
    stream_generator = _gen_stream_with_retry(model, parts)
    
    for chunk in stream_generator:
        if app.stop_flag:
            if hasattr(stream_generator, 'close'):
                stream_generator.close()
            raise SystemExit("Người dùng đã dừng quá trình nhận dữ liệu AI.")

        chunk_text = getattr(chunk, "text", "")
        if chunk_text:
            combined_text += chunk_text
            # Cập nhật UI trên luồng chính để tránh xung đột
            ui_utils._enqueue(app, lambda: ui_utils.ui_detail_replace(app, combined_text))

            # TÁC DỤNG PHỤ QUAN TRỌNG: Auto-trade được kích hoạt ngay tại đây
            # với từng phần nhỏ của câu trả lời từ AI.
            if not trade_action_taken and cfg.auto_trade_enabled:
                try:
                    action_was_taken = auto_trade.auto_trade_if_high_prob(app, combined_text, mt5_dict, cfg)
                    if action_was_taken:
                        trade_action_taken = True
                        app.ui_status("Auto-Trade: Đã thực hiện hành động từ stream.")
                except Exception as e:
                    app.ui_status(f"Lỗi Auto-Trade stream: {e}")
    
    return combined_text or "[Không có nội dung trả về]"

# ==================================================================================
# HÀM WORKER CHÍNH (MAIN WORKER FUNCTION)
# ==================================================================================

def run_analysis_worker(app: "TradingToolApp", prompt_no_entry: str, prompt_entry_run: str, model_name: str, cfg: "RunConfig"):
    """
    Luồng phân tích chính, điều phối toàn bộ quy trình từ upload ảnh đến auto-trade.
    Hàm này được thiết kế để chạy trong một luồng riêng biệt (thread) để không làm treo giao diện.
    """
    uploaded_files = []
    early_exit = False
    composed = ""
    mt5_dict = {}
    combined_text = "" # Khởi tạo biến để đảm bảo nó luôn tồn tại

    try:
        # --- GIAI ĐOẠN 1: KHỞI TẠO VÀ KIỂM TRA ĐẦU VÀO ---
        paths = [r["path"] for r in app.results]
        names = [r["name"] for r in app.results]
        max_files = max(0, int(cfg.max_files))
        if max_files > 0 and len(paths) > max_files:
            paths, names = paths[:max_files], names[:max_files]
        
        if not paths:
            app.ui_status("Không có ảnh để phân tích.")
            ui_utils._enqueue(app, app._finalize_stopped)
            return

        try:
            model = genai.GenerativeModel(model_name=model_name)
        except Exception as e:
            ui_utils.ui_message(app, "error", "Lỗi Model", f"Không thể khởi tạo model '{model_name}': {e}")
            ui_utils._enqueue(app, app._finalize_stopped)
            return

        # --- GIAI ĐOẠN 2: KIỂM TRA ĐIỀU KIỆN NO-RUN ---
        # Chốt chặn đầu tiên: kiểm tra các điều kiện không nên chạy (cuối tuần, ngoài giờ, v.v.)
        should_run, reason = no_run.check_no_run_conditions(app)
        if not should_run:
            app.ui_status(reason)
            app._log_trade_decision({
                "stage": "no-run-skip",
                "t": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "reason": reason
            }, folder_override=(app.mt5_symbol_var.get().strip() or None))
            raise SystemExit(reason)

        # --- GIAI ĐOẠN 3: CHUẨN BỊ VÀ UPLOAD ẢNH ---
        t_up0 = _tnow()
        cache = uploader.UploadCache.load() if cfg.cache_enabled else {}
        prepared_map = {}
        to_upload = []
        file_slots = [None] * len(paths)

        for i, (p, n) in enumerate(zip(paths, names)):
            cached_remote = uploader.UploadCache.lookup(cache, p) if cache else ""
            if cached_remote:
                try:
                    f = genai.get_file(cached_remote)
                    if getattr(getattr(f, "state", None), "name", None) == "ACTIVE":
                        file_slots[i] = f
                        prepared_map[i] = None
                        continue # Bỏ qua nếu file đã có trên cloud và đang hoạt động
                except Exception:
                    pass # Nếu get_file lỗi, sẽ tiến hành upload lại
            
            upath = uploader.prepare_image(p, optimize=bool(cfg.optimize_lossless), app_dir=APP_DIR)
            to_upload.append((i, p, n, upath))
            prepared_map[i] = upath

        # Xử lý trường hợp ảnh không đổi và thoát sớm
        if cfg.only_generate_if_changed and not to_upload and all(file_slots):
            _handle_no_change_scenario(app, cfg)

        for (i, _, _, _) in to_upload:
            app.results[i]["status"] = "Đang upload..."
            app._update_tree_row(i, "Đang upload...")

        # Truyền app vào hàm upload để nó có thể gán executor
        file_slots_from_upload, steps_upload = _upload_images_parallel(app, cfg, to_upload)
        # Cập nhật file_slots với các file vừa upload
        for i, f in enumerate(file_slots_from_upload):
            if f:
                file_slots[i] = f
        
        if to_upload:
            app.ui_status(f"Upload xong {len(to_upload)} ảnh trong {(_tnow()-t_up0):.2f}s")

        if cfg.cache_enabled:
            for (f, p) in uploaded_files:
                uploader.UploadCache.put(cache, p, f.name)
            uploader.UploadCache.save(cache)

        if app.stop_flag: raise SystemExit("Dừng bởi người dùng sau khi upload.")

        # --- GIAI ĐOẠN 4: XÂY DỰNG NGỮ CẢNH VÀ KIỂM TRA NO-TRADE ---
        t_ctx0 = _tnow()
        safe_mt5_data, mt5_dict, context_block, mt5_json_full = _prepare_and_build_context(app, cfg)
        app.ui_status(f"Context+MT5 xong trong {(_tnow()-t_ctx0):.2f}s")

        # Chốt chặn thứ hai: kiểm tra các điều kiện không nên giao dịch (tin tức, rủi ro, v.v.)
        if cfg.nt_enabled and mt5_dict:
            ok, reasons, _, _, _ = no_trade.evaluate(
                safe_mt5_data, cfg, cache_events=app.ff_cache_events_local,
                cache_fetch_time=app.ff_cache_fetch_time, ttl_sec=300
            )
            app.last_no_trade_ok = bool(ok)
            app.last_no_trade_reasons = list(reasons or [])
            if not ok:
                app._log_trade_decision({
                    "stage": "no-trade",
                    "t": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "reasons": reasons
                }, folder_override=(app.mt5_symbol_var.get().strip() or None))
                
                note = "NO-TRADE: Điều kiện giao dịch không thỏa.\n- " + "\n- ".join(reasons)
                if context_block: note += f"\n\n{context_block}"
                if mt5_json_full: note += f"\n\n[PHỤ LỤC_MT5_JSON]\n{mt5_json_full}"
                
                app.combined_report_text = note
                ui_utils.ui_detail_replace(app, note)
                app._auto_save_report(note, cfg)
                ui_utils.ui_refresh_history_list(app)
                
                if mt5_dict: # auto_trade.mt5_manage_be_trailing(app, mt5_dict, cfg) # Tạm thời vô hiệu hóa
                    pass # Giữ khối lệnh hợp lệ sau khi comment
                early_exit = True
                raise SystemExit("Điều kiện No-Trade được kích hoạt.")

        # --- GIAI ĐOẠN 5: GỌI MODEL AI VÀ XỬ LÝ KẾT QUẢ ---
        app.ui_status("Đang phân tích toàn bộ thư mục...")
        
        all_media = []
        for i, f in enumerate(file_slots):
            if f is None:
                all_media.append(uploader.as_inline_media_part(prepared_map.get(i) or paths[i]))
            else:
                all_media.append(uploader.file_or_inline_for_model(f, prepared_map.get(i), paths[i]))

        prompt = _select_prompt_dynamically(app, cfg, safe_mt5_data, prompt_no_entry, prompt_entry_run)
        prompt_final = _construct_final_prompt(app, prompt, mt5_dict, safe_mt5_data, context_block, mt5_json_full, paths)
        
        parts = all_media + [prompt_final]
        
        t_llm0 = _tnow()
        combined_text = _stream_and_process_ai_response(app, cfg, model, parts, mt5_dict)
        app.ui_status(f"Model trả lời trong {(_tnow()-t_llm0):.2f}s")
        
        app._update_progress(steps_upload + 1, steps_upload + 2)

    except SystemExit:
        # Lỗi này được dùng để thoát khỏi worker một cách có kiểm soát, không cần báo lỗi
        pass
    except Exception as e:
        tb_str = traceback.format_exc()
        app.ui_status(f"Lỗi nghiêm trọng trong worker: {e}")
        combined_text = f"[LỖI PHÂN TÍCH] Đã xảy ra lỗi.\n\nChi tiết: {e}\n\nTraceback:\n{tb_str}"
        app.combined_report_text = combined_text
        ui_utils.ui_detail_replace(app, combined_text)
    
    finally:
        # --- GIAI ĐOẠN 6: HOÀN TẤT, LƯU TRỮ VÀ DỌN DẸP ---
        if not early_exit:
            # Cập nhật trạng thái trên UI
            for i in range(len(paths)):
                app.results[i]["status"] = "Hoàn tất"
                app._update_tree_row(i, "Hoàn tất")

            app.combined_report_text = combined_text
            
            # Lưu báo cáo
            saved_path = md_saver.save_md_report(app, combined_text, cfg)
            try:
                json_saver.save_json_report(app, combined_text, cfg, names, composed)
            except Exception as e:
                tb_str = traceback.format_exc()
                err_msg = f"Lỗi nghiêm trọng khi lưu ctx_*.json: {e}\n\n{tb_str}"
                app.ui_status(err_msg)
                ui_utils.ui_message(app, "error", "Lỗi Lưu JSON", err_msg)
                logging.exception("CRITICAL: Lỗi lưu file JSON từ worker.")
            
            ui_utils.ui_refresh_history_list(app)
            ui_utils.ui_refresh_json_list(app)

            # Gửi thông báo và quản lý lệnh lần cuối
            if not app.stop_flag:
                app._maybe_notify_telegram(combined_text, saved_path, cfg)
                if mt5_dict:
                    # auto_trade.mt5_manage_be_trailing(app, mt5_dict, cfg) # Tạm thời vô hiệu hóa
                    pass # Giữ khối lệnh hợp lệ sau khi comment

        # Dọn dẹp file đã upload nếu được cấu hình
        if not cfg.cache_enabled and cfg.delete_after:
            for uf, _ in uploaded_files:
                app._maybe_delete(uf)
        
        # Báo cho luồng chính biết worker đã hoàn thành và reset thanh tiến trình
        app._update_progress(0, 1)
        ui_utils._enqueue(app, app._finalize_done if not app.stop_flag else app._finalize_stopped)
