from __future__ import annotations
import time
from typing import TYPE_CHECKING, List, Dict, Any

import google.generativeai as genai
from google.api_core import exceptions

from src.core import auto_trade # Cần cho auto_trade_if_high_prob
from src.utils import ui_utils # Cần cho ui_detail_replace, ui_status, _enqueue

if TYPE_CHECKING:
    from scripts.tool import TradingToolApp
    from src.config.config import RunConfig

def _gen_stream_with_retry(_model: genai.GenerativeModel, _parts: List[Any], tries: int = 5, base_delay: float = 2.0) -> Any:
    """
    Tạo một generator để gọi API Gemini streaming với cơ chế thử lại (retry).
    Cơ chế này giúp tăng độ ổn định khi gặp lỗi tạm thời từ API.
    Sử dụng chiến lược exponential backoff: thời gian chờ tăng gấp đôi sau mỗi lần thất bại.
    """
    last_exception = None
    for i in range(tries):
        try:
            response_stream = _model.generate_content(_parts, stream=True, request_options={"timeout": 1200})
            for chunk in response_stream:
                yield chunk
            return  # Thoát khỏi hàm khi stream thành công
        except exceptions.ResourceExhausted as e:
            last_exception = e
            wait_time = base_delay * (2 ** i)
            print(f"Cảnh báo: Lỗi ResourceExhausted. Thử lại sau {wait_time:.2f} giây...")
            time.sleep(wait_time)
        except Exception as e:
            last_exception = e
            # Đối với các lỗi khác, tăng thời gian chờ một cách từ từ hơn
            time.sleep(base_delay)
            base_delay *= 1.7
        
        if i == tries - 1:
            raise last_exception # Ném ra lỗi cuối cùng nếu tất cả các lần thử đều thất bại

def stream_and_process_ai_response(app: "TradingToolApp", cfg: "RunConfig", model: genai.GenerativeModel, parts: List[Any], mt5_dict: Dict) -> str:
    """
    Thực hiện gọi API streaming, xử lý các chunk trả về, và kích hoạt auto-trade.
    """
    combined_text = ""
    trade_action_taken = False
    
    ui_utils.ui_detail_replace(app, "Đang nhận dữ liệu từ AI...")
    stream_generator = _gen_stream_with_retry(model, parts)
    
    for chunk in stream_generator:
        if app.stop_flag:
            if hasattr(stream_generator, 'close'):
                stream_generator.close()
            raise SystemExit("Người dùng đã dừng quá trình nhận dữ liệu AI.")

        chunk_text = getattr(chunk, "text", "")
        if chunk_text:
            combined_text += chunk_text
            # Cập nhật UI trên luồng chính để tránh xung đột
            ui_utils._enqueue(app, lambda: ui_utils.ui_detail_replace(app, combined_text))

            # TÁC DỤNG PHỤ QUAN TRỌNG: Auto-trade được kích hoạt ngay tại đây
            # với từng phần nhỏ của câu trả lời từ AI.
            if not trade_action_taken and cfg.auto_trade_enabled:
                try:
                    action_was_taken = auto_trade.auto_trade_if_high_prob(app, combined_text, mt5_dict, cfg)
                    if action_was_taken:
                        trade_action_taken = True
                        app.ui_status("Auto-Trade: Đã thực hiện hành động từ stream.")
                except Exception as e:
                    app.ui_status(f"Lỗi Auto-Trade stream: {e}")
    
    return combined_text or "[Không có nội dung trả về]"
