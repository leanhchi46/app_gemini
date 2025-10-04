from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Dict, Any, List

if TYPE_CHECKING:
    from APP.configs.app_config import RunConfig
    from APP.ui.app_ui import AppUI
    from APP.utils.safe_data import SafeData

logger = logging.getLogger(__name__)

def select_prompt(
    app: "AppUI",
    cfg: "RunConfig",
    safe_mt5_data: "SafeData",
    prompt_no_entry: str,
    prompt_entry_run: str,
) -> str:
    """
    Chọn prompt thích hợp dựa trên trạng thái giao dịch hiện tại.
    """
    # Logic đơn giản: nếu không có vị thế nào đang mở, sử dụng prompt "no entry".
    # Ngược lại, sử dụng prompt "entry run".
    if safe_mt5_data.positions_total == 0:
        logger.debug("Không có vị thế nào, chọn prompt 'no entry'.")
        return prompt_no_entry
    else:
        logger.debug(f"Có {safe_mt5_data.positions_total} vị thế, chọn prompt 'entry run'.")
        return prompt_entry_run

def construct_prompt(
    app: "AppUI",
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
