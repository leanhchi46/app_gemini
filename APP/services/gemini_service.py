from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any, Generator, List

import google.generativeai as genai
from google.api_core import exceptions

if TYPE_CHECKING:
    from APP.ui.app_ui import AppUI

logger = logging.getLogger(__name__)


def _call_gemini_with_retry(
    model: genai.GenerativeModel,
    parts: List[Any],
    stream: bool,
    tries: int = 5,
    base_delay: float = 2.0,
) -> Any:
    """
    Gọi API Gemini với cơ chế thử lại (retry) và exponential backoff.
    Hỗ trợ cả chế độ streaming và non-streaming.
    """
    last_exception = None
    for i in range(tries):
        try:
            # API call with a generous timeout
            return model.generate_content(
                parts, stream=stream, request_options={"timeout": 1200}
            )
        except exceptions.ResourceExhausted as e:
            last_exception = e
            wait_time = base_delay * (2**i)
            logger.warning(
                f"Lần thử {i + 1}: Lỗi ResourceExhausted. Thử lại sau {wait_time:.2f}s. Chi tiết: {e}"
            )
            time.sleep(wait_time)
        except Exception as e:
            last_exception = e
            wait_time = base_delay * (i + 1)
            logger.error(
                f"Lần thử {i + 1}: Lỗi không xác định. Thử lại sau {wait_time:.2f}s. Chi tiết: {e}"
            )
            time.sleep(wait_time)

    logger.error(f"Tất cả {tries} lần thử đều thất bại.")
    raise last_exception


def gemini_api_call(model: genai.GenerativeModel, parts: List[Any]) -> str:
    """
    Thực hiện một lệnh gọi non-streaming đến API Gemini để lấy kết quả hoàn chỉnh.
    """
    logger.debug("Thực hiện lệnh gọi non-streaming đến Gemini API.")
    response = _call_gemini_with_retry(model, parts, stream=False)
    return getattr(response, "text", "[Không có nội dung trả về]")


def stream_gemini_response(
    app: AppUI, model: genai.GenerativeModel, parts: List[Any]
) -> Generator[str, None, None]:
    """
    Tạo một generator để stream dữ liệu từ API Gemini.
    Hàm này yield từng chunk text nhận được.
    """
    logger.debug("Bắt đầu stream dữ liệu từ Gemini API.")
    try:
        stream_generator = _call_gemini_with_retry(model, parts, stream=True)
        for chunk in stream_generator:
            if app.stop_flag:
                logger.info("Người dùng đã dừng quá trình nhận dữ liệu AI.")
                if hasattr(stream_generator, "close"):
                    stream_generator.close()
                break

            chunk_text = getattr(chunk, "text", "")
            if chunk_text:
                yield chunk_text
    except Exception as e:
        logger.error(f"Lỗi nghiêm trọng trong quá trình stream: {e}", exc_info=True)
        yield f"\n\n[LỖI STREAM] Đã xảy ra lỗi khi giao tiếp với API: {e}"
