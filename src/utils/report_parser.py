from __future__ import annotations
import json
import re
import logging # Thêm import logging
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

logger = logging.getLogger(__name__) # Khởi tạo logger

if TYPE_CHECKING:
    from src.utils.safe_data import SafeMT5Data


def parse_float(s: str) -> Optional[float]:
    """
    Phân tích một chuỗi thành số thực (float).
    Hỗ trợ các định dạng số có dấu phẩy hoặc dấu chấm thập phân.

    Args:
        s: Chuỗi cần phân tích.

    Returns:
        Giá trị float hoặc None nếu không thể phân tích.
    """
    logger.debug(f"Bắt đầu parse_float cho chuỗi: '{s}'")
    if not isinstance(s, str):
        logger.debug("Input không phải chuỗi, trả về None.")
        return None
    s = s.strip().replace(",", "") # Loại bỏ dấu phẩy
    try:
        result = float(s)
        logger.debug(f"Đã parse float thành công: {result}")
        return result
    except ValueError:
        logger.warning(f"Không thể parse '{s}' thành float.")
        return None


def parse_direction_from_line1(line1: str) -> Optional[str]:
    """
    Phân tích hướng giao dịch (Buy/Sell) từ dòng đầu tiên của báo cáo.

    Args:
        line1: Dòng đầu tiên của báo cáo.

    Returns:
        "long" hoặc "short" hoặc None nếu không xác định được.
    """
    logger.debug(f"Bắt đầu parse_direction_from_line1 cho dòng: '{line1}'")
    line1_lower = line1.lower()
    if "buy" in line1_lower or "long" in line1_lower:
        logger.debug("Hướng lệnh là 'long'.")
        return "long"
    if "sell" in line1_lower or "short" in line1_lower:
        logger.debug("Hướng lệnh là 'short'.")
        return "short"
    logger.debug("Không xác định được hướng lệnh, trả về None.")
    return None


def parse_setup_from_report(text: str) -> Dict[str, Any]:
    """
    Phân tích báo cáo để trích xuất các thông số setup giao dịch (entry, SL, TP).

    Args:
        text: Nội dung báo cáo.

    Returns:
        Một từ điển chứa các thông số setup.
    """
    logger.debug("Bắt đầu parse_setup_from_report.")
    setup: Dict[str, Any] = {}
    
    # Cố gắng trích xuất từ JSON trước
    try:
        json_block = extract_json_block_prefer(text)
        if json_block and not json_block.get("error"):
            plan = json_block.get("proposed_plan")
            if plan:
                setup = plan
                logger.debug("Đã trích xuất setup từ JSON block.")
                return setup
    except Exception as e:
        logger.warning(f"Lỗi khi trích xuất setup từ JSON: {e}. Fallback sang regex.")
        pass

    # Fallback sang regex nếu JSON không có hoặc lỗi
    lines = text.split("\n")
    for line in lines:
        line_lower = line.lower()
        if "entry:" in line_lower:
            match = re.search(r"entry:\s*([\d\.,]+)", line_lower)
            if match:
                setup["entry"] = parse_float(match.group(1))
        elif "sl:" in line_lower:
            match = re.search(r"sl:\s*([\d\.,]+)", line_lower)
            if match:
                setup["sl"] = parse_float(match.group(1))
        elif "tp1:" in line_lower:
            match = re.search(r"tp1:\s*([\d\.,]+)", line_lower)
            if match:
                setup["tp1"] = parse_float(match.group(1))
        elif "tp2:" in line_lower:
            match = re.search(r"tp2:\s*([\d\.,]+)", line_lower)
            if match:
                setup["tp2"] = parse_float(match.group(1))
        elif "direction:" in line_lower:
            setup["direction"] = parse_direction_from_line1(line)
    
    # Nếu vẫn thiếu direction, thử từ dòng đầu tiên của toàn bộ text
    if not setup.get("direction") and lines:
        setup["direction"] = parse_direction_from_line1(lines[0])

    logger.debug(f"Kết thúc parse_setup_from_report. Setup: {setup}")
    return setup


def extract_summary_lines(text: str) -> Tuple[List[str], Optional[str], bool]:
    """
    Trích xuất các dòng tóm tắt (Task 2) và chữ ký (Task 3) từ báo cáo.
    Cũng xác định xem có phải là "HIGH PROBABILITY" hay không.

    Args:
        text: Nội dung báo cáo.

    Returns:
        Một tuple chứa:
        - Danh sách các dòng tóm tắt.
        - Chữ ký (nếu có).
        - Giá trị boolean cho biết có phải là "HIGH PROBABILITY" hay không.
    """
    logger.debug("Bắt đầu extract_summary_lines.")
    summary_lines: List[str] = []
    signature: Optional[str] = None
    high_prob: bool = False

    # Tìm phần NHIỆM VỤ 2
    task2_match = re.search(r"###\s*NHIỆM VỤ 2\s*(.*?)(?=\n###|\Z)", text, re.DOTALL | re.IGNORECASE)
    if task2_match:
        task2_content = task2_match.group(1).strip()
        # Tách các dòng và loại bỏ các dòng trống
        lines = [line.strip() for line in task2_content.split('\n') if line.strip()]
        # Giới hạn 7 dòng đầu tiên
        summary_lines = lines[:7]
        logger.debug(f"Đã trích xuất {len(summary_lines)} dòng tóm tắt.")

    # Tìm phần NHIỆM VỤ 3 (chữ ký)
    task3_match = re.search(r"###\s*NHIỆM VỤ 3\s*(.*?)(?=\n###|\Z)", text, re.DOTALL | re.IGNORECASE)
    if task3_match:
        signature = task3_match.group(1).strip()
        logger.debug(f"Đã trích xuất chữ ký: {signature}")
        if "HIGH PROBABILITY" in signature.upper():
            high_prob = True
            logger.debug("Tìm thấy 'HIGH PROBABILITY'.")

    logger.debug(f"Kết thúc extract_summary_lines. High Prob: {high_prob}")
    return summary_lines, signature, high_prob


def repair_json_string(s: str) -> str:
    """
    Cố gắng sửa chữa một chuỗi JSON bị lỗi để nó có thể được parse.
    Xử lý các trường hợp phổ biến như thiếu dấu ngoặc, dấu phẩy thừa.

    Args:
        s: Chuỗi JSON có thể bị lỗi.

    Returns:
        Chuỗi JSON đã được sửa chữa hoặc chuỗi gốc nếu không thể sửa chữa.
    """
    logger.debug(f"Bắt đầu repair_json_string. Độ dài chuỗi gốc: {len(s)}")
    # Loại bỏ các ký tự không phải JSON ở đầu và cuối
    s = s.strip()
    if not s.startswith("{"):
        s = "{" + s
    if not s.endswith("}"):
        s = s + "}"

    # Loại bỏ các dấu phẩy thừa trước dấu đóng ngoặc
    s = re.sub(r",\s*}", "}", s)
    s = re.sub(r",\s*]", "]", s)

    # Thêm dấu ngoặc kép cho các key không có dấu ngoặc kép (nếu có thể)
    s = re.sub(r"([{,])\s*([A-Za-z_][A-Za-z0-9_]*)\s*:", r'\1"\2":', s)

    # Thử parse và trả về nếu thành công
    try:
        json.loads(s)
        logger.debug("Đã sửa chữa JSON thành công.")
        return s
    except json.JSONDecodeError:
        logger.warning("Không thể sửa chữa JSON hoàn toàn, trả về chuỗi gốc.")
        return s # Trả về chuỗi gốc nếu không thể sửa chữa


def find_balanced_json_after(text: str, start_idx: int) -> Tuple[Optional[str], Optional[int]]:
    """
    Tìm và trích xuất một khối JSON cân bằng (balanced JSON block) từ một chuỗi văn bản,
    bắt đầu từ một chỉ mục cụ thể.

    Args:
        text: Chuỗi văn bản để tìm kiếm.
        start_idx: Chỉ mục bắt đầu tìm kiếm.

    Returns:
        Một tuple chứa chuỗi JSON tìm được và chỉ mục kết thúc của nó, hoặc (None, None) nếu không tìm thấy.
    """
    logger.debug(f"Bắt đầu find_balanced_json_after. Start index: {start_idx}.")
    brace_count = 0
    in_string = False
    escape_char = False
    json_start = -1

    for i in range(start_idx, len(text)):
        char = text[i]

        if char == '\\':
            escape_char = not escape_char
            continue

        if char == '"' and not escape_char:
            in_string = not in_string

        if not in_string:
            if char == '{':
                if json_start == -1:
                    json_start = i
                brace_count += 1
            elif char == '}':
                brace_count -= 1

        escape_char = False # Reset escape char

        if json_start != -1 and brace_count == 0:
            json_str = text[json_start : i + 1]
            logger.debug(f"Tìm thấy JSON block cân bằng. Độ dài: {len(json_str)}.")
            return json_str, i + 1
    
    logger.debug("Không tìm thấy JSON block cân bằng.")
    return None, None


def extract_json_block_prefer(text: str) -> Dict[str, Any]:
    """
    Trích xuất khối JSON từ một chuỗi văn bản, ưu tiên các khối JSON hoàn chỉnh và hợp lệ.

    Args:
        text: Chuỗi văn bản chứa JSON.

    Returns:
        Một từ điển Python từ JSON hoặc một từ điển lỗi nếu không tìm thấy JSON hợp lệ.
    """
    logger.debug("Bắt đầu extract_json_block_prefer.")
    # Tìm tất cả các khối JSON có thể có
    all_json_blocks = []
    start_search_idx = 0
    while start_search_idx < len(text):
        brace_idx = text.find("{", start_search_idx)
        if brace_idx == -1:
            break
        
        json_str, next_idx = find_balanced_json_after(text, brace_idx)
        if json_str:
            all_json_blocks.append((json_str, brace_idx))
            start_search_idx = next_idx if next_idx else brace_idx + 1
        else:
            start_search_idx = brace_idx + 1
    
    # Ưu tiên các khối JSON lớn hơn và gần cuối văn bản hơn
    all_json_blocks.sort(key=lambda x: (len(x[0]), x[1]), reverse=True)

    for json_str, _ in all_json_blocks:
        try:
            repaired_str = repair_json_string(json_str)
            obj = json.loads(repaired_str)
            if isinstance(obj, dict):
                logger.debug("Đã trích xuất và parse JSON block ưu tiên.")
                return obj
        except Exception as e:
            logger.debug(f"Lỗi khi parse hoặc sửa chữa JSON block: {e}. Thử block tiếp theo.")
            continue
    
    logger.debug("Không tìm thấy JSON block hợp lệ nào.")
    return {"error": "No valid JSON block found"}


def parse_mt5_data_to_report(safe_mt5_data: SafeMT5Data) -> str:
    """
    Chuyển đổi dữ liệu MT5 từ SafeMT5Data thành một chuỗi báo cáo có cấu trúc
    để đưa vào prompt của AI.

    Args:
        safe_mt5_data: Đối tượng SafeMT5Data chứa dữ liệu MT5.

    Returns:
        Chuỗi báo cáo MT5 đã định dạng.
    """
    logger.debug("Bắt đầu parse_mt5_data_to_report.")
    if not safe_mt5_data or not safe_mt5_data.raw:
        logger.warning("SafeMT5Data trống, không thể tạo báo cáo MT5.")
        return "Không có dữ liệu MT5."

    mt5_data = safe_mt5_data.raw
    report_lines = []

    report_lines.append("--- DỮ LIỆU MT5 HIỆN TẠI ---")
    report_lines.append(f"Symbol: {mt5_data.get('symbol', 'N/A')}")
    report_lines.append(f"Thời gian Broker: {mt5_data.get('broker_time', 'N/A')}")
    report_lines.append(f"Giá hiện tại (Bid): {safe_mt5_data.get_tick_value('bid', 'N/A')}")
    report_lines.append(f"Spread (points): {safe_mt5_data.get_info_value('spread_current', 'N/A')}")
    report_lines.append(f"ATR M5 (pips): {safe_mt5_data.get_atr_pips('M5', 0.0):.2f}")
    report_lines.append(f"Ticks/phút (5m): {safe_mt5_data.get_tick_value('ticks_per_min_5m', 'N/A')}")
    report_lines.append(f"Vị trí trong Daily Range: {safe_mt5_data.get('position_in_day_range', 'N/A'):.2f}")
    report_lines.append(f"Phiên giao dịch đang hoạt động: {safe_mt5_data.get_active_session() or 'N/A'}")
    report_lines.append(f"Phân tích tin tức: {mt5_data.get('news_analysis', {}).get('reason', 'N/A')}")
    
    # Thông tin tài khoản
    account = mt5_data.get("account", {})
    if account:
        report_lines.append("\n--- THÔNG TIN TÀI KHOẢN ---")
        report_lines.append(f"Balance: {account.get('balance', 'N/A'):.2f} {account.get('currency', '')}")
        report_lines.append(f"Equity: {account.get('equity', 'N/A'):.2f} {account.get('currency', '')}")
        report_lines.append(f"Free Margin: {account.get('free_margin', 'N/A'):.2f} {account.get('currency', '')}")
        report_lines.append(f"Leverage: {account.get('leverage', 'N/A')}")

    # Lệnh đang mở
    positions = mt5_data.get("positions", [])
    if positions:
        report_lines.append("\n--- LỆNH ĐANG MỞ ---")
        for pos in positions:
            report_lines.append(f"- {pos.get('type')} {pos.get('volume')} @ {pos.get('price_open')} SL:{pos.get('sl')} TP:{pos.get('tp')} PnL:{pos.get('profit'):.2f}")

    # Các mức giá quan trọng
    report_lines.append("\n--- CÁC MỨC GIÁ QUAN TRỌNG ---")
    daily_levels = mt5_data.get("levels", {}).get("daily", {})
    if daily_levels:
        report_lines.append(f"Daily Open: {daily_levels.get('open', 'N/A')}")
        report_lines.append(f"Daily High: {daily_levels.get('high', 'N/A')}")
        report_lines.append(f"Daily Low: {daily_levels.get('low', 'N/A')}")
        report_lines.append(f"Daily EQ50: {daily_levels.get('eq50', 'N/A')}")
    
    key_levels_nearby = mt5_data.get("key_levels_nearby", [])
    if key_levels_nearby:
        report_lines.append("Key Levels Gần đây:")
        for kl in key_levels_nearby:
            report_lines.append(f"- {kl.get('name')}: {kl.get('price')} ({kl.get('relation')}, {kl.get('distance_pips'):.2f} pips)")

    # Các mẫu ICT
    ict_patterns = mt5_data.get("ict_patterns", {})
    if ict_patterns:
        report_lines.append("\n--- CÁC MẪU ICT ---")
        for k, v in ict_patterns.items():
            if v:
                report_lines.append(f"{k}: {v}")

    result = "\n".join(report_lines)
    logger.debug(f"Kết thúc parse_mt5_data_to_report. Độ dài báo cáo: {len(result)}.")
    return result
