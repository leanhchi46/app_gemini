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
from APP.configs.constants import PATHS

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
        logger.critical("SDK google-generativeai chua duoc cai dat. Bo qua upload cho '%s'.", image_path.name)
        return None

    if not display_name:
        display_name = image_path.name

    logger.info("Dang tai '%s' len Gemini File API...", display_name)
    mime_type, _ = mimetypes.guess_type(str(image_path))
    upload_kwargs = {
        "path": str(image_path),
        "mime_type": mime_type or "application/octet-stream",
        "display_name": display_name,
    }

    client = None
    files_api = None

    try:
        upload_fn = getattr(genai, "upload_file", None)
        if callable(upload_fn):
            file_obj = upload_fn(**upload_kwargs)
        else:
            client_cls = getattr(genai, "Client", None)
            if client_cls is None:
                raise RuntimeError("Phien ban google-generativeai khong ho tro upload_file API.")

            client = client_cls()
            files_api = getattr(client, "files", None)
            if files_api is None or not hasattr(files_api, "upload"):
                raise RuntimeError("Client.files API khong kha dung cho upload.")
            file_obj = files_api.upload(**upload_kwargs)

        if not file_obj:
            logger.error("Upload API khong tra ve doi tuong file cho '%s'.", display_name)
            return None

        file_name = getattr(file_obj, "name", None) or getattr(file_obj, "id", None) or getattr(file_obj, "uri", None)
        if not file_name:
            logger.error("Khong nhan duoc dinh danh file sau khi upload '%s'.", display_name)
            return None

        get_file_fn = getattr(genai, "get_file", None)
        delete_file_fn = getattr(genai, "delete_file", None)
        can_poll = callable(get_file_fn) or (files_api is not None and hasattr(files_api, "get"))

        def _poll(name: str):
            if callable(get_file_fn):
                return get_file_fn(name)
            if files_api is not None and hasattr(files_api, "get"):
                return files_api.get(name=name)
            return None

        def _delete(name: str):
            if callable(delete_file_fn):
                return delete_file_fn(name)
            if files_api is not None and hasattr(files_api, "delete"):
                return files_api.delete(name=name)
            return None

        def _extract_state(file_status: Any) -> str:
            if file_status is None:
                return "UNKNOWN"
            state = getattr(file_status, "state", None)
            if isinstance(state, str):
                return state
            if state is not None:
                name_attr = getattr(state, "name", None)
                if isinstance(name_attr, str):
                    return name_attr
                return str(state)
            return "UNKNOWN"

        if not can_poll:
            logger.debug("SDK khong ho tro kiem tra trang thai file sau upload; tra ve ket qua ngay.")
            return file_obj

        start_time = time.monotonic()
        delay = 0.6
        last_state = "UNKNOWN"

        while time.monotonic() - start_time < timeout:
            file_status = _poll(file_name)
            if file_status is None:
                logger.debug("Khong lay duoc trang thai file; tra ve ket qua upload ban dau.")
                return file_obj

            state = _extract_state(file_status)
            last_state = state
            logger.debug("Trang thai file '%s': %s sau %.1fs", display_name, state, time.monotonic() - start_time)

            if state == "ACTIVE":
                logger.info("Da tai len thanh cong '%s'.", display_name)
                return file_status

            if state == "FAILED":
                logger.error("Tai len khong thanh cong cho '%s'. Trang thai FAILED.", display_name)
                try:
                    _delete(file_name)
                except Exception as del_err:
                    logger.warning("Khong the xoa tep that bai '%s': %s", file_name, del_err)
                return None

            time.sleep(delay)
            delay = min(delay * 1.5, 3.0)

        logger.error("Het thoi gian cho (%ss) de tep '%s' tro thanh ACTIVE. Trang thai cuoi: %s.", timeout, display_name, last_state)
        try:
            _delete(file_name)
        except Exception as del_err:
            logger.warning("Khong the xoa tep khi het thoi gian '%s': %s", file_name, del_err)
        return None

    except Exception as e:
        logger.error(f"Da xay ra loi khong mong muon trong qua trinh tai tep len cho '{display_name}': {e}", exc_info=True)
        return None
