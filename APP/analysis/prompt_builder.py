from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Dict, Any, List, Optional

if TYPE_CHECKING:
    from APP.configs.app_config import RunConfig
    from APP.ui.interfaces import AnalysisUi
from APP.utils.safe_data import SafeData

logger = logging.getLogger(__name__)

def select_prompt(
    app: "AnalysisUi",
    cfg: "RunConfig",
    safe_mt5_data: Optional["SafeData"],
    prompt_no_entry: str,
    prompt_entry_run: str,
) -> str:
    """
    Chọn prompt thích hợp dựa trên trạng thái giao dịch hiện tại.

    Cập nhật: Hiện tại, prompt 'no_entry' đã được thiết kế để xử lý cả hai trường hợp
    (có và không có lệnh). Do đó, chúng ta sẽ luôn trả về prompt này.
    Logic cũ được giữ lại dưới dạng comment để tham khảo.
    """
    # Logic mới: Luôn sử dụng prompt_no_entry vì nó có thể xử lý cả hai kịch bản.
    has_positions = False
    if safe_mt5_data:
        positions = safe_mt5_data.get("positions", [])
        if positions:
            has_positions = True

    if has_positions:
        logger.debug("Có vị thế đang mở, chọn prompt 'no_entry' (đã được cập nhật để quản lý lệnh).")
    else:
        logger.debug("Không có vị thế, chọn prompt 'no_entry' để tìm kiếm setup.")

    # Trả về prompt đã được cập nhật, có khả năng xử lý cả hai trường hợp.
    # `prompt_entry_run` có thể sẽ bị loại bỏ trong tương lai.
    return prompt_no_entry

def construct_prompt(
    app: "AnalysisUi",
    prompt: str,
    mt5_dict: Dict[str, Any],
    context_block: str,
    paths: List[str],
) -> str:
    """
    Xây dựng prompt cuối cùng bằng cách kết hợp các thành phần.
    """
    logger.debug("Bắt đầu xây dựng prompt cuối cùng.")
    
    # Thêm thông tin context và MT5 vào prompt
    # (Đây là một cấu trúc ví dụ, có thể cần điều chỉnh)
    final_prompt = f"""
{prompt}

---
**Dữ liệu thị trường và tài khoản (MT5):**
```json
{mt5_dict}
```

---
**Bối cảnh bổ sung từ các báo cáo trước:**
{context_block}

---
**Phân tích các hình ảnh được cung cấp.**
"""
    logger.debug("Đã xây dựng xong prompt cuối cùng.")
    return final_prompt.strip()
