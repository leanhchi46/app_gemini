# -*- coding: utf-8 -*-
"""
Các hàm tiện ích để phân tích và trích xuất thông tin từ các báo cáo văn bản,
đặc biệt là các báo cáo do AI tạo ra và dữ liệu từ MetaTrader 5.

Cải tiến:
- Tối ưu hóa bằng cách biên dịch trước các biểu thức chính quy (regex).
- Tái cấu trúc (refactor) để tăng tính rõ ràng và dễ bảo trì.
- Sử dụng template f-string cho việc tạo báo cáo để mã nguồn sạch hơn.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

# Khởi tạo logger cho module này
logger = logging.getLogger(__name__)

# --- Biểu thức chính quy được biên dịch trước để tối ưu hiệu suất ---
# Sử dụng \b để đảm bảo khớp từ độc lập, tránh dương tính giả
RE_DIRECTION_LONG = re.compile(r'\b(buy|long)\b', re.IGNORECASE)
RE_DIRECTION_SHORT = re.compile(r'\b(sell|short)\b', re.IGNORECASE)

# Regex cho việc trích xuất setup từ văn bản
RE_SETUP_ENTRY = re.compile(r"entry:\s*([\d\.,]+)", re.IGNORECASE)
RE_SETUP_SL = re.compile(r"sl:\s*([\d\.,]+)", re.IGNORECASE)
RE_SETUP_TP1 = re.compile(r"tp1:\s*([\d\.,]+)", re.IGNORECASE)
RE_SETUP_TP2 = re.compile(r"tp2:\s*([\d\.,]+)", re.IGNORECASE)

# Regex để sửa chuỗi JSON
RE_REPAIR_TRAILING_COMMA = re.compile(r",\s*([}\]])")
RE_REPAIR_UNQUOTED_KEYS = re.compile(r"([{,])\s*([a-zA-Z0-9_]+)\s*:")

# Sử dụng TYPE_CHECKING để tránh circular import, chỉ import type hint khi cần
if TYPE_CHECKING:
    from APP.utils.safe_data import SafeData


def parse_float(s: str) -> Optional[float]:
    """
    Phân tích một chuỗi thành số thực (float), xử lý các định dạng khác nhau.
    """
    logger.debug(f"Đang phân tích chuỗi thành float: '{s}'")
    if not isinstance(s, str):
        logger.warning(f"Đầu vào không phải là chuỗi, không thể phân tích: {type(s)}")
        return None
    
    s_cleaned = s.strip().replace(",", "")
    
    try:
        result = float(s_cleaned)
        logger.debug(f"Phân tích thành công: {result}")
        return result
    except ValueError:
        logger.warning(f"Không thể chuyển đổi chuỗi '{s_cleaned}' thành float.")
        return None


def parse_direction_from_line1(line1: str) -> Optional[str]:
    """
    Xác định hướng giao dịch (mua/bán) từ một dòng văn bản bằng regex đã biên dịch.
    """
    logger.debug(f"Đang xác định hướng từ dòng: '{line1}'")
    if RE_DIRECTION_LONG.search(line1):
        logger.debug("Phát hiện hướng 'long'.")
        return "long"
    if RE_DIRECTION_SHORT.search(line1):
        logger.debug("Phát hiện hướng 'short'.")
        return "short"
    
    logger.debug("Không tìm thấy hướng giao dịch trong dòng.")
    return None


def _parse_setup_with_regex(lines: List[str]) -> Dict[str, Any]:
    """
    Hàm phụ trợ: Chỉ thực hiện việc trích xuất setup bằng regex.
    """
    setup: Dict[str, Any] = {}
    for line in lines:
        if "entry:" in line and "entry" not in setup:
            match = RE_SETUP_ENTRY.search(line)
            if match:
                setup["entry"] = parse_float(match.group(1))
        elif "sl:" in line and "sl" not in setup:
            match = RE_SETUP_SL.search(line)
            if match:
                setup["sl"] = parse_float(match.group(1))
        elif "tp1:" in line and "tp1" not in setup:
            match = RE_SETUP_TP1.search(line)
            if match:
                setup["tp1"] = parse_float(match.group(1))
        elif "tp2:" in line and "tp2" not in setup:
            match = RE_SETUP_TP2.search(line)
            if match:
                setup["tp2"] = parse_float(match.group(1))
        elif "direction:" in line and "direction" not in setup:
            setup["direction"] = parse_direction_from_line1(line)
    return setup


def parse_setup_from_report(text: str) -> Dict[str, Any]:
    """
    Trích xuất thông tin cài đặt giao dịch (entry, SL, TP, direction) từ báo cáo.
    """
    logger.debug("Bắt đầu trích xuất cài đặt giao dịch từ báo cáo.")
    
    try:
        json_block = extract_json_block_prefer(text)
        if json_block and not json_block.get("error"):
            plan = json_block.get("proposed_plan")
            if isinstance(plan, dict):
                logger.info("Trích xuất cài đặt thành công từ khối JSON.")
                return plan
    except Exception as e:
        logger.warning(f"Lỗi khi xử lý khối JSON, sẽ chuyển sang dùng regex. Lỗi: {e}")

    logger.debug("Không tìm thấy JSON hợp lệ, đang sử dụng regex để phân tích.")
    lines = text.split("\n")
    setup = _parse_setup_with_regex(lines)

    if "direction" not in setup and lines:
        setup["direction"] = parse_direction_from_line1(lines[0])

    logger.debug(f"Hoàn tất phân tích bằng regex. Cài đặt: {setup}")
    return setup


def _extract_task_content(task_num: int, text: str) -> Optional[str]:
    """
    Hàm phụ trợ: Trích xuất nội dung của một "Nhiệm vụ" cụ thể từ báo cáo.
    """
    pattern = re.compile(f"###\\s*NHIỆM VỤ\\s*{task_num}\\s*(.*?)(?=\\n###|\\Z)", re.DOTALL | re.IGNORECASE)
    match = pattern.search(text)
    return match.group(1).strip() if match else None


def extract_summary_lines(text: str) -> Tuple[List[str], Optional[str], bool]:
    """
    Trích xuất các dòng tóm tắt (Nhiệm vụ 2) và chữ ký (Nhiệm vụ 3) từ báo cáo.
    """
    logger.debug("Bắt đầu trích xuất tóm tắt và chữ ký.")
    summary_lines: List[str] = []
    high_prob: bool = False

    task2_content = _extract_task_content(2, text)
    if task2_content:
        lines = [line.strip() for line in task2_content.split('\n') if line.strip()]
        summary_lines = lines[:7]
        logger.debug(f"Đã trích xuất {len(summary_lines)} dòng tóm tắt từ Nhiệm vụ 2.")

    signature = _extract_task_content(3, text)
    if signature:
        logger.debug(f"Đã trích xuất chữ ký: '{signature}'")
        if "HIGH PROBABILITY" in signature.upper():
            high_prob = True
            logger.debug("Phát hiện 'HIGH PROBABILITY' trong chữ ký.")

    logger.debug(f"Hoàn tất trích xuất. High Prob: {high_prob}")
    return summary_lines, signature, high_prob


def repair_json_string(s: str) -> str:
    """
    Cố gắng sửa một chuỗi JSON không hợp lệ.
    """
    logger.debug("Bắt đầu sửa chuỗi JSON.")
    s = s.strip()

    if not s.startswith("{"):
        s = "{" + s
    if not s.endswith("}"):
        s = s + "}"

    s = RE_REPAIR_TRAILING_COMMA.sub(r"\1", s)
    s = RE_REPAIR_UNQUOTED_KEYS.sub(r'\1"\2":', s)

    try:
        json.loads(s)
        logger.debug("Chuỗi JSON hợp lệ sau khi sửa.")
        return s
    except json.JSONDecodeError:
        logger.warning("Không thể sửa chữa hoàn toàn chuỗi JSON.")
        return s


def find_balanced_json_after(text: str, start_idx: int) -> Tuple[Optional[str], Optional[int]]:
    """
    Tìm một khối JSON cân bằng (số lượng '{' và '}' bằng nhau) trong văn bản.
    """
    logger.debug(f"Đang tìm khối JSON cân bằng từ vị trí {start_idx}.")
    brace_count = 0
    in_string = False
    escape = False
    json_start = -1

    for i in range(start_idx, len(text)):
        char = text[i]
        if json_start == -1 and char == '{':
            json_start = i
        if json_start != -1:
            if char == '"' and not escape:
                in_string = not in_string
            elif char == '\\':
                escape = not escape
            else:
                escape = False
            if not in_string:
                if char == '{':
                    brace_count += 1
                elif char == '}':
                    brace_count -= 1
            if brace_count == 0:
                json_str = text[json_start : i + 1]
                logger.debug(f"Tìm thấy khối JSON cân bằng dài {len(json_str)} ký tự.")
                return json_str, i + 1
    
    logger.debug("Không tìm thấy khối JSON cân bằng.")
    return None, None


def extract_json_block_prefer(text: str) -> Dict[str, Any]:
    """
    Trích xuất khối JSON từ văn bản, ưu tiên khối lớn nhất và hợp lệ nhất.
    """
    logger.debug("Bắt đầu trích xuất khối JSON ưu tiên.")
    possible_blocks = []
    search_idx = 0
    while search_idx < len(text):
        start_brace = text.find('{', search_idx)
        if start_brace == -1:
            break
        json_str, end_idx = find_balanced_json_after(text, start_brace)
        if json_str and end_idx:
            possible_blocks.append(json_str)
            search_idx = end_idx
        else:
            search_idx = start_brace + 1

    possible_blocks.sort(key=len, reverse=True)

    for block in possible_blocks:
        try:
            repaired = repair_json_string(block)
            data = json.loads(repaired)
            if isinstance(data, dict):
                logger.info("Trích xuất và phân tích JSON thành công.")
                return data
        except json.JSONDecodeError:
            logger.debug("Khối JSON không hợp lệ, thử khối tiếp theo.")
            continue
            
    logger.warning("Không tìm thấy khối JSON hợp lệ nào trong văn bản.")
    return {"error": "No valid JSON block found"}


def _generate_positions_report(positions: List[Dict[str, Any]]) -> str:
    """Hàm phụ trợ: Tạo phần báo cáo cho các lệnh đang mở."""
    if not positions:
        return ""
    header = "\n--- LỆNH ĐANG MỞ ---"
    lines = [
        f"- {'BUY' if p.get('type') == 0 else 'SELL'} {p.get('volume')} tại {p.get('price_open')} | SL: {p.get('sl')} | TP: {p.get('tp')} | PnL: {p.get('profit', 0.0):.2f}"
        for p in positions
    ]
    return "\n".join([header] + lines)


def _generate_key_levels_report(data: Dict[str, Any]) -> str:
    """Hàm phụ trợ: Tạo phần báo cáo cho các mức giá quan trọng."""
    lines = ["\n--- CÁC MỨC GIÁ QUAN TRỌNG ---"]
    daily = data.get("levels", {}).get("daily", {})
    lines.append(f"Daily: Open={daily.get('open', 'N/A')}, High={daily.get('high', 'N/A')}, Low={daily.get('low', 'N/A')}")
    
    nearby_levels = data.get("key_levels_nearby", [])
    if nearby_levels:
        lines.append("Các mức cản gần nhất:")
        lines.extend([
            f"- {level.get('name')}: {level.get('price')} (cách {level.get('distance_pips', 0.0):.2f} pips)"
            for level in nearby_levels
        ])
    return "\n".join(lines)


def _generate_ict_report(ict_patterns: Dict[str, Any]) -> str:
    """Hàm phụ trợ: Tạo phần báo cáo cho các mẫu hình ICT."""
    if not ict_patterns:
        return ""
    lines = [f"- {p}: {v}" for p, v in ict_patterns.items() if v]
    if not lines:
        return ""
    return "\n".join(["\n--- PHÂN TÍCH ICT ---"] + lines)


def parse_mt5_data_to_report(safe_mt5_data: SafeData) -> str:
    """
    Chuyển đổi đối tượng SafeData thành một báo cáo văn bản có cấu trúc.
    """
    logger.debug("Bắt đầu chuyển đổi dữ liệu MT5 thành báo cáo.")
    if not safe_mt5_data or not safe_mt5_data.raw:
        logger.warning("Dữ liệu MT5 đầu vào trống.")
        return "Không có dữ liệu MT5."

    data = safe_mt5_data.raw
    account = data.get("account", {})
    
    broker_tz_str = "Asia/Ho_Chi_Minh" # Mặc định
    broker_time_iso = data.get('broker_time')
    if broker_time_iso:
        try:
            # Chuyển đổi chuỗi ISO thành đối tượng datetime và lấy tên múi giờ
            dt_obj = datetime.fromisoformat(broker_time_iso.replace("Z", "+00:00"))
            if dt_obj.tzinfo:
                broker_tz_str = dt_obj.tzinfo.tzname(None) or broker_tz_str
        except (ValueError, AttributeError):
            logger.warning(f"Không thể phân tích múi giờ từ broker_time: {broker_time_iso}")


    report_template = f"""--- DỮ LIỆU THỊ TRƯỜNG (MT5) ---
Symbol: {data.get('symbol', 'N/A')}
Thời gian Broker: {data.get('broker_time', 'N/A')}
Giá Bid hiện tại: {safe_mt5_data.get_tick_value('bid', 'N/A')}
Spread (points): {safe_mt5_data.get_info_value('spread_current', 'N/A')}
ATR M5 (pips): {safe_mt5_data.get_atr_pips('M5', 0.0):.2f}
Vị trí trong biên độ ngày: {data.get('position_in_day_range', 0.0):.2f}
Phiên giao dịch: {safe_mt5_data.get_active_session(tz=broker_tz_str) or 'N/A'}
Phân tích tin tức: {data.get('news_analysis', {}).get('reason', 'Không có tin tức')}

--- TÀI KHOẢN ---
Số dư: {account.get('balance', 0.0):.2f} {account.get('currency', '')}
Vốn chủ sở hữu: {account.get('equity', 0.0):.2f}
Ký quỹ tự do: {account.get('free_margin', 0.0):.2f}{_generate_positions_report(data.get("positions", []))}{_generate_key_levels_report(data)}{_generate_ict_report(data.get("ict_patterns", {}))}
"""
    final_report = report_template.strip()
    logger.debug(f"Hoàn tất tạo báo cáo MT5, độ dài: {len(final_report)} ký tự.")
    return final_report
