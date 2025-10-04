from __future__ import annotations

import logging
import time
import traceback
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

import google.generativeai as genai

from APP.analysis import context_builder, image_processor
from APP.core.trading import actions as trade_actions
from APP.core.trading import conditions as trade_conditions
from APP.persistence import json_handler, md_handler
from APP.services import gemini_service
from APP.ui.components import prompt_manager
from APP.ui.utils import ui_builder
from APP.utils.safe_data import SafeMT5Data

if TYPE_CHECKING:
    from APP.configs.app_config import RunConfig
    from APP.ui.app_ui import AppUI

logger = logging.getLogger(__name__)


def _tnow() -> float:
    """Trả về thời gian hiện tại với độ chính xác cao."""
    return time.perf_counter()


class AnalysisWorker:
    """
    Lớp điều phối toàn bộ quy trình phân tích, chạy trong một luồng riêng biệt.
    """

    def __init__(self, app: "AppUI", cfg: "RunConfig"):
        """
        Khởi tạo worker với các đối tượng cần thiết.

        Args:
            app (AppUI): Instance của ứng dụng UI chính.
            cfg (RunConfig): Đối tượng cấu hình cho lần chạy này.
        """
        self.app = app
        self.cfg = cfg
        self.model_name: str = self.app.model_var.get()
        self.model: Optional[genai.GenerativeModel] = None

        # State variables
        self.early_exit: bool = False
        self.uploaded_files: list[tuple[genai.File, str]] = []
        self.paths: List[str] = []
        self.names: List[str] = []
        self.composed: str = ""
        self.combined_text: str = ""
        self.safe_mt5_data: Optional[SafeMT5Data] = None
        self.mt5_dict: Dict[str, Any] = {}
        self.context_block: str = ""
        self.mt5_json_full: str = ""
        self.file_slots: List[Optional[genai.File]] = []
        self.prepared_map: Dict[int, Optional[str]] = {}
        self.steps_upload: int = 0

    def run(self) -> None:
        """Phương thức chính để chạy worker, chứa logic try/except/finally."""
        logger.debug(f"Bắt đầu AnalysisWorker.run với model: {self.model_name}")
        try:
            self._stage_1_initialize_and_validate()
            self._stage_2_build_context_and_check_conditions()
            self._stage_3_prepare_and_upload_images()
            self._stage_4_call_ai_model()
            self._stage_5_execute_or_manage_trades()
        except SystemExit as e:
            logger.info(f"Worker đã thoát một cách có kiểm soát: {e}")
        except Exception:
            tb_str = traceback.format_exc()
            logger.exception("Lỗi nghiêm trọng trong worker.")
            self.combined_text = f"[LỖI PHÂN TÍCH] Đã xảy ra lỗi.\n\nChi tiết:\n{tb_str}"
            self.app.combined_report_text = self.combined_text
            ui_builder.ui_detail_replace(self.app, self.combined_text)
        finally:
            self._stage_6_finalize_and_cleanup()

    def _stage_1_initialize_and_validate(self) -> None:
        """Giai đoạn 1: Khởi tạo và kiểm tra đầu vào."""
        logger.debug("GIAI ĐOẠN 1: Khởi tạo và kiểm tra đầu vào.")
        self.paths = [r["path"] for r in self.app.results]
        self.names = [r["name"] for r in self.app.results]
        max_files = max(0, self.cfg.folder.max_files)
        if max_files > 0 and len(self.paths) > max_files:
            self.paths, self.names = self.paths[:max_files], self.names[:max_files]

        if not self.paths:
            self.app.ui_status("Không có ảnh để phân tích.")
            ui_builder.enqueue(self.app, self.app._finalize_stopped)
            raise SystemExit("Không có ảnh để phân tích.")

        try:
            self.model = genai.GenerativeModel(model_name=self.model_name)
            logger.debug(f"Model '{self.model_name}' được khởi tạo thành công.")
        except Exception as e:
            ui_builder.ui_message(self.app, "error", "Lỗi Model", f"Không thể khởi tạo model '{self.model_name}': {e}")
            ui_builder.enqueue(self.app, self.app._finalize_stopped)
            raise SystemExit(f"Lỗi khởi tạo model: {e}")

    def _stage_2_build_context_and_check_conditions(self) -> None:
        """Giai đoạn 2: Xây dựng ngữ cảnh và kiểm tra các điều kiện."""
        logger.debug("GIAI ĐOẠN 2: Xây dựng ngữ cảnh và kiểm tra điều kiện.")
        no_run_reason = trade_conditions.check_no_run_conditions(self.app, self.cfg)
        if no_run_reason:
            trade_conditions.handle_early_exit(self.app, self.cfg, no_run_reason)
            self.early_exit = True
            raise SystemExit(f"Điều kiện No-Run: {no_run_reason}")

        t_ctx0 = _tnow()
        self.safe_mt5_data, self.mt5_dict, self.context_block, self.mt5_json_full = \
            context_builder.coordinate_context_building(self.app, self.cfg)
        self.app.ui_status(f"Context+MT5 xong trong {(_tnow() - t_ctx0):.2f}s")

        no_trade_reasons = trade_conditions.check_no_trade_conditions(self.app, self.cfg, self.safe_mt5_data)
        if no_trade_reasons:
            reason_str = ", ".join(no_trade_reasons)
            trade_conditions.handle_early_exit(self.app, self.cfg, f"NO-TRADE: {reason_str}")
            self.early_exit = True
            raise SystemExit(f"NO-TRADE: {reason_str}")

    def _stage_3_prepare_and_upload_images(self) -> None:
        """Giai đoạn 3: Chuẩn bị và upload ảnh."""
        logger.debug("GIAI ĐOẠN 3: Chuẩn bị và upload ảnh.")
        t_up0 = _tnow()
        cache = image_processor.UploadCache.load() if self.cfg.upload.cache_enabled else {}
        
        self.file_slots, self.prepared_map, to_upload = \
            image_processor.prepare_images_for_upload(self.paths, self.names, cache, self.cfg)
        
        if self.cfg.folder.only_generate_if_changed and not to_upload and all(self.file_slots):
            trade_conditions.handle_early_exit(self.app, self.cfg, "Ảnh không đổi.")
            self.early_exit = True
            raise SystemExit("Ảnh không đổi, thoát sớm.")

        for (i, _, _, _) in to_upload:
            self.app.results[i]["status"] = "Đang upload..."
            self.app._update_tree_row(i, "Đang upload...")

        file_slots_from_upload, self.steps_upload = \
            image_processor.upload_images_parallel(self.app, self.cfg, to_upload)
        
        for i, f in enumerate(file_slots_from_upload):
            if f:
                original_index = to_upload[i][0]
                self.file_slots[original_index] = f
                self.uploaded_files.append((f, self.paths[original_index]))

        if to_upload:
            self.app.ui_status(f"Upload xong {len(to_upload)} ảnh trong {(_tnow() - t_up0):.2f}s")

        if self.cfg.upload.cache_enabled:
            for (f, p) in self.uploaded_files:
                image_processor.UploadCache.put(cache, p, f.name)
            image_processor.UploadCache.save(cache)

        if self.app.stop_flag:
            raise SystemExit("Dừng bởi người dùng sau khi upload.")

    def _stage_4_call_ai_model(self) -> None:
        """Giai đoạn 4: Gọi model AI và xử lý kết quả."""
        logger.debug("GIAI ĐOẠN 4: Gọi model AI.")
        self.app.ui_status("Đang phân tích...")
        all_media = image_processor.prepare_media_for_gemini(self.file_slots, self.prepared_map, self.paths)
        
        prompt_no_entry = self.app.prompt_manager.get_prompt_no_entry()
        prompt_entry_run = self.app.prompt_manager.get_prompt_entry_run()

        prompt = prompt_manager.select_prompt_dynamically(self.app, self.cfg, self.safe_mt5_data, prompt_no_entry, prompt_entry_run)
        prompt_final = prompt_manager.construct_final_prompt(self.app, prompt, self.mt5_dict, self.safe_mt5_data, self.context_block, self.mt5_json_full, self.paths)

        parts = all_media + [prompt_final]
        t_llm0 = _tnow()
        self.combined_text = gemini_service.stream_gemini_response(self.app, self.cfg, self.model, parts, self.mt5_dict)
        self.app.ui_status(f"Model trả lời trong {(_tnow() - t_llm0):.2f}s")
        self.app._update_progress(self.steps_upload + 1, self.steps_upload + 2)

    def _stage_5_execute_or_manage_trades(self) -> None:
        """Giai đoạn 5: Thực thi hoặc quản lý giao dịch."""
        logger.debug("GIAI ĐOẠN 5: Thực thi hoặc quản lý giao dịch.")
        has_active_positions = self.safe_mt5_data and self.safe_mt5_data.positions
        
        if not has_active_positions:
            logger.info("Không có lệnh. Tìm kiếm cơ hội vào lệnh mới.")
            trade_actions.execute_trade_action(self.app, self.combined_text, self.safe_mt5_data, self.cfg)
        else:
            logger.info(f"Có {len(self.safe_mt5_data.positions)} lệnh. Thực hiện quản lý.")
            trade_actions.manage_existing_trades(self.app, self.combined_text, self.cfg, self.safe_mt5_data)

    def _stage_6_finalize_and_cleanup(self) -> None:
        """Giai đoạn 6: Hoàn tất, lưu trữ và dọn dẹp."""
        logger.debug("GIAI ĐOẠN 6: Hoàn tất và dọn dẹp.")
        if not self.early_exit:
            for i in range(len(self.paths)):
                self.app.results[i]["status"] = "Hoàn tất"
                self.app._update_tree_row(i, "Hoàn tất")

            self.app.combined_report_text = self.combined_text
            saved_path = md_handler.save_md_report(self.app, self.combined_text, self.cfg)
            try:
                json_handler.save_json_report(self.app, self.combined_text, self.cfg, self.names, self.composed)
            except Exception:
                tb_str = traceback.format_exc()
                err_msg = f"Lỗi nghiêm trọng khi lưu ctx_*.json:\n{tb_str}"
                ui_builder.ui_message(self.app, "error", "Lỗi Lưu JSON", err_msg)

            ui_builder.ui_refresh_history_list(self.app)
            ui_builder.ui_refresh_json_list(self.app)

            if not self.app.stop_flag:
                self.app._maybe_notify_telegram(self.combined_text, saved_path, self.cfg)

        if not self.cfg.upload.cache_enabled and self.cfg.folder.delete_after:
            for uf, _ in self.uploaded_files:
                image_processor.delete_uploaded_file(uf)
        
        self.app._update_progress(0, 1)
        final_state = self.app._finalize_done if not self.app.stop_flag else self.app._finalize_stopped
        ui_builder.enqueue(self.app, final_state)
        logger.debug("Kết thúc AnalysisWorker.run.")
