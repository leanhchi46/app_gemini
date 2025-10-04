from __future__ import annotations

import logging
import random
import time
from typing import Any, Generator, List

import google.generativeai as genai
from google.api_core import exceptions

# Khởi tạo logger cho service này
logger = logging.getLogger(__name__)

# Hằng số cho việc gọi API
REQUEST_TIMEOUT: int = 1200


def _handle_api_exception(
    e: Exception, attempt: int, tries: int, base_delay: float
) -> None:
    """
    Xử lý lỗi API, ghi log và thực hiện sleep với exponential backoff + jitter.

    Args:
        e: Exception đã xảy ra.
        attempt: Số thứ tự của lần thử (bắt đầu từ 0).
        tries: Tổng số lần thử.
        base_delay: Thời gian chờ cơ bản.
    """
    if isinstance(e, exceptions.ResourceExhausted):
        # Backoff mạnh hơn cho lỗi hết tài nguyên
        wait_time = base_delay * (2**attempt)
        log_level = logging.WARNING
        error_type = "ResourceExhausted"
    else:
        # Backoff từ từ hơn cho các lỗi khác
        wait_time = base_delay * (1.7**attempt)
        log_level = logging.ERROR
        error_type = "Unknown"

    # Thêm jitter để tránh các yêu cầu thử lại đồng thời
    jitter = random.uniform(0, 1)
    total_wait = wait_time + jitter

    logger.log(
        log_level,
        f"Lần thử {attempt + 1}/{tries}: Lỗi API ({error_type}). "
        f"Thử lại sau {total_wait:.2f} giây. Chi tiết: {e}",
    )
    time.sleep(total_wait)


def stream_gemini_response(
    model: genai.GenerativeModel,
    parts: List[Any],
    tries: int = 5,
    base_delay: float = 2.0,
) -> Generator[Any, None, None]:
    """
    Tạo một generator để gọi API Gemini streaming với cơ chế thử lại (retry).

    Hàm này đóng gói logic gọi API, giúp tăng độ ổn định khi gặp lỗi tạm thời.
    Nó sử dụng chiến lược exponential backoff với jitter.

    Args:
        model: Đối tượng GenerativeModel đã được khởi tạo.
        parts: Danh sách các phần nội dung để gửi đến API.
        tries: Số lần thử lại tối đa.
        base_delay: Thời gian chờ cơ bản (tính bằng giây).

    Yields:
        Các chunk dữ liệu từ API trả về.

    Raises:
        Exception: Ném ra lỗi cuối cùng nếu tất cả các lần thử đều thất bại.
    """
    logger.debug(f"Bắt đầu stream tới Gemini API với {tries} lần thử.")
    last_exception: Exception | None = None

    for i in range(tries):
        try:
            response_stream = model.generate_content(
                parts, stream=True, request_options={"timeout": REQUEST_TIMEOUT}
            )
            logger.info(f"Lần thử {i+1}: Kết nối stream tới Gemini API thành công.")
            yield from response_stream
            logger.debug("Stream từ Gemini API hoàn tất.")
            return  # Thoát khỏi hàm khi stream thành công
        except (exceptions.ResourceExhausted, Exception) as e:
            last_exception = e
            _handle_api_exception(e, attempt=i, tries=tries, base_delay=base_delay)

    logger.error(f"Tất cả {tries} lần thử streaming đều thất bại.")
    if last_exception:
        raise last_exception
    raise RuntimeError("Không thể kết nối tới Gemini API sau nhiều lần thử.")


def gemini_api_call(
    model: genai.GenerativeModel,
    parts: List[Any],
    tries: int = 5,
    base_delay: float = 2.0,
) -> str:
    """
    Thực hiện một cuộc gọi API Gemini không streaming với cơ chế thử lại (retry).

    Hàm này hữu ích cho các tác vụ cần toàn bộ phản hồi trước khi xử lý.
    Nó cũng sử dụng chiến lược exponential backoff với jitter.

    Args:
        model: Đối tượng GenerativeModel đã được khởi tạo.
        parts: Danh sách các phần nội dung để gửi đến API.
        tries: Số lần thử lại tối đa.
        base_delay: Thời gian chờ cơ bản (tính bằng giây).

    Returns:
        Nội dung văn bản đầy đủ từ phản hồi của API.

    Raises:
        Exception: Ném ra lỗi cuối cùng nếu tất cả các lần thử đều thất bại.
    """
    logger.debug(f"Bắt đầu gọi Gemini API (non-streaming) với {tries} lần thử.")
    last_exception: Exception | None = None

    for i in range(tries):
        try:
            response = model.generate_content(
                parts, request_options={"timeout": REQUEST_TIMEOUT}
            )
            logger.info(f"Lần thử {i+1}: Gọi Gemini API thành công.")
            return getattr(response, "text", "")
        except (exceptions.ResourceExhausted, Exception) as e:
            last_exception = e
            _handle_api_exception(e, attempt=i, tries=tries, base_delay=base_delay)

    logger.error(f"Tất cả {tries} lần gọi API đều thất bại.")
    if last_exception:
        raise last_exception
    raise RuntimeError("Không thể kết nối tới Gemini API sau nhiều lần thử.")
