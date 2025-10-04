from __future__ import annotations
import time
import logging
import traceback
from typing import TYPE_CHECKING

import google.generativeai as genai # Thêm import genai

from src.core.worker_modules import api_handlers
from src.core.worker_modules import context_coordinator
from src.core.worker_modules import image_processor
from src.core.worker_modules import prompt_manager
from src.core.worker_modules import trade_conditions
from src.core.worker_modules import no_run_trade_conditions # Thêm import no_run_trade_conditions
from src.utils import ui_utils
from src.utils import json_saver, md_saver
from src.config.constants import APP_DIR

# Khởi tạo logger cho module này
logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from scripts.tool import TradingToolApp
    from src.config.config import RunConfig

def _tnow() -> float:
    """Trả về thời gian hiện tại với độ chính xác cao."""
    logger.debug("Bắt đầu hàm _tnow.")
    result = time.perf_counter()
    logger.debug(f"Kết thúc hàm _tnow. Thời gian: {result}")
    return result

def run_analysis_worker(app: "TradingToolApp", prompt_no_entry: str, prompt_entry_run: str, model_name: str, cfg: "RunConfig"):
    """
    Luồng phân tích chính, điều phối toàn bộ quy trình từ upload ảnh đến auto-trade.
    Hàm này được thiết kế để chạy trong một luồng riêng biệt (thread) để không làm treo giao diện.
    """
    logger.debug("Bắt đầu hàm run_analysis_worker.")
    uploaded_files = []
    early_exit = False
    composed = ""
    mt5_dict = {}
    combined_text = "" # Khởi tạo biến để đảm bảo nó luôn tồn tại

    logger.debug(f"Bắt đầu run_analysis_worker với model: {model_name}, folder: {cfg.folder}")

    try:
        # --- GIAI ĐOẠN 1: KHỞI TẠO VÀ KIỂM TRA ĐẦU VÀO ---
        logger.debug(f"GIAI ĐOẠN 1: Khởi tạo và kiểm tra đầu vào. Số ảnh: {len(app.results)}")
        paths = [r["path"] for r in app.results]
        names = [r["name"] for r in app.results]
        max_files = max(0, int(cfg.max_files))
        if max_files > 0 and len(paths) > max_files:
            paths, names = paths[:max_files], names[:max_files]
        
        if not paths:
            app.ui_status("Không có ảnh để phân tích.")
            ui_utils._enqueue(app, app._finalize_stopped)
            logger.info("Không có ảnh để phân tích, thoát worker.")
            return

        try:
            model = genai.GenerativeModel(model_name=model_name)
            logger.debug(f"Model '{model_name}' được khởi tạo thành công.")
        except Exception as e:
            ui_utils.ui_message(app, "error", "Lỗi Model", f"Không thể khởi tạo model '{model_name}': {e}")
            ui_utils._enqueue(app, app._finalize_stopped)
            logger.exception(f"Lỗi khởi tạo model '{model_name}'.")
            return

        # --- GIAI ĐOẠN 2: KIỂM TRA ĐIỀU KIỆN NO-RUN ---
        logger.debug("GIAI ĐOẠN 2: Kiểm tra điều kiện NO-RUN.")
        # Chốt chặn đầu tiên: kiểm tra các điều kiện không nên chạy (cuối tuần, ngoài giờ, v.v.)
        should_proceed, reason = no_run_trade_conditions.check_all_preconditions(
            app, cfg, safe_mt5_data=None, mt5_dict={}, context_block="", mt5_json_full=""
        )
        if not should_proceed:
            logger.info(f"Điều kiện No-Run được kích hoạt: {reason}, thoát sớm.")
            early_exit = True
            raise SystemExit("Điều kiện No-Run được kích hoạt.")
        logger.debug("Không có điều kiện No-Run nào được kích hoạt.")

        # --- GIAI ĐOẠN 3: CHUẨN BỊ VÀ UPLOAD ẢNH ---
        logger.debug(f"GIAI ĐOẠN 3: Chuẩn bị và upload ảnh. Số ảnh cần xử lý: {len(paths)}")
        t_up0 = _tnow()
        cache = image_processor.UploadCache.load() if cfg.cache_enabled else {}
        prepared_map = {}
        to_upload = []
        file_slots = [None] * len(paths)
        uploaded_files = [] # Khởi tạo đúng cách

        for i, (p, n) in enumerate(zip(paths, names)):
            cached_remote = image_processor.UploadCache.lookup(cache, p) if cache else ""
            if cached_remote:
                try:
                    f = genai.get_file(cached_remote)
                    if getattr(getattr(f, "state", None), "name", None) == "ACTIVE":
                        file_slots[i] = f
                        prepared_map[i] = None
                        logger.debug(f"Sử dụng ảnh '{n}' từ cache.")
                        continue # Bỏ qua nếu file đã có trên cloud và đang hoạt động
                except Exception:
                    logger.warning(f"Lỗi khi truy xuất ảnh '{n}' từ cache, sẽ upload lại.")
                    pass # Nếu get_file lỗi, sẽ tiến hành upload lại
            
            upath = image_processor.prepare_image(p, optimize=bool(cfg.optimize_lossless), app_dir=APP_DIR)
            to_upload.append((i, p, n, upath))
            prepared_map[i] = upath
            logger.debug(f"Ảnh '{n}' được chuẩn bị để upload.")

        # Xử lý trường hợp ảnh không đổi và thoát sớm
        if cfg.only_generate_if_changed and not to_upload and all(file_slots):
            trade_conditions.handle_no_change_scenario(app, cfg)
            early_exit = True
            logger.info("Ảnh không đổi và chỉ tạo nếu thay đổi, thoát sớm.")
            raise SystemExit("Ảnh không đổi, thoát sớm.")

        for (i, _, _, _) in to_upload:
            app.results[i]["status"] = "Đang upload..."
            app._update_tree_row(i, "Đang upload...")

        # Truyền app vào hàm upload để nó có thể gán executor
        file_slots_from_upload, steps_upload = image_processor.upload_images_parallel(app, cfg, to_upload)
        # Cập nhật file_slots với các file vừa upload
        for i, f in enumerate(file_slots_from_upload):
            if f:
                file_slots[i] = f
                uploaded_files.append((f, paths[i])) # Cập nhật uploaded_files

        if to_upload:
            app.ui_status(f"Upload xong {len(to_upload)} ảnh trong {(_tnow()-t_up0):.2f}s")
            logger.debug(f"Upload xong {len(to_upload)} ảnh trong {(_tnow()-t_up0):.2f}s.")

        if cfg.cache_enabled:
            for (f, p) in uploaded_files:
                image_processor.UploadCache.put(cache, p, f.name)
            image_processor.UploadCache.save(cache)
            logger.debug("Cache upload đã được cập nhật và lưu.")

        if app.stop_flag:
            logger.info("Dừng bởi người dùng sau khi upload.")
            raise SystemExit("Dừng bởi người dùng sau khi upload.")

        # --- GIAI ĐOẠN 4: XÂY DỰNG NGỮ CẢNH VÀ KIỂM TRA NO-TRADE ---
        logger.debug("GIAI ĐOẠN 4: Xây dựng ngữ cảnh và kiểm tra NO-TRADE.")
        t_ctx0 = _tnow()
        safe_mt5_data, mt5_dict, context_block, mt5_json_full = context_coordinator.prepare_and_build_context(app, cfg)
        app.ui_status(f"Context+MT5 xong trong {(_tnow()-t_ctx0):.2f}s")
        logger.debug(f"Context+MT5 xong trong {(_tnow()-t_ctx0):.2f}s.")

        # Chốt chặn thứ hai: kiểm tra các điều kiện không nên giao dịch (tin tức, rủi ro, v.v.)
        should_proceed_trade, no_trade_reason = no_run_trade_conditions.check_all_preconditions(
            app, cfg, safe_mt5_data, mt5_dict, context_block, mt5_json_full
        )
        if not should_proceed_trade:
            logger.info(f"Điều kiện No-Trade được kích hoạt: {no_trade_reason}, thoát sớm.")
            early_exit = True
            raise SystemExit("Điều kiện No-Trade được kích hoạt.")
        logger.debug("Không có điều kiện No-Trade nào được kích hoạt.")

        # --- GIAI ĐOẠN 5: GỌI MODEL AI VÀ XỬ LÝ KẾT QUẢ ---
        logger.debug("GIAI ĐOẠN 5: Gọi model AI và xử lý kết quả.")
        app.ui_status("Đang phân tích toàn bộ thư mục...")
        
        all_media = []
        for i, f in enumerate(file_slots):
            if f is None:
                all_media.append(image_processor.as_inline_media_part(prepared_map.get(i) or paths[i]))
                logger.debug(f"Thêm ảnh inline: {paths[i]}")
            else:
                all_media.append(image_processor.file_or_inline_for_model(f, prepared_map.get(i), paths[i]))
                logger.debug(f"Thêm ảnh đã upload hoặc inline: {paths[i]}")

        prompt = prompt_manager.select_prompt_dynamically(app, cfg, safe_mt5_data, prompt_no_entry, prompt_entry_run)
        logger.debug(f"Prompt được chọn: {prompt[:100]}...") # Log 100 ký tự đầu của prompt
        prompt_final = prompt_manager.construct_final_prompt(app, prompt, mt5_dict, safe_mt5_data, context_block, mt5_json_full, paths)
        logger.debug(f"Prompt cuối cùng đã được xây dựng. Độ dài: {len(prompt_final)} ký tự.")
        
        parts = all_media + [prompt_final]
        logger.debug(f"Tổng số phần gửi đến model: {len(parts)} (bao gồm {len(all_media)} media và 1 prompt).")
        
        t_llm0 = _tnow()
        combined_text = api_handlers.stream_and_process_ai_response(app, cfg, model, parts, mt5_dict)
        app.ui_status(f"Model trả lời trong {(_tnow()-t_llm0):.2f}s")
        logger.debug(f"Model AI đã trả lời trong {(_tnow()-t_llm0):.2f}s. Độ dài văn bản kết hợp: {len(combined_text)} ký tự.")
        
        app._update_progress(steps_upload + 1, steps_upload + 2)

    except SystemExit:
        logger.info("Worker đã thoát một cách có kiểm soát (SystemExit).")
        pass
    except Exception as e:
        tb_str = traceback.format_exc()
        logger.exception(f"Lỗi nghiêm trọng trong worker: {e}") # Sử dụng logger.exception để tự động thêm traceback
        app.ui_status(f"Lỗi nghiêm trọng trong worker: {e}")
        combined_text = f"[LỖI PHÂN TÍCH] Đã xảy ra lỗi.\n\nChi tiết: {e}\n\nTraceback:\n{tb_str}"
        app.combined_report_text = combined_text
        ui_utils.ui_detail_replace(app, combined_text)
    
    finally:
        logger.debug("GIAI ĐOẠN 6: Hoàn tất, lưu trữ và dọn dẹp.")
        if not early_exit:
            # Cập nhật trạng thái trên UI
            for i in range(len(paths)):
                app.results[i]["status"] = "Hoàn tất"
                app._update_tree_row(i, "Hoàn tất")
            logger.debug("Trạng thái UI đã được cập nhật thành 'Hoàn tất'.")

            app.combined_report_text = combined_text
            
            # Lưu báo cáo
            saved_path = md_saver.save_md_report(app, combined_text, cfg)
            logger.debug(f"Báo cáo Markdown đã lưu tại: {saved_path}")
            try:
                json_saver.save_json_report(app, combined_text, cfg, names, composed)
                logger.debug("Báo cáo JSON đã lưu.")
            except Exception as e:
                tb_str = traceback.format_exc()
                err_msg = f"Lỗi nghiêm trọng khi lưu ctx_*.json: {e}\n\n{tb_str}"
                app.ui_status(err_msg)
                ui_utils.ui_message(app, "error", "Lỗi Lưu JSON", err_msg)
                logger.exception("CRITICAL: Lỗi lưu file JSON từ worker.")
            
            ui_utils.ui_refresh_history_list(app)
            ui_utils.ui_refresh_json_list(app)
            logger.debug("Danh sách lịch sử và JSON trên UI đã được làm mới.")

            # Gửi thông báo và quản lý lệnh lần cuối
            if not app.stop_flag:
                app._maybe_notify_telegram(combined_text, saved_path, cfg)
                logger.debug("Đã kiểm tra và gửi thông báo Telegram (nếu có).")
                if mt5_dict:
                    # trade_actions.mt5_manage_be_trailing(app, mt5_dict, cfg) # Tạm thời vô hiệu hóa
                    pass # Giữ khối lệnh hợp lệ sau khi comment

        # Dọn dẹp file đã upload nếu được cấu hình
        if not cfg.cache_enabled and cfg.delete_after:
            for uf, _ in uploaded_files: # uploaded_files ở đây có vẻ không được dùng đúng cách, cần xem lại
                image_processor.delete_uploaded_file(uf)
            logger.debug("Đã dọn dẹp các file đã upload (nếu được cấu hình).")
        
        # Báo cho luồng chính biết worker đã hoàn thành và reset thanh tiến trình
        app._update_progress(0, 1)
        ui_utils._enqueue(app, app._finalize_done if not app.stop_flag else app._finalize_stopped)
        logger.debug("Kết thúc hàm run_analysis_worker.")
