import base64
import hashlib
import os
from pathlib import Path
import platform
import logging # Thêm import logging

logger = logging.getLogger(__name__) # Khởi tạo logger

def _xor_bytes(a: bytes, b: bytes) -> bytes:
    """
    Thực hiện phép toán XOR bitwise giữa hai chuỗi byte.

    Args:
        a: Chuỗi byte thứ nhất.
        b: Chuỗi byte thứ hai.

    Returns:
        Chuỗi byte kết quả của phép XOR.
    """
    logger.debug("Thực hiện XOR bytes.")
    return bytes(x ^ y for x, y in zip(a, b))

def _machine_key() -> bytes:
    """
    Tạo một khóa máy duy nhất dựa trên thông tin hệ thống.

    Returns:
        Khóa máy dưới dạng chuỗi byte SHA256.
    """
    logger.debug("Tạo machine key.")
    info = f"{platform.system()}-{platform.machine()}-{platform.node()}"
    key = hashlib.sha256(info.encode("utf-8")).digest()
    logger.debug(f"Đã tạo machine key. Độ dài: {len(key)} bytes.")
    return key

def obfuscate_text(text: str) -> str:
    """
    Mã hóa một chuỗi văn bản bằng cách sử dụng phép XOR với khóa máy và mã hóa Base64.

    Args:
        text: Chuỗi văn bản cần mã hóa.

    Returns:
        Chuỗi văn bản đã được mã hóa Base64.
    """
    logger.debug("Bắt đầu obfuscate text.")
    key = _machine_key()
    data = text.encode("utf-8")
    encrypted = _xor_bytes(data, key * (len(data) // len(key) + 1))
    result = base64.b64encode(encrypted).decode("utf-8")
    logger.debug("Đã obfuscate text thành công.")
    return result

def deobfuscate_text(b64_text: str) -> str:
    """
    Giải mã một chuỗi văn bản đã được mã hóa Base64 bằng cách sử dụng phép XOR với khóa máy.

    Args:
        b64_text: Chuỗi văn bản đã được mã hóa Base64.

    Returns:
        Chuỗi văn bản đã được giải mã. Trả về chuỗi rỗng nếu có lỗi giải mã.
    """
    logger.debug("Bắt đầu deobfuscate text.")
    key = _machine_key()
    try:
        # Fix incorrect padding
        b64_text += '=' * (-len(b64_text) % 4)
        encrypted = base64.b64decode(b64_text.encode("utf-8"))
        decrypted = _xor_bytes(encrypted, key * (len(encrypted) // len(key) + 1))
        result = decrypted.decode("utf-8")
        logger.debug("Đã deobfuscate text thành công.")
        return result
    except (ValueError, TypeError, base64.binascii.Error) as e:
        logger.warning(f"Lỗi khi deobfuscate text: {e}. Trả về chuỗi rỗng.")
        # Return empty string if the key is corrupted or invalid
        return ""

def _tg_html_escape(text: str) -> str:
    """
    Thực hiện HTML escape cho văn bản để sử dụng an toàn trong Telegram.

    Args:
        text: Chuỗi văn bản cần escape.

    Returns:
        Chuỗi văn bản đã được HTML escape.
    """
    logger.debug("Thực hiện HTML escape cho Telegram.")
    if not text:
        return ""
    return text.replace("&", "&").replace("<", "<").replace(">", ">")

def cleanup_old_files(directory: Path, pattern: str, keep_n: int):
    """
    Xóa các tệp cũ nhất trong một thư mục khớp với một mẫu, chỉ giữ lại n tệp mới nhất.

    Args:
        directory: Đường dẫn đến thư mục cần dọn dẹp.
        pattern: Mẫu glob để khớp với tên tệp (ví dụ: "*.log").
        keep_n: Số lượng tệp mới nhất cần giữ lại.
    """
    logger.debug(f"Bắt đầu cleanup_old_files trong thư mục: {directory}, pattern: {pattern}, giữ lại: {keep_n} file.")
    if not directory or not directory.is_dir() or keep_n <= 0:
        logger.warning("Điều kiện cleanup không hợp lệ (directory trống/không tồn tại, hoặc keep_n <= 0).")
        return
    try:
        files = sorted(directory.glob(pattern), key=os.path.getmtime, reverse=True)
        if len(files) > keep_n:
            for p in files[keep_n:]:
                try:
                    p.unlink()
                    logger.debug(f"Đã xóa file cũ: {p.name}")
                except Exception as e:
                    logger.warning(f"Lỗi khi xóa file '{p.name}': {e}")
                    pass # Silently ignore if a single file fails to delete
        else:
            logger.debug("Không có đủ file để cleanup.")
    except Exception as e:
        logger.error(f"Lỗi trong quá trình cleanup_old_files: {e}")
        pass # Silently ignore if the cleanup process fails
    finally:
        logger.debug("Kết thúc cleanup_old_files.")

# Các hàm detect_timeframe_from_name và build_timeframe_section đã được chuyển sang src/ui/timeframe_detector.py.
# File này hiện tại không còn hàm nào.
