from __future__ import annotations

import json
import hashlib
import mimetypes
import time
from pathlib import Path
from typing import Optional, Tuple, List, TYPE_CHECKING  # Thêm TYPE_CHECKING
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    import google.generativeai as genai  # type: ignore
except Exception as _e:  # pragma: no cover - import validated by caller
    genai = None  # type: ignore

try:
    from PIL import Image  # type: ignore
except Exception:  # pragma: no cover - optional optimization
    Image = None  # type: ignore

from src.config.constants import APP_DIR, UPLOAD_CACHE_JSON

if TYPE_CHECKING:
    from scripts.tool import TradingToolApp
    from src.config.config import RunConfig

try:
    import google.generativeai as genai  # type: ignore
except Exception as _e:  # pragma: no cover - import validated by caller
    genai = None  # type: ignore


class UploadCache:
    @staticmethod
    def load() -> dict:
        try:
            if UPLOAD_CACHE_JSON.exists():
                return json.loads(UPLOAD_CACHE_JSON.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {}

    @staticmethod
    def save(cache: dict) -> None:
        try:
            UPLOAD_CACHE_JSON.write_text(
                json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception:
            pass

    @staticmethod
    def file_sig(path: str) -> str:
        p = Path(path)
        try:
            size = p.stat().st_size
            mtime = int(p.stat().st_mtime)
            h = hashlib.sha1()
            with open(p, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    h.update(chunk)
            return f"{size}:{mtime}:{h.hexdigest()[:16]}"
        except Exception:
            return ""

    @staticmethod
    def lookup(cache: dict, path: str) -> str:
        rec = cache.get(path)
        if not rec:
            return ""
        sig_now = UploadCache.file_sig(path)
        return rec["remote_name"] if sig_now and rec.get("sig") == sig_now else ""

    @staticmethod
    def put(cache: dict, path: str, remote_name: str) -> None:
        cache[path] = {"sig": UploadCache.file_sig(path), "remote_name": remote_name}


def prepare_image(path: str, *, optimize: bool, app_dir: Path = APP_DIR) -> str:
    """
    Optionally convert the image to an optimized JPEG copy, else return the original path.
    - Resizes to a max width of 1600px.
    - Converts to JPEG at 85% quality.
    - Fills transparent backgrounds with white.
    - If optimization produces a larger file, keeps the original.
    """
    if not optimize or Image is None:
        return path
    try:
        src = Path(path)
        tmpdir = app_dir / "tmp_upload"
        tmpdir.mkdir(parents=True, exist_ok=True)
        # Output as JPEG
        out = tmpdir / (src.stem + "_opt.jpg")

        with Image.open(src) as im:
            im.load()

            # Resize if wider than 1600px
            max_width = 1600
            if im.width > max_width:
                aspect_ratio = im.height / im.width
                new_height = int(max_width * aspect_ratio)
                work = im.resize((max_width, new_height), Image.Resampling.LANCZOS)
            else:
                work = im.copy()

            # Handle transparency by pasting onto a white background
            if work.mode in ("RGBA", "LA") or "transparency" in work.info:
                background = Image.new("RGB", work.size, (255, 255, 255))
                background.paste(work, (0, 0), work)
                work.close()
                work = background
            elif work.mode != "RGB":
                work = work.convert("RGB")

            # Save as JPEG with specified quality
            work.save(out, format="JPEG", quality=85, optimize=True)
            work.close()

        # Keep original if the optimized version is larger
        if out.stat().st_size >= src.stat().st_size:
            try:
                out.unlink()
            except Exception:
                pass
            return str(src)

        return str(out)
    except Exception:
        # Fallback to original path on any error
        return path


def as_inline_media_part(path: str) -> dict:
    mime, _ = mimetypes.guess_type(path)
    with open(path, "rb") as f:
        data = f.read()
    return {"mime_type": mime or "application/octet-stream", "data": data}


def file_or_inline_for_model(
    file_obj, prepared_path: Optional[str], original_path: str
) -> object:
    try:
        st = getattr(getattr(file_obj, "state", None), "name", None)
        if st == "ACTIVE":
            return file_obj
    except Exception:
        pass
    use_path = prepared_path or original_path
    return as_inline_media_part(use_path)


def upload_one_file_for_worker(item) -> Tuple[str, object]:
    """Upload a single file to Gemini and wait until ACTIVE state if possible.
    item = (original_path, display_name, upload_path)
    Returns (original_path, file_obj_or_upload_ref)
    """
    if genai is None:  # pragma: no cover
        raise RuntimeError(
            "google-generativeai SDK missing. Install: pip install google-generativeai"
        )

    p, n, upath = item
    mime, _ = mimetypes.guess_type(upath)
    uf = genai.upload_file(
        path=upath, mime_type=mime or "application/octet-stream", display_name=n
    )
    retries, delay = 10, 0.6
    while retries > 0:
        try:
            f = genai.get_file(uf.name)
            st = getattr(getattr(f, "state", None), "name", None)
            if st == "ACTIVE":
                return (p, f)
            if st == "FAILED":
                raise RuntimeError("File in FAILED state.")
        except Exception:
            if retries <= 1:
                raise
        time.sleep(delay)
        retries -= 1
        delay = min(delay * 1.5, 3.0)
    return (p, uf)


def upload_images_parallel(
    app: "TradingToolApp", cfg: "RunConfig", to_upload: List[Tuple]
) -> Tuple[List, int]:
    """
    Upload các file ảnh song song và cho phép hủy bỏ các tác vụ đang chờ.
    Gán executor vào app.active_executor để luồng chính có thể truy cập và hủy.
    """
    uploaded_files = []
    file_slots = [None] * len(app.results)

    if not to_upload:
        return file_slots, 0

    max_workers = max(1, min(len(to_upload), int(cfg.upload_workers)))
    steps_upload = len(to_upload)
    total_steps = steps_upload + 2  # 1 cho xử lý context, 1 cho gọi AI

    try:
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            # Gán executor cho app để luồng chính có thể hủy
            app.active_executor = ex

            # Tạo một map từ future sang thông tin file để xử lý kết quả
            futs = {
                ex.submit(upload_one_file_for_worker, (p, n, upath)): (i, p)
                for (i, p, n, upath) in to_upload
            }

            done_cnt = 0
            for fut in as_completed(futs):
                if app.stop_flag:
                    # Không cần hủy future ở đây nữa vì stop_analysis đã làm
                    raise SystemExit("Người dùng đã dừng quá trình upload.")

                try:
                    (p_ret, fobj) = fut.result()
                    i, p = futs[fut]
                    file_slots[i] = fobj
                    uploaded_files.append((fobj, p))
                except Exception:
                    # Bỏ qua lỗi của các future đã bị hủy
                    if app.stop_flag:
                        continue
                    raise  # Ném lại lỗi nếu không phải do người dùng dừng

                done_cnt += 1
                app._update_progress(done_cnt, total_steps)
                app.results[i]["status"] = "Đã upload"
                app._update_tree_row(i, "Đã upload")
    finally:
        # Dọn dẹp tham chiếu đến executor
        app.active_executor = None

    return file_slots, steps_upload


def maybe_delete_uploaded_file(uploaded_file):
    """
    Thực hiện xóa file đã upload lên Gemini nếu cấu hình cho phép.
    """
    try:
        if genai:
            genai.delete_file(uploaded_file.name)
    except Exception:
        pass
