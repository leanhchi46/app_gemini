from __future__ import annotations

import logging
import time
import traceback
from typing import TYPE_CHECKING

import google.generativeai as genai

from APP.analysis import context_builder, image_processor, prompt_builder
from APP.configs.workspace_config import get_workspace_dir
from APP.core.trading import actions as trade_actions
from APP.core.trading import conditions as trade_conditions
from APP.persistence import json_handler, md_handler
from APP.services import gemini_service, news_service
from APP.ui.utils import ui_builder

if TYPE_CHECKING:
    from APP.configs.app_config import RunConfig
    from APP.ui.app_ui import AppUI

logger = logging.getLogger(__name__)


def _tnow() -> float:
    """Trả về thời gian hiện tại với độ chính xác cao."""
    return time.perf_counter()


def run_analysis_worker(
    app: "AppUI",
    prompt_no_entry: str,
    prompt_entry_run: str,
    model_name: str,
    cfg: "RunConfig",
):
    """
    Luồng phân tích chính, điều phối toàn bộ quy trình từ upload ảnh đến auto-trade.
    Hàm này được thiết kế để chạy trong một luồng riêng biệt (thread) để không làm treo giao diện.
    """
    logger.debug("Bắt đầu hàm run_analysis_worker.")
    uploaded_files = []
    early_exit = False
    combined_text = ""
    workspace_dir = get_workspace_dir()

    try:
        # --- GIAI ĐOẠN 1: KHỞI TẠO VÀ KIỂM TRA ĐẦU VÀO ---
        logger.debug("GIAI ĐOẠN 1: Khởi tạo và kiểm tra đầu vào.")
        paths = [r["path"] for r in app.results]
        names = [r["name"] for r in app.results]
        max_files = max(0, cfg.max_files)
        if max_files > 0 and len(paths) > max_files:
            paths, names = paths[:max_files], names[:max_files]

        if not paths:
            app.ui_status("Không có ảnh để phân tích.")
            ui_builder.enqueue(app, app.finalize_stopped)
            return

        try:
            model = genai.GenerativeModel(model_name=model_name)
        except Exception as e:
            ui_builder.message(app, "error", "Lỗi Model", f"Không thể khởi tạo model '{model_name}': {e}")
            ui_builder.enqueue(app, app.finalize_stopped)
            return

        # --- GIAI ĐOẠN 2: KIỂM TRA ĐIỀU KIỆN NO-RUN ---
        logger.debug("GIAI ĐOẠN 2: Kiểm tra điều kiện NO-RUN.")
        should_proceed, reason = trade_conditions.check_no_run_conditions(cfg)
        if not should_proceed:
            logger.info(f"Điều kiện No-Run được kích hoạt: {reason}, thoát sớm.")
            early_exit = True
            raise SystemExit("Điều kiện No-Run được kích hoạt.")

        # --- GIAI ĐOẠN 3: CHUẨN BỊ VÀ UPLOAD ẢNH ---
        logger.debug("GIAI ĐOẠN 3: Chuẩn bị và upload ảnh.")
        t_up0 = _tnow()
        prepared_map, file_slots, to_upload = image_processor.prepare_images_for_upload(
            paths, names, cfg.cache_enabled, cfg.optimize_lossless
        )

        if cfg.only_generate_if_changed and not to_upload and all(file_slots):
            trade_conditions.handle_early_exit(app, "Ảnh không đổi và chỉ tạo nếu thay đổi, thoát sớm.")
            early_exit = True
            raise SystemExit("Ảnh không đổi, thoát sớm.")

        for i, _, _, _ in to_upload:
            app.update_tree_row(i, "Đang upload...")

        file_slots, uploaded_files = image_processor.upload_images_parallel(
            app, cfg, to_upload, file_slots
        )

        if to_upload:
            app.ui_status(f"Upload xong {len(to_upload)} ảnh trong {(_tnow() - t_up0):.2f}s")

        if cfg.cache_enabled:
            image_processor.update_upload_cache(uploaded_files)

        if app.stop_flag:
            raise SystemExit("Dừng bởi người dùng sau khi upload.")

        # --- GIAI ĐOẠN 4: XÂY DỰNG NGỮ CẢNH VÀ KIỂM TRA NO-TRADE ---
        logger.debug("GIAI ĐOẠN 4: Xây dựng ngữ cảnh và kiểm tra NO-TRADE.")
        t_ctx0 = _tnow()
        (
            safe_mt5_data,
            mt5_dict,
            context_block,
            mt5_json_full,
        ) = context_builder.coordinate_context_building(app, cfg)
        app.ui_status(f"Context+MT5 xong trong {(_tnow() - t_ctx0):.2f}s")

        # Tải tin tức trước khi kiểm tra điều kiện NO-TRADE
        news_events = []
        if cfg.trade_news_block_enabled:
            news_events = news_service.get_forex_factory_news(cfg)

        should_proceed_trade, no_trade_reason = trade_conditions.check_no_trade_conditions(
            cfg, safe_mt5_data, news_events
        )
        if not should_proceed_trade:
            trade_conditions.handle_early_exit(app, f"Điều kiện No-Trade: {no_trade_reason}")
            early_exit = True
            raise SystemExit("Điều kiện No-Trade được kích hoạt.")

        # --- GIAI ĐOẠN 5: GỌI MODEL AI VÀ XỬ LÝ KẾT QUẢ ---
        logger.debug("GIAI ĐOẠN 5: Gọi model AI và xử lý kết quả.")
        app.ui_status("Đang phân tích toàn bộ thư mục...")

        all_media = image_processor.prepare_media_for_gemini(
            file_slots, prepared_map, paths
        )
        prompt = prompt_builder.select_prompt(
            app, cfg, safe_mt5_data, prompt_no_entry, prompt_entry_run
        )
        prompt_final = prompt_builder.construct_prompt(
            app, prompt, mt5_dict, context_block, paths
        )
        parts = all_media + [prompt_final]

        t_llm0 = _tnow()
        trade_action_taken = False
        ui_builder.detail_replace(app, "Đang nhận dữ liệu từ AI...")
        
        response_stream = gemini_service.stream_gemini_response(app, model, parts)
        
        for chunk_text in response_stream:
            combined_text += chunk_text
            ui_builder.enqueue(app, lambda: ui_builder.detail_replace(app, combined_text))

            if not trade_action_taken and cfg.auto_trade_enabled:
                action_was_taken = trade_actions.execute_trade_action(
                    app, combined_text, mt5_dict, cfg
                )
                if action_was_taken:
                    trade_action_taken = True
                    app.ui_status("Auto-Trade: Đã thực hiện hành động từ stream.")
        
        if not combined_text:
            combined_text = "[Không có nội dung trả về]"

        app.ui_status(f"Model trả lời trong {(_tnow() - t_llm0):.2f}s")
        app.update_progress(len(paths) + 1, len(paths) + 2)

    except SystemExit as e:
        logger.info(f"Worker đã thoát một cách có kiểm soát: {e}")
    except Exception as e:
        tb_str = traceback.format_exc()
        logger.exception(f"Lỗi nghiêm trọng trong worker: {e}")
        combined_text = f"[LỖI PHÂN TÍCH] Đã xảy ra lỗi.\n\nChi tiết: {e}\n\nTraceback:\n{tb_str}"
        app.combined_report_text = combined_text
        ui_builder.detail_replace(app, combined_text)

    finally:
        logger.debug("GIAI ĐOẠN 6: Hoàn tất, lưu trữ và dọn dẹp.")
        if not early_exit:
            for i in range(len(paths)):
                app.update_tree_row(i, "Hoàn tất")

            app.combined_report_text = combined_text
            md_saver = md_handler.MdSaver(app)
            saved_path = md_saver.save_report(combined_text, cfg)
            
            json_saver = json_handler.JsonSaver(app)
            json_saver.save_report(combined_text, cfg, names)

            ui_builder.refresh_history_list(app)
            ui_builder.refresh_json_list(app)

            if not app.stop_flag:
                app.notify_telegram(combined_text, saved_path, cfg)
                if mt5_dict:
                    trade_actions.manage_existing_trades(app, mt5_dict, cfg)

        if not cfg.cache_enabled:
            image_processor.delete_uploaded_files(uploaded_files)

        app.update_progress(0, 1)
        ui_builder.enqueue(
            app, app.finalize_done if not app.stop_flag else app.finalize_stopped
        )
        logger.debug("Kết thúc hàm run_analysis_worker.")
