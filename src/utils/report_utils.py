# src/utils/report_utils.py
from __future__ import annotations

import json
import re
from typing import Any, Optional


def find_balanced_json_after(text: str, start_idx: int) -> Optional[str]:
    """
    Tìm và trích xuất một khối JSON cân bằng (balanced JSON block) từ một chuỗi văn bản,
    bắt đầu từ một chỉ mục cụ thể.
    """
    balance = 0
    in_string = False
    escape_char = False
    start_json = -1

    for i in range(start_idx, len(text)):
        char = text[i]

        if in_string:
            if escape_char:
                escape_char = False
            elif char == '\\':
                escape_char = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char == '{':
            if start_json == -1:
                start_json = i
            balance += 1
        elif char == '}':
            balance -= 1
            if balance == 0 and start_json != -1:
                return text[start_json : i + 1]
    return None

def extract_json_block_prefer(text: str) -> Optional[dict[str, Any]]:
    """
    Trích xuất khối JSON từ một chuỗi văn bản, ưu tiên các khối JSON hoàn chỉnh và hợp lệ.
    """
    # Tìm tất cả các khối JSON có thể có
    json_blocks = []
    for match in re.finditer(r"\{", text):
        start_idx = match.start()
        balanced_json = find_balanced_json_after(text, start_idx)
        if balanced_json:
            json_blocks.append(balanced_json)

    # Ưu tiên khối JSON lớn nhất và hợp lệ
    best_json = None
    best_len = -1
    for block in json_blocks:
        try:
            data = json.loads(block)
            if len(block) > best_len:
                best_json = data
                best_len = len(block)
        except json.JSONDecodeError:
            continue
    return best_json

def coerce_setup_from_json(obj: dict[str, Any]) -> dict[str, Any]:
    """
    Chuyển đổi một đối tượng Python (thường là từ JSON) thành đối tượng TradeSetup.
    Đảm bảo các trường cần thiết có mặt và đúng định dạng.
    """
    # Đây là một hàm giữ chỗ. Logic thực tế sẽ phức tạp hơn.
    # Nó sẽ cần kiểm tra và chuyển đổi các trường như 'direction', 'entry', 'stop_loss', 'take_profit'
    # từ các giá trị thô trong obj sang định dạng mong muốn của TradeSetup.
    # Ví dụ:
    # setup = {
    #     "direction": obj.get("direction", "").upper(),
    #     "entry": float(obj.get("entry", 0.0)),
    #     "stop_loss": float(obj.get("stop_loss", 0.0)),
    #     "take_profit": float(obj.get("take_profit", 0.0)),
    #     ...
    # }
    # return setup
    return obj # Tạm thời trả về obj gốc

def parse_float(s: str) -> float:
    """
    Phân tích một chuỗi thành số thực (float).
    Xử lý các trường hợp có dấu phẩy hoặc khoảng trắng.
    """
    s = s.replace(",", ".").strip()
    try:
        return float(s)
    except ValueError:
        return 0.0

def parse_direction_from_line1(line1: str) -> str:
    """
    Phân tích hướng giao dịch (Buy/Sell) từ dòng đầu tiên của báo cáo.
    """
    line1_upper = line1.upper()
    if "BUY" in line1_upper:
        return "BUY"
    if "SELL" in line1_upper:
        return "SELL"
    return ""
