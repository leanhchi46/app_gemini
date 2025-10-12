from __future__ import annotations

import logging
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, TimeoutError, as_completed
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

import google.generativeai as genai

from APP.analysis import context_builder, image_processor, prompt_builder
from APP.core.trading import actions as trade_actions
from APP.core.trading import conditions as trade_conditions
from APP.persistence import md_handler
from APP.persistence.json_handler import JsonSaver
from APP.services import gemini_service, mt5_service
# Cập nhật import để nhận diện lớp lỗi mới
from APP.services.gemini_service import StreamError
from APP.utils import threading_utils
from APP.utils.threading_utils import CancelToken
from APP.utils.safe_data import SafeData

if TYPE_CHECKING:
    from APP.configs.app_config import RunConfig
    from APP.services.news_service import NewsService
    from APP.ui.app_ui import AppUI

logger = logging.getLogger(__name__)


def _tnow() -> float:
    """Trả về thời gian hiện tại với độ chính xác cao."""
    return time.perf_counter()


class AnalysisWorker:
    """
    Lớp điều phối toàn bộ quy trình phân tích, chạy trong một luồng riêng biệt.
    """

    def __init__(
        self,
        app: "AppUI",
        cfg: "RunConfig",
        cancel_token: CancelToken | None = None,
        *,
        session_id: str | None = None,
        stop_event: Any | None = None,
    ):
        """
        Khởi tạo worker với các đối tượng cần thiết.

        Args:
            app (AppUI): Instance của ứng dụng UI chính.
            cfg (RunConfig): Đối tượng cấu hình cho lần chạy này.
            stop_event (threading.Event): Sự kiện để báo hiệu dừng worker.
        """
        self.app = app
        self.cfg = cfg
        self.cancel_token = cancel_token or CancelToken()
        self._legacy_stop_event = stop_event
        self.session_id = session_id or f"session-{int(time.time())}"
        self.news_service: "NewsService" = app.news_service
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

    def _is_cancelled(self) -> bool:
        if self.cancel_token and self.cancel_token.is_cancelled():
            return True
        if self._legacy_stop_event and getattr(self._legacy_stop_event, "is_set", lambda: False)():
            self.cancel_token.cancel()
            return True
        return False

    def _process_and_upload_single_image(
        self,
        path_str: str,
        name: str,
        index: int,
        cache: Dict[str, Any],
        cancel_token: CancelToken,
    ) -> Tuple[int, Optional[Any], Optional[str], Optional[str]]:
        """
        Xử lý và tải lên một ảnh duy nhất. Được thiết kế để chạy trong một luồng riêng.
        Trả về: (index, file_obj, new_status, error_message)
        """
        try:
            if cancel_token.is_cancelled() or self._is_cancelled():
                return index, None, "Bị hủy", None

            self.app.ui_queue.put(lambda: self.app._update_tree_row(index, "Đang xử lý..."))
            path = Path(path_str)
            remote_name = image_processor.UploadCache.lookup(cache, path)
            file_obj = None

            if remote_name:
                try:
                    logger.debug(f"Tìm thấy trong cache: {name}, đang lấy thông tin file...")
                    file_obj = genai.get_file(remote_name)
                    return index, file_obj, "Đã cache", None
                except Exception as e:
                    logger.warning(f"Không thể lấy file từ cache cho {name} ({remote_name}): {e}. Sẽ upload lại.")
                    file_obj = None

            if not file_obj:
                cancel_token.raise_if_cancelled()
                self.app.ui_queue.put(lambda: self.app._update_tree_row(index, "Đang upload..."))
                prepared_path = image_processor.prepare_image(
                    path,
                    optimize=self.cfg.upload.optimize_lossless,
                    image_config=self.cfg.image_processing,
                )
                cancel_token.raise_if_cancelled()
                file_obj = image_processor.upload_image_to_gemini(prepared_path, display_name=name)

                if file_obj:
                    if self.cfg.upload.cache_enabled:
                        image_processor.UploadCache.put(cache, path, file_obj.name)
                    return index, file_obj, "Đã upload", None
                else:
                    return index, None, "Lỗi Upload", f"Không thể upload ảnh: {name}"
        except Exception as e:
            logger.error(f"Lỗi khi xử lý ảnh {name}: {e}", exc_info=True)
            return index, None, "Lỗi Xử Lý", f"Lỗi khi xử lý ảnh {name}: {e}"

    def run(self, cancel_token: CancelToken | None = None) -> dict[str, Any]:
        """
        Phương thức chính để chạy worker.
        Tối ưu hóa bằng cách chạy song song Giai đoạn 2 (Context) và Giai đoạn 3 (Upload).
        """
        logger.debug(f"Bắt đầu AnalysisWorker.run với model: {self.model_name}")
        try:
            if cancel_token:
                self.cancel_token = cancel_token
            if self._is_cancelled():
                return {"status": "cancelled"}

            self._stage_1_initialize_and_validate()
            if self._is_cancelled():
                return {"status": "cancelled"}

            # Chạy song song Giai đoạn 2 và 3
            parallel_stages = [
                (self._execute_stage_2_logic, (), {}),
                (self._execute_stage_3_logic, (), {}),
            ]
            stage_results = threading_utils.run_in_parallel(parallel_stages)

            stage2_success = stage_results.get("_execute_stage_2_logic", False)
            stage3_success = stage_results.get("_execute_stage_3_logic", False)

            if self._is_cancelled():
                return {"status": "cancelled"}

            if not stage2_success or not stage3_success:
                logger.warning("Một trong các giai đoạn song song đã thất bại. Dừng worker.")
                raise SystemExit("Thoát sớm do lỗi ở Giai đoạn 2 hoặc 3.")

            if not self._stage_4_call_ai_model():
                return {"status": "failed"}
            if self._is_cancelled():
                return {"status": "cancelled"}
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
        return {"status": "completed", "early_exit": self.early_exit}

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
            raise SystemExit("Không có ảnh để phân tích.")

        api_key = self.app.api_key_var.get()
        if not api_key:
            self.app.ui_queue.put(lambda: self.app.show_error_message("Lỗi API", "API Key không được tìm thấy."))
            raise SystemExit("API Key không được tìm thấy.")

        self.model = gemini_service.initialize_model(api_key=api_key, model_name=self.model_name)

        if not self.model:
            error_message = f"Không thể khởi tạo model '{self.model_name}'. Vui lòng kiểm tra API key và kết nối mạng."
            self.app.ui_queue.put(lambda: self.app.show_error_message("Lỗi Model", error_message))
            raise SystemExit(f"Lỗi khởi tạo model: {self.model_name}")

    def _execute_stage_2_logic(self) -> bool:
        """
        Thực thi logic của Giai đoạn 2. Trả về True nếu thành công, False nếu thất bại.
        """
        try:
            logger.debug("BẮT ĐẦU GIAI ĐOẠN 2: Xây dựng ngữ cảnh và kiểm tra điều kiện.")
            should_run, no_run_reason = trade_conditions.check_no_run_conditions(
                self.cfg, self.news_service
            )
            if not should_run:
                trade_conditions.handle_early_exit(
                    self, "no-run", no_run_reason, notify=self.cfg.telegram.notify_on_early_exit
                )
                self.early_exit = True
                raise SystemExit(f"Điều kiện No-Run: {no_run_reason}")

            t_ctx0 = _tnow()
            self.app.ui_queue.put(
                lambda: self.app.ui_status("GĐ 2/6: Đang lấy dữ liệu (MT5, Reports) song song...")
            )

            reports_dir = Path(self.app.folder_path.get()) / "Reports"
            context_tasks = [
                (
                    mt5_service.get_market_data_async,
                    (),
                    {
                        "cfg": self.cfg.mt5,
                        "plan": None,
                        "timezone_name": self.cfg.no_run.timezone,
                    },
                ),
                (
                    context_builder.build_historical_context_async,
                    (
                        reports_dir,
                        self.app.results,
                        self.app.timeframe_detector,
                        self.cfg,
                    ),
                    {"budget_chars": max(800, int(self.cfg.context.ctx_limit))},
                ),
            ]

            results = threading_utils.run_in_parallel(context_tasks)

            self.safe_mt5_data = results.get("get_market_data_async")
            historical_context, plan = results.get(
                "build_historical_context_async", (None, None)
            )

            # Lấy dữ liệu tin tức tức thì từ cache của service
            news_analysis = self.news_service.get_news_analysis(self.cfg.mt5.symbol)

            if not self.safe_mt5_data or not self.safe_mt5_data.is_valid():
                raise ValueError("Không thể lấy dữ liệu thị trường hợp lệ từ MT5.")

            if self.safe_mt5_data.raw and news_analysis:
                self.safe_mt5_data.raw["news_analysis"] = news_analysis
                concept_table = context_builder.create_concept_value_table(self.safe_mt5_data)
                self.safe_mt5_data.raw["concept_value_table"] = concept_table

            self.mt5_dict = self.safe_mt5_data.raw
            self.mt5_json_full = self.safe_mt5_data.to_json(indent=2)
            self.context_block = (
                f"\n\n[CONTEXT_COMPOSED]\n{historical_context}"
                if historical_context
                else ""
            )

            self.app.ui_queue.put(lambda: self.app.ui_status(f"GĐ 2/6: Lấy dữ liệu xong ({(_tnow() - t_ctx0):.2f}s)"))

            no_trade_reasons = trade_conditions.check_no_trade_conditions(
                self.safe_mt5_data, self.cfg, self.news_service
            )
            if no_trade_reasons:
                reason_str = "\n- ".join(no_trade_reasons)
                trade_conditions.handle_early_exit(
                    self, "no-trade", reason_str, notify=self.cfg.telegram.notify_on_early_exit
                )
                self.early_exit = True
                raise SystemExit(f"Điều kiện No-Trade: {reason_str}")

            return True
        except SystemExit as e:
            logger.info(f"Giai đoạn 2 thoát sớm: {e}")
            return False
        except TimeoutError:
            error_msg = "Giai đoạn 2 thất bại (Timeout). Terminal MT5 có thể bị treo."
            logger.error(error_msg)
            self.app.ui_queue.put(lambda: self.app.show_error_message("Lỗi MT5", error_msg))
            return False
        except Exception as e:
            tb_str = traceback.format_exc()
            error_msg = f"Lỗi nghiêm trọng trong Giai đoạn 2: {e}\n{tb_str}"
            logger.error(error_msg)
            self.app.ui_queue.put(lambda: self.app.show_error_message("Lỗi Context", error_msg))
            return False

    def _execute_stage_3_logic(self) -> bool:
        """Thực thi logic upload ảnh với TaskGroup `analysis.upload`."""

        try:
            logger.debug("BẮT ĐẦU GIAI ĐOẠN 3: Chuẩn bị và upload ảnh (TaskGroup analysis.upload).")
            t_up0 = _tnow()
            cache = image_processor.UploadCache.load() if self.cfg.upload.cache_enabled else {}
            self.file_slots = [None] * len(self.paths)
            images_changed = False
            total_files = len(self.paths)
            self.steps_upload = total_files
            files_processed = 0

            max_files = min(total_files, 10)
            max_workers = max(1, min(self.cfg.upload.upload_workers, 10))
            manager = self.app.threading_manager
            in_flight: list = []

            def submit_upload(idx: int, path_str: str, name: str) -> None:
                record = manager.submit(
                    func=self._process_and_upload_single_image,
                    args=(path_str, name, idx, cache, self.cancel_token),
                    group="analysis.upload",
                    name=f"analysis.upload.{self.session_id}.{idx}",
                    cancel_token=self.cancel_token,
                    metadata={
                        "component": "analysis",
                        "session_id": self.session_id,
                        "index": idx,
                    },
                )
                in_flight.append(record)

            iterator = list(zip(self.paths[:max_files], self.names[:max_files]))
            for idx, (path_str, name) in enumerate(iterator):
                if self._is_cancelled():
                    manager.cancel_group("analysis.upload")
                    raise SystemExit("Dừng bởi người dùng trong quá trình upload.")
                submit_upload(idx, path_str, name)
                if len(in_flight) >= max_workers:
                    files_processed, images_changed = self._drain_upload_record(
                        in_flight.pop(0), files_processed, total_files, cache, images_changed
                    )

            while in_flight:
                files_processed, images_changed = self._drain_upload_record(
                    in_flight.pop(0), files_processed, total_files, cache, images_changed
                )

            if self.cfg.folder.only_generate_if_changed and not images_changed:
                trade_conditions.handle_early_exit(
                    self, "no-change", "Ảnh không đổi.", notify=self.cfg.telegram.notify_on_early_exit
                )
                self.early_exit = True
                raise SystemExit("Ảnh không đổi, thoát sớm.")

            if self.cfg.upload.cache_enabled:
                image_processor.UploadCache.save(cache)

            self.app.ui_queue.put(lambda: self.app.ui_status(f"GĐ 3/6: Upload xong ({(_tnow() - t_up0):.2f}s)"))
            return True
        except SystemExit as e:
            logger.info(f"Giai đoạn 3 thoát sớm: {e}")
            return False
        except Exception as e:
            error_msg = f"Lỗi nghiêm trọng trong Giai đoạn 3: {e}"
            logger.error(error_msg, exc_info=True)
            self.app.ui_queue.put(lambda: self.app.show_error_message("Lỗi Upload", error_msg))
            return False

    def _drain_upload_record(
        self,
        record,
        files_processed: int,
        total_files: int,
        cache: Dict[str, Any],
        images_changed: bool,
    ) -> tuple[int, bool]:
        if self._is_cancelled():
            raise SystemExit("Dừng bởi người dùng trong quá trình upload.")

        index, file_obj, status, error_msg = record.future.result()
        files_processed += 1
        self.app.ui_queue.put(lambda p=files_processed: self.app._update_progress(p, total_files + 2))

        if status:
            self.app.results[index]["status"] = status
            self.app.ui_queue.put(lambda i=index, s=status: self.app._update_tree_row(i, s))

        if file_obj:
            self.file_slots[index] = file_obj
            if status == "Đã upload":
                images_changed = True
                self.uploaded_files.append((file_obj, self.paths[index]))
        elif error_msg:
            raise RuntimeError(error_msg)

        return files_processed, images_changed

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
            return True

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

        if not self.model:
            raise SystemExit("Model chưa được khởi tạo.")

        stream_generator = gemini_service.stream_gemini_response(
            model=self.model, parts=parts, tries=self.cfg.api.tries, base_delay=self.cfg.api.delay
        )

        self.app.ui_queue.put(lambda: self.app.ui_detail_replace("Đang nhận dữ liệu từ AI..."))

        for chunk in stream_generator:
            if self._is_cancelled():
                if hasattr(stream_generator, "close"): stream_generator.close()
                raise SystemExit("Dừng bởi người dùng trong khi streaming.")

            if isinstance(chunk, StreamError):
                logger.error(f"Lỗi nghiêm trọng khi streaming từ Gemini: {chunk}")
                error_message = f"Không thể nhận phản hồi từ model AI.\n\nChi tiết:\n{chunk}"
                self.combined_text = f"[LỖI PHÂN TÍCH] {error_message}"
                self.app.ui_queue.put(lambda: self.app.ui_detail_replace(self.combined_text))
                self.app.ui_queue.put(lambda: self.app.show_error_message("Lỗi Kết Nối AI", error_message))
                return False

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
            
            self.app.ui_queue.put(lambda: self.app.ui_status("GĐ 6/6: Đang lưu báo cáo song song..."))
            
            json_saver = JsonSaver(config=self.cfg)
            images_tf_map = self.app.timeframe_detector.create_images_tf_map(self.names)

            save_tasks = [
                (md_handler.MdSaver.save_report, (self.combined_text, self.cfg), {}),
                (json_saver.save_report, (), {
                    "report_text": self.combined_text,
                    "images_tf_map": images_tf_map,
                    "composed_context_str": self.composed
                }),
            ]
            
            threading_utils.run_in_parallel(save_tasks)
            logger.info("Đã lưu báo cáo MD và JSON song song.")

            self.app.ui_queue.put(self.app.history_manager.refresh_all_lists)

        if not self.cfg.upload.cache_enabled and self.cfg.folder.delete_after and self.uploaded_files:
            logger.info(f"Đang xóa {len(self.uploaded_files)} file đã upload (song song)...")
            
            def delete_file_worker(file_obj):
                try:
                    if genai:
                        genai.delete_file(file_obj.name)
                        logger.debug(f"Đã xóa file Gemini: {file_obj.name}")
                except Exception as e:
                    logger.warning(f"Lỗi khi xóa file Gemini '{file_obj.name}': {e}")

            with ThreadPoolExecutor(max_workers=self.cfg.upload.upload_workers) as executor:
                for uf, _ in self.uploaded_files:
                    executor.submit(delete_file_worker, uf)

        self.app.ui_queue.put(lambda: self.app.ui_progress(0))
        final_state = self.app._finalize_done if not self.app.stop_flag else self.app._finalize_stopped
        self.app.ui_queue.put(final_state)
        logger.debug("Kết thúc AnalysisWorker.run.")
