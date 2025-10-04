from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any, Dict, List

import google.generativeai as genai
from google.api_core import exceptions

from APP.core.trading import actions as trade_actions
from APP.ui.utils import ui_builder

if TYPE_CHECKING:
    from APP.configs.app_config import RunConfig
    from APP.ui.app_ui import AppUI

logger = logging.getLogger(__name__)


def _gen_stream_with_retry(_model: genai.GenerativeModel, _parts: List[Any], tries: int = 5, base_delay: float = 2.0) -> Any:
    """
    Tạo một generator để gọi API Gemini streaming với cơ chế thử lại.
    """
    logger.debug(f"Bắt đầu hàm _gen_stream_with_retry với {tries} lần thử.")
    last_exception = None
    for i in range(tries):
        try:
            response_stream = _model.generate_content(_parts, stream=True, request_options={"timeout": 1200})
            for chunk in response_stream:
                yield chunk
            return
        except exceptions.ResourceExhausted as e:
            last_exception = e
            wait_time = base_delay * (2 ** i)
            logger.warning(f"Lần thử {i+1}: Lỗi ResourceExhausted. Thử lại sau {wait_time:.2f} giây.")
            time.sleep(wait_time)
        except Exception as e:
            last_exception = e
            logger.error(f"Lần thử {i+1}: Lỗi không xác định. Thử lại sau {base_delay:.2f} giây.")
            time.sleep(base_delay)
            base_delay *= 1.7
        
        if i == tries - 1:
            logger.error(f"Tất cả {tries} lần thử đều thất bại.")
            raise last_exception


def stream_gemini_response(app: "AppUI", cfg: "RunConfig", model: genai.GenerativeModel, parts: List[Any], mt5_dict: Dict) -> str:
    """
    Thực hiện gọi API streaming và xử lý các chunk trả về.
    Tách biệt logic gọi API khỏi logic xử lý nghiệp vụ (auto-trade).
    """
    logger.debug("Bắt đầu hàm stream_gemini_response.")
    combined_text = ""
    
    ui_builder.ui_detail_replace(app, "Đang nhận dữ liệu từ AI...")
    stream_generator = _gen_stream_with_retry(model, parts)
    
    for chunk in stream_generator:
        if app.stop_flag:
            logger.info("Người dùng đã dừng quá trình nhận dữ liệu AI.")
            if hasattr(stream_generator, 'close'):
                stream_generator.close()
            raise SystemExit("Dừng bởi người dùng.")

        chunk_text = getattr(chunk, "text", "")
        if chunk_text:
            combined_text += chunk_text
            ui_builder.enqueue(app, lambda: ui_builder.ui_detail_replace(app, combined_text))
            
            # Logic auto-trade sẽ được gọi từ analysis_worker sau khi stream hoàn tất
            # hoặc theo một logic khác, không nằm trong service này.

    logger.debug(f"Kết thúc stream_gemini_response. Tổng độ dài: {len(combined_text)}.")
    return combined_text or "[Không có nội dung trả về]"

__all__ = ["stream_gemini_response"]
