from __future__ import annotations

import logging
import threading
import time
import traceback
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

import google.generativeai as genai

from APP.analysis import context_builder, image_processor
from APP.core.trading import actions as trade_actions
from APP.core.trading import conditions as trade_conditions
from APP.persistence import md_handler
from APP.persistence.json_handler import JsonSaver
from APP.services import gemini_service
# Cập nhật import để nhận diện lớp lỗi mới
from APP.services.gemini_service import StreamError
from APP.analysis import prompt_builder
from APP.utils.safe_data import SafeData

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

    def __init__(self, app: "AppUI", cfg: "RunConfig", stop_event: threading.Event):
        """
        Khởi tạo worker với các đối tượng cần thiết.

        Args:
            app (AppUI): Instance của ứng dụng UI chính.
            cfg (RunConfig): Đối tượng cấu hình cho lần chạy này.
            stop_event (threading.Event): Sự kiện để báo hiệu dừng worker.
        """
        self.app = app
        self.cfg = cfg
        self.stop_event = stop_event
        self.model_name: str = self.app.model_var.get()
        self.model: Optional[Any] = None

        # State variables
        self.early_exit: bool = False
        self.uploaded_files: list[tuple[Any, str]] = []
        self.paths: List[str] = []
        self.names: List[str] = []
        self.composed: str = ""
        self.combined_text: str = ""
        self.safe_mt5_data: Optional[SafeData] = None
        self.mt5_dict: Dict[str, Any] = {}
        self.context_block: str = ""
        self.mt5_json_full: str = ""
        self.file_slots: List[Optional[Any]] = []
        self.steps_upload: int = 0

    def run(self) -> None:
        """Phương thức chính để chạy worker, chứa logic try/except/finally."""
        logger.debug(f"Bắt đầu AnalysisWorker.run với model: {self.model_name}")
        try:
            if self.stop_event.is_set():
                return
            self._stage_1_initialize_and_validate()
            if self.stop_event.is_set():
                return
            self._stage_2_build_context_and_check_conditions()
            if self.stop_event.is_set():
                return
            self._stage_3_prepare_and_upload_images()
            if self.stop_event.is_set():
                return
            # Cập nhật: Hàm này giờ sẽ trả về False nếu có lỗi không thể phục hồi
            if not self._stage_4_call_ai_model():
                # Nếu có lỗi nghiêm trọng từ AI (ví dụ: API key hỏng), dừng worker
                # và không tiếp tục đến giai đoạn 5. Giai đoạn 6 (dọn dẹp) vẫn sẽ chạy.
                return
            if self.stop_event.is_set():
                return
            self._stage_5_execute_or_manage_trades()
        except SystemExit as e:
            logger.info(f"Worker đã thoát một cách có kiểm soát: {e}")
        except Exception:
            tb_str = traceback.format_exc()
            logger.exception("Lỗi nghiêm trọng trong worker.")
            self.combined_text = f"[LỖI PHÂN TÍCH] Đã xảy ra lỗi.\n\nChi tiết:\n{tb_str}"
            self.app.combined_report_text = self.combined_text
            self.app.ui_queue.put(lambda: self.app.ui_detail_replace(self.combined_text))
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
            self.app.ui_queue.put(lambda: self.app.ui_status("Không có ảnh để phân tích."))
            self.app.ui_queue.put(self.app._finalize_stopped)
            raise SystemExit("Không có ảnh để phân tích.")

        api_key = self.app.api_key_var.get()
        if not api_key:
            self.app.ui_queue.put(lambda: self.app.show_error_message("Lỗi API", "API Key không được tìm thấy."))
            self.app.ui_queue.put(self.app._finalize_stopped)
            raise SystemExit("API Key không được tìm thấy.")

        self.model = gemini_service.initialize_model(api_key=api_key, model_name=self.model_name)

        if not self.model:
            error_message = f"Không thể khởi tạo model '{self.model_name}'. Vui lòng kiểm tra API key và kết nối mạng."
            self.app.ui_queue.put(lambda: self.app.show_error_message("Lỗi Model", error_message))
            self.app.ui_queue.put(self.app._finalize_stopped)
            raise SystemExit(f"Lỗi khởi tạo model: {self.model_name}")

    def _stage_2_build_context_and_check_conditions(self) -> None:
        """Giai đoạn 2: Xây dựng ngữ cảnh và kiểm tra các điều kiện."""
        logger.debug("GIAI ĐOẠN 2: Xây dựng ngữ cảnh và kiểm tra điều kiện.")
        should_run, no_run_reason = trade_conditions.check_no_run_conditions(self.cfg)
        if not should_run:
            trade_conditions.handle_early_exit(
                self, "no-run", no_run_reason, notify=self.cfg.telegram.notify_on_early_exit
            )
            self.early_exit = True
            raise SystemExit(f"Điều kiện No-Run: {no_run_reason}")

        t_ctx0 = _tnow()
        self.safe_mt5_data, self.mt5_dict, self.context_block, self.mt5_json_full = \
            context_builder.coordinate_context_building(self.app, self.cfg)
        self.app.ui_queue.put(lambda: self.app.ui_status(f"Context+MT5 xong trong {(_tnow() - t_ctx0):.2f}s"))

        # Kiểm tra điều kiện NO-TRADE ngay sau khi có context
        no_trade_reasons = trade_conditions.check_no_trade_conditions(
            self.safe_mt5_data, self.cfg
        )
        if no_trade_reasons:
            reason_str = "\n- ".join(no_trade_reasons)
            trade_conditions.handle_early_exit(
                self, "no-trade", reason_str, notify=self.cfg.telegram.notify_on_early_exit
            )
            self.early_exit = True
            raise SystemExit(f"Điều kiện No-Trade: {reason_str}")

    def _stage_3_prepare_and_upload_images(self) -> None:
        """Giai đoạn 3: Chuẩn bị và upload ảnh."""
        logger.debug("GIAI ĐOẠN 3: Chuẩn bị và upload ảnh.")
        t_up0 = _tnow()
        cache = image_processor.UploadCache.load() if self.cfg.upload.cache_enabled else {}
        self.file_slots = [None] * len(self.paths)
        
        images_changed = False
        total_files = len(self.paths)
        self.steps_upload = total_files

        for i, (path_str, name) in enumerate(zip(self.paths, self.names)):
            if self.stop_event.is_set():
                raise SystemExit("Dừng bởi người dùng trong quá trình chuẩn bị ảnh.")

            self.app.ui_queue.put(lambda i=i: self.app._update_progress(i, total_files + 2))
            self.app.results[i]["status"] = "Đang xử lý..."
            self.app.ui_queue.put(lambda i=i: self.app._update_tree_row(i, "Đang xử lý..."))

            path = Path(path_str)
            remote_name = image_processor.UploadCache.lookup(cache, path)
            file_obj = None

            if remote_name:
                try:
                    logger.debug(f"Tìm thấy trong cache: {name}, đang lấy thông tin file...")
                    file_obj = genai.get_file(remote_name)
                    self.file_slots[i] = file_obj
                    self.app.results[i]["status"] = "Đã cache"
                    self.app.ui_queue.put(lambda i=i: self.app._update_tree_row(i, "Đã cache"))
                    logger.info(f"Đã sử dụng cache cho ảnh: {name}")
                except Exception as e:
                    logger.warning(f"Không thể lấy file từ cache cho {name} ({remote_name}): {e}. Sẽ upload lại.")
                    file_obj = None # Reset để upload lại

            if not file_obj:
                images_changed = True
                self.app.results[i]["status"] = "Đang upload..."
                self.app.ui_queue.put(lambda i=i: self.app._update_tree_row(i, "Đang upload..."))
                
                prepared_path = image_processor.prepare_image(
                    path,
                    optimize=self.cfg.upload.optimize_lossless,
                    image_config=self.cfg.image_processing,
                )
                
                file_obj = image_processor.upload_image_to_gemini(
                    prepared_path, display_name=name
                )

                if file_obj:
                    self.file_slots[i] = file_obj
                    self.uploaded_files.append((file_obj, path_str))
                    if self.cfg.upload.cache_enabled:
                        image_processor.UploadCache.put(cache, path, file_obj.name)
                    self.app.results[i]["status"] = "Đã upload"
                    self.app.ui_queue.put(lambda i=i: self.app._update_tree_row(i, "Đã upload"))
                else:
                    self.app.results[i]["status"] = "Lỗi Upload"
                    self.app.ui_queue.put(lambda i=i: self.app._update_tree_row(i, "Lỗi Upload"))
                    # Có thể dừng hoặc tiếp tục tùy theo yêu cầu
                    raise SystemExit(f"Không thể upload ảnh: {name}")

        if self.cfg.folder.only_generate_if_changed and not images_changed:
            trade_conditions.handle_early_exit(
                self, "no-change", "Ảnh không đổi.", notify=self.cfg.telegram.notify_on_early_exit
            )
            self.early_exit = True
            raise SystemExit("Ảnh không đổi, thoát sớm.")

        if self.cfg.upload.cache_enabled:
            image_processor.UploadCache.save(cache)

        self.app.ui_queue.put(lambda: self.app.ui_status(f"Xử lý {total_files} ảnh xong trong {(_tnow() - t_up0):.2f}s"))

        if self.stop_event.is_set():
            raise SystemExit("Dừng bởi người dùng sau khi upload.")

    def _stage_4_call_ai_model(self) -> bool:
        """
        Giai đoạn 4: Gọi model AI và xử lý kết quả.
        Trả về True nếu thành công, False nếu có lỗi API không thể phục hồi.
        """
        logger.debug("BẮT ĐẦU GIAI ĐOẠN 4: Gọi Model AI")
        self.app.ui_queue.put(lambda: self.app.ui_status("Giai đoạn 4/6: Đang nhận phân tích từ AI..."))

        all_media = [f for f in self.file_slots if f is not None]
        if not all_media:
            logger.error("Không có media nào để gửi đến model. Bỏ qua giai đoạn 4.")
            return True # Không phải lỗi nghiêm trọng, chỉ là không có gì để làm

        prompt_no_entry = self.app.prompt_manager.get_prompts().get("no_entry", "")
        prompt_entry_run = self.app.prompt_manager.get_prompts().get("entry_run", "")

        prompt = prompt_builder.select_prompt(
            self.app, self.cfg, self.safe_mt5_data, prompt_no_entry, prompt_entry_run
        )
        prompt_final = prompt_builder.construct_prompt(
            self.app, prompt, self.mt5_dict, self.context_block, self.paths
        )

        logger.debug(f"--- PROMPT FINAL GỬI ĐẾN AI ---\n{prompt_final}\n--- KẾT THÚC PROMPT ---")

        parts = all_media + [prompt_final]
        t_llm0 = _tnow()
        self.combined_text = ""

        tries = self.cfg.api.tries
        base_delay = self.cfg.api.delay

        if not self.model:
            raise SystemExit("Model chưa được khởi tạo.")

        stream_generator = gemini_service.stream_gemini_response(
            model=self.model, parts=parts, tries=tries, base_delay=base_delay
        )

        self.app.ui_queue.put(lambda: self.app.ui_detail_replace("Đang nhận dữ liệu từ AI..."))

        for chunk in stream_generator:
            if self.stop_event.is_set():
                logger.info("Người dùng đã dừng quá trình nhận dữ liệu AI.")
                if hasattr(stream_generator, "close"):
                    stream_generator.close()
                raise SystemExit("Dừng bởi người dùng trong khi streaming.")

            # Xử lý lỗi streaming một cách an toàn
            if isinstance(chunk, StreamError):
                logger.error(f"Lỗi nghiêm trọng khi streaming từ Gemini: {chunk}")
                error_title = "Lỗi Kết Nối AI"
                error_message = (
                    "Không thể nhận phản hồi từ model AI sau nhiều lần thử.\n\n"
                    "Lý do có thể là:\n"
                    "- Lỗi tạm thời từ dịch vụ của Google AI.\n"
                    "- Vấn đề về kết nối mạng.\n"
                    "- API key không hợp lệ hoặc hết hạn mức.\n\n"
                    f"Chi tiết kỹ thuật:\n{chunk}"
                )
                self.combined_text = f"[LỖI PHÂN TÍCH] {error_message}"
                # Gửi cả hai tác vụ cập nhật UI vào queue
                self.app.ui_queue.put(lambda: self.app.ui_detail_replace(self.combined_text))
                self.app.ui_queue.put(lambda: self.app.show_error_message(error_title, error_message))
                return False # Báo hiệu cho worker biết đã có lỗi

            chunk_text = getattr(chunk, "text", "")
            if chunk_text:
                self.combined_text += chunk_text
                self.app.ui_queue.put(lambda: self.app.ui_detail_replace(self.combined_text))

        if not self.combined_text:
            self.combined_text = "[LỖI PHÂN TÍCH] AI không trả về nội dung nào."
            logger.warning("AI không trả về nội dung nào sau khi stream kết thúc.")

        self.app.ui_queue.put(lambda: self.app.ui_status(f"Model trả lời trong {(_tnow() - t_llm0):.2f}s"))
        self.app.ui_queue.put(lambda: self.app._update_progress(self.steps_upload + 1, self.steps_upload + 2))
        return True

    def _stage_5_execute_or_manage_trades(self) -> None:
        """Giai đoạn 5: Thực thi hoặc quản lý giao dịch."""
        logger.debug("GIAI ĐOẠN 5: Thực thi hoặc quản lý giao dịch.")
        positions = self.safe_mt5_data.get("positions", []) if self.safe_mt5_data else []
        has_active_positions = bool(positions)
        
        if not has_active_positions:
            logger.info("Không có lệnh. Tìm kiếm cơ hội vào lệnh mới.")
            trade_actions.execute_trade_action(self.app, self.combined_text, self.mt5_dict, self.cfg)
        else:
            logger.info(f"Có {len(positions)} lệnh. Thực hiện quản lý.")
            trade_actions.manage_existing_trades(self.app, self.combined_text, self.mt5_dict, self.cfg)

    def _stage_6_finalize_and_cleanup(self) -> None:
        """Giai đoạn 6: Hoàn tất, lưu trữ và dọn dẹp."""
        logger.debug("GIAI ĐOẠN 6: Hoàn tất và dọn dẹp.")
        if not self.early_exit:
            for i in range(len(self.paths)):
                self.app.results[i]["status"] = "Hoàn tất"
                self.app.ui_queue.put(lambda i=i: self.app._update_tree_row(i, "Hoàn tất"))

            self.app.combined_report_text = self.combined_text
            # Tái cấu trúc: Sử dụng lớp MdSaver chuyên dụng
            md_handler.MdSaver.save_report(self.combined_text, self.cfg)
            try:
                # Tái cấu trúc: Sử dụng lớp JsonSaver chuyên dụng
                json_saver = JsonSaver(config=self.cfg)
                images_tf_map = self.app.timeframe_detector.create_images_tf_map(self.names)
                json_saver.save_report(
                    report_text=self.combined_text,
                    images_tf_map=images_tf_map,
                    composed_context_str=self.composed
                )
            except Exception:
                tb_str = traceback.format_exc()
                err_msg = f"Lỗi nghiêm trọng khi lưu ctx_*.json:\n{tb_str}"
                # Sửa lỗi: Thay thế hàm không tồn tại bằng cách gọi phương thức trên app
                self.app.ui_queue.put(lambda: self.app.show_error_message("Lỗi Lưu JSON", err_msg))

            self.app.ui_queue.put(self.app.history_manager.refresh_all_lists)

            # Logic thông báo đã được chuyển vào trade_actions và conditions.py
            # if not self.app.stop_flag:
            #     self.app._maybe_notify_telegram(self.combined_text, saved_path, self.cfg)

        if not self.cfg.upload.cache_enabled and self.cfg.folder.delete_after:
            logger.info(f"Đang xóa {len(self.uploaded_files)} file đã upload (cache bị vô hiệu hóa).")
            for uf, _ in self.uploaded_files:
                try:
                    if genai:
                        genai.delete_file(uf.name)
                        logger.debug(f"Đã xóa file Gemini: {uf.name}")
                except Exception as e:
                    logger.warning(f"Lỗi khi xóa file Gemini '{uf.name}': {e}")
        
        self.app.ui_queue.put(lambda: self.app.ui_progress(0))
        final_state = self.app._finalize_done if not self.app.stop_flag else self.app._finalize_stopped
        self.app.ui_queue.put(final_state)
        logger.debug("Kết thúc AnalysisWorker.run.")
