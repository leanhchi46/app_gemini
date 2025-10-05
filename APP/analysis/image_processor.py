# -*- coding: utf-8 -*-
"""
Module để chuẩn bị và tải ảnh lên Gemini API.

Module này cung cấp các chức năng để tối ưu hóa hình ảnh cho việc tải lên và
xử lý quá trình tải lên, bao gồm cả việc sử dụng cache để tránh tải lại các tệp không thay đổi.
"""

from __future__ import annotations

import hashlib
import json
import logging
import mimetypes
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict

# Import của bên thứ ba
try:
    import google.generativeai as genai
except ImportError:
    genai = None
try:
    from PIL import Image
except ImportError:
    Image = None

# Import cục bộ
from APP.configs.constants import FILES, PATHS

if TYPE_CHECKING:
    from APP.configs.app_config import ImageProcessingConfig

logger = logging.getLogger(__name__)


class UploadCache:
    """
    Quản lý cache để tránh tải lại các file không thay đổi.

    Cache lưu trữ một chữ ký của mỗi file (dựa trên kích thước, thời gian sửa đổi,
    và hash nội dung) và tên từ xa do Gemini API cung cấp.
    """

    @staticmethod
    def load() -> Dict[str, Any]:
        """Tải cache upload từ file JSON."""
        logger.debug("Đang thử tải cache upload.")
        if not PATHS.UPLOAD_CACHE_JSON.exists():
            logger.debug("File cache upload không tồn tại. Trả về cache rỗng.")
            return {}
        try:
            with open(PATHS.UPLOAD_CACHE_JSON, "r", encoding="utf-8") as f:
                cache_data = json.load(f)
            logger.debug(f"Đã tải cache upload với {len(cache_data)} mục.")
            return cache_data
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Lỗi khi tải cache upload: {e}", exc_info=True)
            return {}

    @staticmethod
    def save(cache: Dict[str, Any]) -> None:
        """Lưu cache upload vào file JSON."""
        logger.debug(f"Đang lưu cache upload với {len(cache)} mục.")
        try:
            with open(PATHS.UPLOAD_CACHE_JSON, "w", encoding="utf-8") as f:
                json.dump(cache, f, ensure_ascii=False, indent=2)
            logger.debug("Đã lưu cache upload thành công.")
        except IOError as e:
            logger.error(f"Lỗi khi lưu cache upload: {e}", exc_info=True)

    @staticmethod
    def _calculate_file_sig(path: Path) -> str:
        """Tính toán chữ ký cho một file dựa trên metadata và nội dung của nó."""
        try:
            size = path.stat().st_size
            mtime = int(path.stat().st_mtime)
            h = hashlib.sha1()
            with open(path, "rb") as f:
                # Đọc theo từng đoạn để xử lý các file lớn
                for chunk in iter(lambda: f.read(65536), b""):
                    h.update(chunk)
            # Chữ ký kết hợp kích thước, mtime, và một phần của hash
            sig = f"{size}:{mtime}:{h.hexdigest()[:16]}"
            logger.debug(f"Đã tính toán chữ ký cho {path.name}: {sig}")
            return sig
        except IOError as e:
            logger.warning(f"Không thể tính toán chữ ký cho '{path}': {e}")
            return ""

    @staticmethod
    def lookup(cache: Dict[str, Any], path: Path) -> str:
        """
        Tra cứu một file trong cache.

        Trả về tên từ xa nếu file được tìm thấy và chữ ký của nó khớp,
        nếu không trả về một chuỗi rỗng.
        """
        path_str = str(path)
        record = cache.get(path_str)
        if not record:
            logger.debug(f"Cache miss cho đường dẫn: {path_str}")
            return ""

        current_sig = UploadCache._calculate_file_sig(path)
        if current_sig and record.get("sig") == current_sig:
            remote_name = record.get("remote_name", "")
            logger.debug(f"Cache hit cho {path.name}. Tên từ xa: {remote_name}")
            return remote_name
        
        logger.debug(f"Cache hit cho {path.name}, nhưng chữ ký không khớp.")
        return ""

    @staticmethod
    def put(cache: Dict[str, Any], path: Path, remote_name: str) -> None:
        """Thêm hoặc cập nhật bản ghi của một file trong cache."""
        path_str = str(path)
        sig = UploadCache._calculate_file_sig(path)
        if not sig:
            logger.warning(f"Không thể thêm {path.name} vào cache do lỗi chữ ký.")
            return
        
        cache[path_str] = {"sig": sig, "remote_name": remote_name}
        logger.debug(f"Đã thêm/cập nhật {path.name} trong cache với tên từ xa {remote_name}.")


def prepare_image(
    path: Path, *, optimize: bool, image_config: ImageProcessingConfig
) -> Path:
    """
    Tùy chọn chuyển đổi một hình ảnh thành một bản sao JPEG được tối ưu hóa.

    Sử dụng các tham số từ đối tượng ImageProcessingConfig để điều khiển quá trình.

    Args:
        path: Đường dẫn đến hình ảnh nguồn.
        optimize: Cờ boolean để bật hoặc tắt tối ưu hóa.
        image_config: Đối tượng cấu hình chứa max_width và jpeg_quality.

    Returns:
        Đường dẫn đến hình ảnh được tối ưu hóa, hoặc đường dẫn gốc.
    """
    logger.debug(f"Đang chuẩn bị ảnh: {path.name}, Tối ưu hóa: {optimize}")
    if not optimize or Image is None:
        if Image is None:
            logger.warning("Pillow (PIL) chưa được cài đặt. Tối ưu hóa hình ảnh bị vô hiệu hóa.")
        logger.debug("Bỏ qua tối ưu hóa hình ảnh.")
        return path

    try:
        src_path = path
        tmp_dir = PATHS.APP_DIR / "tmp_upload"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        
        # Xuất ra dưới dạng JPEG để nhất quán
        out_path = tmp_dir / (src_path.stem + "_optimized.jpg")
        logger.debug(f"Ảnh được tối ưu hóa sẽ được lưu vào: {out_path}")

        with Image.open(src_path) as img:
            img.load()
            logger.debug(f"Đã tải ảnh gốc: {src_path.name}, kích thước: {img.size}, mode: {img.mode}")

            # Thay đổi kích thước nếu rộng hơn ngưỡng từ cấu hình
            if img.width > image_config.max_width:
                aspect_ratio = img.height / img.width
                new_height = int(image_config.max_width * aspect_ratio)
                work_img = img.resize(
                    (image_config.max_width, new_height), Image.Resampling.LANCZOS
                )
                logger.debug(
                    f"Đã thay đổi kích thước ảnh từ {img.size} thành {(image_config.max_width, new_height)}."
                )
            else:
                work_img = img.copy()
                logger.debug("Chiều rộng ảnh nằm trong giới hạn, không cần thay đổi kích thước.")

            # Xử lý nền trong suốt bằng cách dán lên nền trắng
            if work_img.mode in ("RGBA", "LA") or "transparency" in work_img.info:
                background = Image.new("RGB", work_img.size, (255, 255, 255))
                background.paste(work_img, (0, 0), work_img)
                work_img.close()
                work_img = background
                logger.debug("Đã xử lý nền trong suốt bằng cách lấp đầy màu trắng.")
            elif work_img.mode != "RGB":
                logger.debug(f"Đang chuyển đổi ảnh từ {work_img.mode} sang RGB.")
                work_img = work_img.convert("RGB")

            # Lưu dưới dạng JPEG với chất lượng được chỉ định từ cấu hình
            work_img.save(
                out_path,
                format="JPEG",
                quality=image_config.jpeg_quality,
                optimize=True,
            )
            work_img.close()
            logger.debug(
                f"Đã lưu ảnh được tối ưu hóa với chất lượng {image_config.jpeg_quality}. "
                f"Kích thước: {out_path.stat().st_size} bytes."
            )

        # Giữ lại ảnh gốc nếu phiên bản được tối ưu hóa lớn hơn
        if out_path.stat().st_size >= src_path.stat().st_size:
            logger.info("Ảnh được tối ưu hóa lớn hơn ảnh gốc. Sử dụng ảnh gốc.")
            try:
                out_path.unlink()
            except OSError as e:
                logger.warning(f"Không thể xóa ảnh được tối ưu hóa quá khổ: {e}")
            return src_path

        logger.info(f"Tối ưu hóa hình ảnh thành công. Sử dụng tệp được tối ưu hóa: {out_path.name}")
        return out_path
    except Exception as e:
        logger.error(f"Lỗi khi chuẩn bị ảnh '{path}': {e}", exc_info=True)
        # Trả về đường dẫn gốc khi có bất kỳ lỗi nào
        return path


def upload_image_to_gemini(
    image_path: Path,
    display_name: str | None = None,
    timeout: int = 60,
) -> Any | None:
    """
    Tải một hình ảnh duy nhất lên Gemini File API.

    Nó đợi cho đến khi tệp trở nên ACTIVE, với một timeout toàn cục.

    Args:
        image_path: Đường dẫn đến tệp hình ảnh cần tải lên.
        display_name: Tên hiển thị tùy chọn cho tệp trong API.
        timeout: Thời gian chờ tối đa (tính bằng giây).

    Returns:
        Đối tượng tệp Gemini nếu thành công, nếu không thì None.
    """
    if genai is None:
        logger.critical("SDK google-generativeai chưa được cài đặt. Không thể tải tệp lên.")
        raise RuntimeError("SDK google-generativeai bị thiếu. Cài đặt bằng: pip install google-generativeai")

    if not display_name:
        display_name = image_path.name
        
    logger.info(f"Đang tải '{display_name}' lên Gemini File API...")
    
    try:
        mime_type, _ = mimetypes.guess_type(image_path)
        uploaded_file = genai.files.upload(
            path=image_path,
            mime_type=mime_type or "application/octet-stream",
            display_name=display_name,
        )
        logger.debug(f"Yêu cầu tải lên đã được gửi. Tên từ xa: {uploaded_file.name}. Đang chờ trạng thái ACTIVE.")

        # Đợi tệp được xử lý với timeout
        start_time = time.monotonic()
        delay = 0.6
        while time.monotonic() - start_time < timeout:
            time.sleep(delay)
            file_status = genai.files.get(uploaded_file.name)
            state_name = getattr(getattr(file_status, "state", None), "name", "UNKNOWN")
            logger.debug(f"Kiểm tra trạng thái tệp cho '{display_name}': {state_name}. Thời gian đã trôi qua: {time.monotonic() - start_time:.1f}s")

            if state_name == "ACTIVE":
                logger.info(f"Đã tải lên và xử lý thành công '{display_name}'.")
                return file_status
            if state_name == "FAILED":
                logger.error(f"Tải lên không thành công cho '{display_name}'. Trạng thái là FAILED.")
                try:
                    genai.files.delete(uploaded_file.name)
                    logger.debug(f"Đã xóa cấu phần tệp không thành công: {uploaded_file.name}")
                except Exception as del_e:
                    logger.warning(f"Không thể xóa cấu phần tệp không thành công: {del_e}")
                return None
            
            delay = min(delay * 1.5, 3.0) # Backoff hàm mũ với giới hạn

        logger.error(f"Hết thời gian chờ ({timeout}s) cho tệp '{display_name}' trở nên ACTIVE.")
        return None

    except Exception as e:
        logger.error(f"Đã xảy ra lỗi không mong muốn trong quá trình tải tệp lên cho '{display_name}': {e}", exc_info=True)
        return None
