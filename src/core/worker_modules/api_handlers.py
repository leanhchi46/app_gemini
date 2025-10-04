from __future__ import annotations
import time
import logging # Thêm import logging
from typing import TYPE_CHECKING, List, Dict, Any

import google.generativeai as genai
from google.api_core import exceptions

from src.core.worker_modules import trade_actions # Cập nhật import
from src.utils import ui_utils # Cần cho ui_detail_replace, ui_status, _enqueue

logger = logging.getLogger(__name__) # Khởi tạo logger

if TYPE_CHECKING:
    from scripts.tool import TradingToolApp
    from src.config.config import RunConfig

def _gen_stream_with_retry(_model: genai.GenerativeModel, _parts: List[Any], tries: int = 5, base_delay: float = 2.0) -> Any:
    """
    Tạo một generator để gọi API Gemini streaming với cơ chế thử lại (retry).
    Cơ chế này giúp tăng độ ổn định khi gặp lỗi tạm thời từ API.
    Sử dụng chiến lược exponential backoff: thời gian chờ tăng gấp đôi sau mỗi lần thất bại.
    """
    logger.debug(f"Bắt đầu hàm _gen_stream_with_retry với {tries} lần thử, base_delay: {base_delay}.")
    last_exception = None
    for i in range(tries):
        try:
            response_stream = _model.generate_content(_parts, stream=True, request_options={"timeout": 1200})
            logger.debug(f"Lần thử {i+1}: Bắt đầu stream từ Gemini API.")
            for chunk in response_stream:
                yield chunk
            logger.debug("Stream từ Gemini API hoàn tất thành công.")
            return  # Thoát khỏi hàm khi stream thành công
        except exceptions.ResourceExhausted as e:
            last_exception = e
            wait_time = base_delay * (2 ** i)
            logger.warning(f"Lần thử {i+1}: Lỗi ResourceExhausted. Thử lại sau {wait_time:.2f} giây. Chi tiết: {e}")
            time.sleep(wait_time)
        except Exception as e:
            last_exception = e
            # Đối với các lỗi khác, tăng thời gian chờ một cách từ từ hơn
            logger.error(f"Lần thử {i+1}: Lỗi không xác định khi gọi Gemini API. Thử lại sau {base_delay:.2f} giây. Chi tiết: {e}")
            time.sleep(base_delay)
            base_delay *= 1.7
        
        if i == tries - 1:
            logger.error(f"Tất cả {tries} lần thử đều thất bại. Ném ra lỗi cuối cùng.")
            logger.debug("Kết thúc hàm _gen_stream_with_retry (thất bại).")
            raise last_exception # Ném ra lỗi cuối cùng nếu tất cả các lần thử đều thất bại

def stream_and_process_ai_response(app: "TradingToolApp", cfg: "RunConfig", model: genai.GenerativeModel, parts: List[Any], mt5_dict: Dict) -> str:
    """
    Thực hiện gọi API streaming, xử lý các chunk trả về, và kích hoạt auto-trade.
    """
    logger.debug("Bắt đầu hàm stream_and_process_ai_response.")
    combined_text = ""
    trade_action_taken = False
    
    ui_utils.ui_detail_replace(app, "Đang nhận dữ liệu từ AI...")
    stream_generator = _gen_stream_with_retry(model, parts)
    
    for chunk in stream_generator:
        if app.stop_flag:
            logger.info("Người dùng đã dừng quá trình nhận dữ liệu AI.")
            if hasattr(stream_generator, 'close'):
                stream_generator.close()
            raise SystemExit("Người dùng đã dừng quá trình nhận dữ liệu AI.")

        chunk_text = getattr(chunk, "text", "")
        if chunk_text:
            combined_text += chunk_text
            # Cập nhật UI trên luồng chính để tránh xung đột
            ui_utils._enqueue(app, lambda: ui_utils.ui_detail_replace(app, combined_text))
            logger.debug(f"Đã nhận chunk từ AI. Độ dài hiện tại: {len(combined_text)}.")

            # TÁC DỤNG PHỤ QUAN TRỌNG: Auto-trade được kích hoạt ngay tại đây
            # với từng phần nhỏ của câu trả lời từ AI.
            if not trade_action_taken and cfg.auto_trade_enabled:
                logger.debug("Auto-trade enabled và chưa có hành động, thử kích hoạt auto-trade.")
                try:
                    action_was_taken = trade_actions.auto_trade_if_high_prob(app, combined_text, mt5_dict, cfg) # Cập nhật lệnh gọi
                    if action_was_taken:
                        trade_action_taken = True
                        app.ui_status("Auto-Trade: Đã thực hiện hành động từ stream.")
                        logger.info("Auto-Trade: Đã thực hiện hành động từ stream thành công.")
                except Exception as e:
                    app.ui_status(f"Lỗi Auto-Trade stream: {e}")
                    logger.error(f"Lỗi Auto-Trade stream: {e}")
    
    logger.debug(f"Kết thúc hàm stream_and_process_ai_response. Tổng độ dài văn bản: {len(combined_text)}.")
    return combined_text or "[Không có nội dung trả về]"
