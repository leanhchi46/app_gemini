from __future__ import annotations

import json
import hashlib
import mimetypes
import time
from pathlib import Path
from typing import Optional, Tuple, List, TYPE_CHECKING  # Thêm TYPE_CHECKING
from concurrent.futures import ThreadPoolExecutor, as_completed
import logging # Thêm import logging

logger = logging.getLogger(__name__) # Khởi tạo logger

try:
    import google.generativeai as genai  # type: ignore
except Exception as _e:  # pragma: no cover - import validated by caller
    genai = None  # type: ignore
    logger.warning(f"Không thể import google.generativeai: {_e}")

try:
    from PIL import Image  # type: ignore
except Exception as _e:  # pragma: no cover - optional optimization
    Image = None  # type: ignore
    logger.warning(f"Không thể import PIL.Image: {_e}. Tối ưu hóa ảnh sẽ bị vô hiệu hóa.")

from src.config.constants import APP_DIR, UPLOAD_CACHE_JSON

if TYPE_CHECKING:
    from scripts.tool import TradingToolApp
    from src.config.config import RunConfig


class UploadCache:
    @staticmethod
    def load() -> dict:
        logger.debug("Bắt đầu UploadCache.load().")
        try:
            if UPLOAD_CACHE_JSON.exists():
                cache_data = json.loads(UPLOAD_CACHE_JSON.read_text(encoding="utf-8"))
                logger.debug(f"Đã tải cache upload. Số mục: {len(cache_data)}")
                return cache_data
        except Exception as e:
            logger.error(f"Lỗi khi tải upload cache: {e}")
            pass
        logger.debug("Không tìm thấy hoặc lỗi khi tải upload cache, trả về rỗng.")
        return {}

    @staticmethod
    def save(cache: dict) -> None:
        logger.debug(f"Bắt đầu UploadCache.save(). Số mục: {len(cache)}")
        try:
            UPLOAD_CACHE_JSON.write_text(
                json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            logger.debug("Đã lưu upload cache thành công.")
        except Exception as e:
            logger.error(f"Lỗi khi lưu upload cache: {e}")
            pass

    @staticmethod
    def file_sig(path: str) -> str:
        logger.debug(f"Bắt đầu UploadCache.file_sig cho path: {path}")
        p = Path(path)
        try:
            size = p.stat().st_size
            mtime = int(p.stat().st_mtime)
            h = hashlib.sha1()
            with open(p, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    h.update(chunk)
            sig = f"{size}:{mtime}:{h.hexdigest()[:16]}"
            logger.debug(f"Đã tạo file signature: {sig}")
            return sig
        except Exception as e:
            logger.warning(f"Lỗi khi tạo file signature cho '{path}': {e}")
            return ""

    @staticmethod
    def lookup(cache: dict, path: str) -> str:
        logger.debug(f"Bắt đầu UploadCache.lookup cho path: {path}")
        rec = cache.get(path)
        if not rec:
            logger.debug("Không tìm thấy record trong cache.")
            return ""
        sig_now = UploadCache.file_sig(path)
        result = rec["remote_name"] if sig_now and rec.get("sig") == sig_now else ""
        logger.debug(f"Kết quả lookup cache: {result}")
        return result

    @staticmethod
    def put(cache: dict, path: str, remote_name: str) -> None:
        logger.debug(f"Bắt đầu UploadCache.put cho path: {path}, remote_name: {remote_name}")
        cache[path] = {"sig": UploadCache.file_sig(path), "remote_name": remote_name}
        logger.debug("Đã thêm/cập nhật mục vào cache.")


def prepare_image(path: str, *, optimize: bool, app_dir: Path = APP_DIR) -> str:
    """
    Optionally convert the image to an optimized JPEG copy, else return the original path.
    - Resizes to a max width of 1600px.
    - Converts to JPEG at 85% quality.
    - Fills transparent backgrounds with white.
    - If optimization produces a larger file, keeps the original.
    """
    logger.debug(f"Bắt đầu prepare_image cho path: {path}, optimize: {optimize}")
    if not optimize or Image is None:
        logger.debug("Không tối ưu hóa ảnh hoặc PIL.Image không có sẵn, trả về path gốc.")
        return path
    try:
        src = Path(path)
        tmpdir = app_dir / "tmp_upload"
        tmpdir.mkdir(parents=True, exist_ok=True)
        # Output as JPEG
        out = tmpdir / (src.stem + "_opt.jpg")
        logger.debug(f"Đường dẫn ảnh tối ưu hóa tạm thời: {out}")

        with Image.open(src) as im:
            im.load()
            logger.debug(f"Đã tải ảnh gốc: {src.name}, kích thước: {im.size}, mode: {im.mode}")

            # Resize if wider than 1600px
            max_width = 1600
            if im.width > max_width:
                aspect_ratio = im.height / im.width
                new_height = int(max_width * aspect_ratio)
                work = im.resize((max_width, new_height), Image.Resampling.LANCZOS)
                logger.debug(f"Đã resize ảnh từ {im.size} xuống {(max_width, new_height)}.")
            else:
                work = im.copy()
                logger.debug("Không cần resize ảnh.")

            # Handle transparency by pasting onto a white background
            if work.mode in ("RGBA", "LA") or "transparency" in work.info:
                background = Image.new("RGB", work.size, (255, 255, 255))
                background.paste(work, (0, 0), work)
                work.close()
                work = background
                logger.debug("Đã xử lý nền trong suốt.")
            elif work.mode != "RGB":
                work = work.convert("RGB")
                logger.debug(f"Đã convert ảnh sang mode RGB từ {im.mode}.")

            # Save as JPEG with specified quality
            work.save(out, format="JPEG", quality=85, optimize=True)
            work.close()
            logger.debug(f"Đã lưu ảnh tối ưu hóa tại {out}, kích thước: {out.stat().st_size} bytes.")

        # Keep original if the optimized version is larger
        if out.stat().st_size >= src.stat().st_size:
            logger.debug("Ảnh tối ưu hóa lớn hơn hoặc bằng ảnh gốc, giữ ảnh gốc.")
            try:
                out.unlink()
                logger.debug(f"Đã xóa ảnh tối ưu hóa lớn hơn: {out.name}")
            except Exception as e:
                logger.warning(f"Lỗi khi xoá ảnh tối ưu hóa: {e}")
                pass
            return str(src)

        logger.debug(f"Kết thúc prepare_image. Trả về path tối ưu hóa: {out}")
        return str(out)
    except Exception as e:
        logger.error(f"Lỗi khi chuẩn bị ảnh '{path}': {e}. Trả về path gốc.")
        # Fallback to original path on any error
        return path


def as_inline_media_part(path: str) -> dict:
    logger.debug(f"Bắt đầu as_inline_media_part cho path: {path}")
    mime, _ = mimetypes.guess_type(path)
    with open(path, "rb") as f:
        data = f.read()
    logger.debug(f"Đã đọc file {path} làm inline media, mime_type: {mime}.")
    return {"mime_type": mime or "application/octet-stream", "data": data}


def file_or_inline_for_model(
    file_obj, prepared_path: Optional[str], original_path: str
) -> object:
    logger.debug(f"Bắt đầu file_or_inline_for_model cho original_path: {original_path}")
    try:
        st = getattr(getattr(file_obj, "state", None), "name", None)
        if st == "ACTIVE":
            logger.debug(f"Sử dụng file_obj đã ACTIVE: {file_obj.name}")
            return file_obj
    except Exception as e:
        logger.warning(f"Lỗi khi kiểm tra trạng thái file_obj: {e}")
        pass
    use_path = prepared_path or original_path
    logger.debug(f"Sử dụng path inline: {use_path}")
    return as_inline_media_part(use_path)


def upload_one_file_for_worker(item) -> Tuple[str, object]:
    """Upload a single file to Gemini and wait until ACTIVE state if possible.
    item = (original_path, display_name, upload_path)
    Returns (original_path, file_obj_or_upload_ref)
    """
    logger.debug(f"Bắt đầu upload_one_file_for_worker cho item: {item[1]}")
    if genai is None:  # pragma: no cover
        logger.error("google-generativeai SDK missing, không thể upload file.")
        raise RuntimeError(
            "google-generativeai SDK missing. Install: pip install google-generativeai"
        )

    p, n, upath = item
    mime, _ = mimetypes.guess_type(upath)
    uf = genai.upload_file(
        path=upath, mime_type=mime or "application/octet-stream", display_name=n
    )
    logger.debug(f"Đã gửi yêu cầu upload file '{n}', remote_name: {uf.name}.")
    retries, delay = 10, 0.6
    while retries > 0:
        try:
            f = genai.get_file(uf.name)
            st = getattr(getattr(f, "state", None), "name", None)
            logger.debug(f"Kiểm tra trạng thái file '{n}': {st}. Còn {retries} lần thử.")
            if st == "ACTIVE":
                logger.debug(f"File '{n}' đã ACTIVE.")
                return (p, f)
            if st == "FAILED":
                logger.error(f"File '{n}' ở trạng thái FAILED.")
                raise RuntimeError("File in FAILED state.")
        except Exception as e:
            logger.warning(f"Lỗi khi get_file '{n}': {e}. Còn {retries} lần thử.")
            if retries <= 1:
                logger.error(f"Hết lần thử, ném lỗi khi get_file '{n}'.")
                raise
        time.sleep(delay)
        retries -= 1
        delay = min(delay * 1.5, 3.0)
    logger.error(f"Hết lần thử, file '{n}' không đạt trạng thái ACTIVE.")
    return (p, uf)


def upload_images_parallel(
    app: "TradingToolApp", cfg: "RunConfig", to_upload: List[Tuple]
) -> Tuple[List, int]:
    """
    Upload các file ảnh song song và cho phép hủy bỏ các tác vụ đang chờ.
    Gán executor vào app.active_executor để luồng chính có thể truy cập và hủy.
    """
    logger.debug(f"Bắt đầu upload_images_parallel. Số file cần upload: {len(to_upload)}")
    uploaded_files = []
    file_slots = [None] * len(app.results)

    if not to_upload:
        logger.debug("Không có file nào để upload, trả về rỗng.")
        return file_slots, 0

    max_workers = max(1, min(len(to_upload), int(cfg.upload_workers)))
    steps_upload = len(to_upload)
    total_steps = steps_upload + 2  # 1 cho xử lý context, 1 cho gọi AI
    logger.debug(f"Max workers: {max_workers}, steps_upload: {steps_upload}, total_steps: {total_steps}")

    try:
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            # Gán executor cho app để luồng chính có thể hủy
            app.active_executor = ex
            logger.debug("Đã gán ThreadPoolExecutor vào app.active_executor.")

            # Tạo một map từ future sang thông tin file để xử lý kết quả
            futs = {
                ex.submit(upload_one_file_for_worker, (p, n, upath)): (i, p)
                for (i, p, n, upath) in to_upload
            }
            logger.debug(f"Đã submit {len(futs)} tác vụ upload.")

            done_cnt = 0
            for fut in as_completed(futs):
                if app.stop_flag:
                    logger.info("Người dùng đã dừng quá trình upload.")
                    # Không cần hủy future ở đây nữa vì stop_analysis đã làm
                    raise SystemExit("Người dùng đã dừng quá trình upload.")

                try:
                    (p_ret, fobj) = fut.result()
                    i, p = futs[fut]
                    file_slots[i] = fobj
                    uploaded_files.append((fobj, p))
                    logger.debug(f"Đã upload thành công file: {p_ret}")
                except Exception as e:
                    # Bỏ qua lỗi của các future đã bị hủy
                    if app.stop_flag:
                        logger.debug(f"Bỏ qua lỗi upload do người dùng dừng: {e}")
                        continue
                    logger.error(f"Lỗi khi upload file: {e}")
                    raise  # Ném lại lỗi nếu không phải do người dùng dừng

                done_cnt += 1
                app._update_progress(done_cnt, total_steps)
                app.results[i]["status"] = "Đã upload"
                app._update_tree_row(i, "Đã upload")
                logger.debug(f"Tiến độ upload: {done_cnt}/{steps_upload}.")
    finally:
        # Dọn dẹp tham chiếu đến executor
        app.active_executor = None
        logger.debug("Đã dọn dẹp app.active_executor.")

    logger.debug(f"Kết thúc upload_images_parallel. Tổng số file đã upload: {len(uploaded_files)}.")
    return file_slots, steps_upload


def delete_uploaded_file(uploaded_file):
    """
    Thực hiện xóa file đã upload lên Gemini.
    """
    logger.debug(f"Bắt đầu delete_uploaded_file cho file: {uploaded_file.name}")
    try:
        if genai:
            genai.delete_file(uploaded_file.name)
            logger.debug(f"Đã xoá file Gemini: {uploaded_file.name}")
        else:
            logger.warning("genai không có sẵn, không thể xoá file Gemini.")
    except Exception as e:
        logger.warning(f"Lỗi khi xoá file Gemini '{uploaded_file.name}': {e}")
