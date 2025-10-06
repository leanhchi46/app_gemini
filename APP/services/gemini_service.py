from __future__ import annotations

import logging
import random
import time
from typing import Any, Generator, List, Optional, Union

# Sửa lỗi pyright bằng cách import từ các submodule cụ thể theo gợi ý
from google.generativeai.client import configure
from google.generativeai.generative_models import GenerativeModel
from google.generativeai.models import list_models
from google.api_core import exceptions

# Khởi tạo logger cho service này
logger = logging.getLogger(__name__)

# Hằng số cho việc gọi API
REQUEST_TIMEOUT: int = 1200


class StreamError:
    """Lớp tùy chỉnh để biểu diễn lỗi trong quá trình streaming."""
    def __init__(self, message: str, exception: Exception | None = None):
        self.message = message
        self.exception = exception

    def __str__(self) -> str:
        if self.exception:
            return f"StreamError: {self.message} (Caused by: {self.exception})"
        return f"StreamError: {self.message}"


def initialize_model(api_key: str, model_name: str) -> Optional[GenerativeModel]:
    """
    Khởi tạo GenerativeModel với API key được cung cấp.

    Args:
        api_key: Khóa API của Google AI.
        model_name: Tên của model cần khởi tạo.

    Returns:
        Một instance của GenerativeModel nếu thành công, ngược lại trả về None.
    """
    if not api_key:
        logger.error("Không thể khởi tạo model: API key bị thiếu.")
        return None
    try:
        # Cấu hình API key trước khi khởi tạo model.
        # Đây là cách làm đúng và an toàn, thay vì gán trực tiếp vào client.
        configure(api_key=api_key)

        # Khởi tạo model sau khi đã cấu hình.
        model = GenerativeModel(model_name=model_name)

        logger.info(f"Đã khởi tạo model '{model_name}' thành công.")
        return model
    except exceptions.PermissionDenied as e:
        # Bắt lỗi cụ thể hơn để cung cấp thông báo hữu ích
        logger.error(f"Lỗi quyền API (PermissionDenied) khi khởi tạo model '{model_name}': {e}. Vui lòng kiểm tra API key.")
        return None
    except Exception as e:
        logger.exception(f"Lỗi không mong muốn khi khởi tạo model '{model_name}': {e}")
        return None


def configure_and_get_models(api_key: str) -> List[str]:
    """
    Cấu hình API và lấy danh sách các model hỗ trợ 'generateContent'.

    Args:
        api_key: Khóa API của Google AI.

    Returns:
        Một danh sách tên các model khả dụng.
    """
    if not api_key:
        logger.warning("API key bị thiếu, không thể lấy danh sách model.")
        return []
    try:
        configure(api_key=api_key)
        available_models = [
            m.name
            for m in list_models()
            if "generateContent" in m.supported_generation_methods
        ]
        logger.info(f"Đã tìm thấy {len(available_models)} model khả dụng.")
        return available_models
    except exceptions.PermissionDenied as e:
        logger.error(f"Lỗi quyền API (PermissionDenied): {e}. Vui lòng kiểm tra API key.")
        # Ném lại lỗi để UI có thể xử lý cụ thể
        raise
    except Exception as e:
        logger.exception(f"Lỗi không mong muốn khi lấy danh sách model: {e}")
        return []


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
    model: Any,
    parts: List[Any],
    tries: int = 5,
    base_delay: float = 2.0,
) -> Generator[Union[Any, StreamError], None, None]:
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
    # Thay vì ném lỗi, yield một đối tượng StreamError để worker có thể xử lý.
    # Điều này giúp worker không bị crash và có thể tiếp tục vòng lặp.
    if last_exception:
        yield StreamError(
            message=f"Tất cả {tries} lần thử streaming đều thất bại.",
            exception=last_exception
        )
    else:
        yield StreamError(
            message="Không thể kết nối tới Gemini API sau nhiều lần thử mà không có lỗi cụ thể."
        )


def gemini_api_call(
    model: Any,
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
            # Cải tiến: Thay vì dùng getattr, truy cập trực tiếp vào parts để an toàn hơn
            # và tương thích với các phiên bản API trong tương lai.
            if response and response.parts:
                return "".join(part.text for part in response.parts if hasattr(part, "text"))
            return ""
        except (exceptions.ResourceExhausted, Exception) as e:
            last_exception = e
            _handle_api_exception(e, attempt=i, tries=tries, base_delay=base_delay)

    logger.error(f"Tất cả {tries} lần gọi API đều thất bại.")
    if last_exception:
        raise last_exception
    raise RuntimeError("Không thể kết nối tới Gemini API sau nhiều lần thử.")
