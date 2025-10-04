from __future__ import annotations
import json
import re
import logging
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


def parse_float(s: str) -> Optional[float]:
    """Phân tích một chuỗi thành số thực (float), hỗ trợ dấu phẩy."""
    if not isinstance(s, str):
        return None
    try:
        return float(s.strip().replace(",", ""))
    except ValueError:
        return None


def parse_direction_from_line(line: str) -> Optional[str]:
    """Phân tích hướng 'long' hoặc 'short' từ một dòng văn bản."""
    line_lower = line.lower()
    if "buy" in line_lower or "long" in line_lower:
        return "long"
    if "sell" in line_lower or "short" in line_lower:
        return "short"
    return None


def parse_trade_setup_from_report(text: str) -> Dict[str, Any]:
    """
    Trích xuất thông tin setup giao dịch (entry, SL, TP, direction) từ báo cáo.
    Ưu tiên trích xuất từ khối JSON, sau đó fallback sang phân tích văn bản.
    """
    try:
        json_block = extract_json_block(text)
        if json_block and isinstance(json_block.get("proposed_plan"), dict):
            return json_block["proposed_plan"]
    except Exception:
        pass  # Fallback to regex parsing

    setup: Dict[str, Any] = {}
    lines = text.split("\n")
    for line in lines:
        line_lower = line.lower()
        if "entry:" in line_lower and "entry" not in setup:
            match = re.search(r"entry:\s*([\d\.,]+)", line_lower)
            if match:
                setup["entry"] = parse_float(match.group(1))
        elif "sl:" in line_lower and "sl" not in setup:
            match = re.search(r"sl:\s*([\d\.,]+)", line_lower)
            if match:
                setup["sl"] = parse_float(match.group(1))
        elif "tp1:" in line_lower and "tp1" not in setup:
            match = re.search(r"tp1:\s*([\d\.,]+)", line_lower)
            if match:
                setup["tp1"] = parse_float(match.group(1))
        elif "tp2:" in line_lower and "tp2" not in setup:
            match = re.search(r"tp2:\s*([\d\.,]+)", line_lower)
            if match:
                setup["tp2"] = parse_float(match.group(1))

    if not setup.get("direction") and lines:
        setup["direction"] = parse_direction_from_line(lines[0])

    return setup


def extract_summary_lines(text: str) -> Tuple[List[str], Optional[str], bool]:
    """Trích xuất 7 dòng tóm tắt và xác định 'HIGH PROBABILITY'."""
    summary_lines: List[str] = []
    signature: Optional[str] = None
    high_prob = False

    task2_match = re.search(r"###\s*NHIỆM VỤ 2\s*(.*?)(?=\n###|\Z)", text, re.DOTALL | re.IGNORECASE)
    if task2_match:
        content = task2_match.group(1).strip()
        summary_lines = [line.strip() for line in content.split('\n') if line.strip()][:7]

    task3_match = re.search(r"###\s*NHIỆM VỤ 3\s*(.*?)(?=\n###|\Z)", text, re.DOTALL | re.IGNORECASE)
    if task3_match:
        signature = task3_match.group(1).strip()
        if "HIGH PROBABILITY" in signature.upper():
            high_prob = True
            
    return summary_lines, signature, high_prob


def _repair_json_string(s: str) -> str:
    """Cố gắng sửa một chuỗi JSON không hợp lệ."""
    s = s.strip()
    if not s.startswith("{"):
        s = "{" + s
    if not s.endswith("}"):
        s = s + "}"
    s = re.sub(r",\s*}", "}", s)
    s = re.sub(r",\s*]", "]", s)
    return s


def extract_json_block(text: str) -> Dict[str, Any]:
    """Trích xuất khối JSON lớn nhất và hợp lệ từ văn bản."""
    json_blocks = []
    start_idx = 0
    while (brace_idx := text.find("{", start_idx)) != -1:
        brace_count = 0
        in_string = False
        for i in range(brace_idx, len(text)):
            char = text[i]
            if char == '"':
                in_string = not in_string
            elif not in_string:
                if char == '{':
                    brace_count += 1
                elif char == '}':
                    brace_count -= 1
            if brace_count == 0:
                json_blocks.append(text[brace_idx : i + 1])
                break
        start_idx = brace_idx + 1

    json_blocks.sort(key=len, reverse=True)

    for block in json_blocks:
        try:
            return json.loads(_repair_json_string(block))
        except json.JSONDecodeError:
            continue
            
    return {"error": "No valid JSON block found"}


def parse_management_from_report(report: str) -> Dict:
    """
    Phân tích báo cáo để trích xuất các chỉ thị quản lý lệnh.
    Ví dụ: [MANAGE] {"ticket": 12345, "action": "CLOSE"}
    Ví dụ: [MANAGE] {"ticket": "ALL", "sl": 1.2345}
    """
    logger.debug("Bắt đầu phân tích chỉ thị quản lý từ báo cáo.")
    management_actions = {}
    
    # Sử dụng regex để tìm tất cả các khối [MANAGE]
    manage_blocks = re.findall(r"\[MANAGE\]\s*({.*?})", report, re.DOTALL)
    
    for block_str in manage_blocks:
        try:
            action = json.loads(block_str)
            ticket = action.get("ticket")
            if not ticket:
                continue
                
            # Chuẩn hóa ticket thành chuỗi để dùng làm key
            ticket_key = str(ticket)
            management_actions[ticket_key] = {
                "action": action.get("action"),
                "sl": parse_float(str(action.get("sl"))) if action.get("sl") is not None else None,
                "tp": parse_float(str(action.get("tp"))) if action.get("tp") is not None else None
            }
            logger.info(f"Đã tìm thấy chỉ thị quản lý cho ticket {ticket_key}: {management_actions[ticket_key]}")

        except json.JSONDecodeError:
            logger.warning(f"Lỗi giải mã JSON trong khối quản lý: {block_str}")
        except Exception as e:
            logger.error(f"Lỗi không xác định khi phân tích khối quản lý: {e}")
            
    return management_actions


__all__ = [
    "parse_trade_setup_from_report", 
    "extract_summary_lines", 
    "extract_json_block",
    "parse_management_from_report"
]
