from __future__ import annotations

import hashlib
import json
import logging
import mimetypes
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import TYPE_CHECKING, List, Optional, Tuple

from APP.configs.constants import PATHS

try:
    import google.generativeai as genai
except ImportError:
    genai = None

try:
    from PIL import Image
except ImportError:
    Image = None

if TYPE_CHECKING:
    from APP.configs.app_config import RunConfig
    from APP.ui.app_ui import AppUI

logger = logging.getLogger(__name__)


class UploadCache:
    @staticmethod
    def load() -> dict:
        try:
            if PATHS.UPLOAD_CACHE_JSON.exists():
                return json.loads(PATHS.UPLOAD_CACHE_JSON.read_text(encoding="utf-8"))
        except Exception as e:
            logger.error(f"Lỗi khi tải upload cache: {e}")
        return {}

    @staticmethod
    def save(cache: dict) -> None:
        try:
            PATHS.UPLOAD_CACHE_JSON.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            logger.error(f"Lỗi khi lưu upload cache: {e}")

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
        except Exception as e:
            logger.warning(f"Lỗi khi tạo file signature cho '{path}': {e}")
            return ""

    @staticmethod
    def lookup(cache: dict, path: str) -> str:
        rec = cache.get(str(path))
        if not rec:
            return ""
        sig_now = UploadCache.file_sig(path)
        return rec["remote_name"] if sig_now and rec.get("sig") == sig_now else ""

    @staticmethod
    def put(cache: dict, path: str, remote_name: str) -> None:
        cache[str(path)] = {"sig": UploadCache.file_sig(path), "remote_name": remote_name}


def prepare_image(path: str, *, optimize: bool, app_dir: Path = PATHS.APP_DIR) -> str:
    """
    Optionally convert the image to an optimized JPEG copy.
    """
    if not optimize or Image is None:
        return path
    try:
        src = Path(path)
        tmpdir = app_dir / "tmp_upload"
        tmpdir.mkdir(parents=True, exist_ok=True)
        out = tmpdir / (src.stem + "_opt.jpg")

        with Image.open(src) as im:
            im.load()
            max_width = 1600
            if im.width > max_width:
                aspect_ratio = im.height / im.width
                new_height = int(max_width * aspect_ratio)
                work = im.resize((max_width, new_height), Image.Resampling.LANCZOS)
            else:
                work = im.copy()

            if work.mode in ("RGBA", "LA") or "transparency" in work.info:
                background = Image.new("RGB", work.size, (255, 255, 255))
                background.paste(work, (0, 0), work)
                work.close()
                work = background
            elif work.mode != "RGB":
                work = work.convert("RGB")

            work.save(out, format="JPEG", quality=85, optimize=True)
            work.close()

        if out.stat().st_size >= src.stat().st_size:
            try:
                out.unlink()
            except Exception:
                pass
            return str(src)
        return str(out)
    except Exception as e:
        logger.error(f"Lỗi khi chuẩn bị ảnh '{path}': {e}. Trả về path gốc.")
        return path


def as_inline_media_part(path: str) -> dict:
    mime, _ = mimetypes.guess_type(path)
    with open(path, "rb") as f:
        data = f.read()
    return {"mime_type": mime or "application/octet-stream", "data": data}


def file_or_inline_for_model(file_obj, prepared_path: Optional[str], original_path: str) -> object:
    try:
        if getattr(getattr(file_obj, "state", None), "name", None) == "ACTIVE":
            return file_obj
    except Exception:
        pass
    return as_inline_media_part(prepared_path or original_path)


def upload_one_file_for_worker(item) -> Tuple[str, object]:
    """Upload a single file to Gemini."""
    if genai is None:
        raise RuntimeError("google-generativeai SDK missing.")

    p, n, upath = item
    mime, _ = mimetypes.guess_type(upath)
    uf = genai.upload_file(path=upath, mime_type=mime or "application/octet-stream", display_name=n)
    
    retries, delay = 10, 0.6
    while retries > 0:
        try:
            f = genai.get_file(uf.name)
            st = getattr(getattr(f, "state", None), "name", None)
            if st == "ACTIVE":
                return (p, f)
            if st == "FAILED":
                raise RuntimeError("File in FAILED state.")
        except Exception as e:
            if retries <= 1:
                raise
        time.sleep(delay)
        retries -= 1
        delay = min(delay * 1.5, 3.0)
    return (p, uf)


def upload_images_parallel(app: "AppUI", cfg: "RunConfig", to_upload: List[Tuple]) -> Tuple[List, int]:
    """Upload images in parallel."""
    uploaded_files = []
    file_slots = [None] * len(app.results)

    if not to_upload:
        return file_slots, 0

    max_workers = max(1, min(len(to_upload), cfg.upload.upload_workers))
    steps_upload = len(to_upload)
    total_steps = steps_upload + 2

    try:
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            app.active_executor = ex
            futs = {ex.submit(upload_one_file_for_worker, (p, n, upath)): (i, p) for (i, p, n, upath) in to_upload}
            
            done_cnt = 0
            for fut in as_completed(futs):
                if app.stop_flag:
                    raise SystemExit("User stopped upload.")
                try:
                    (p_ret, fobj) = fut.result()
                    i, p = futs[fut]
                    file_slots[i] = fobj
                    uploaded_files.append((fobj, p))
                except Exception as e:
                    if app.stop_flag:
                        continue
                    raise
                
                done_cnt += 1
                app._update_progress(done_cnt, total_steps)
                app.results[i]["status"] = "Đã upload"
                app._update_tree_row(i, "Đã upload")
    finally:
        app.active_executor = None

    return file_slots, steps_upload


def delete_uploaded_file(uploaded_file):
    """Delete a file uploaded to Gemini."""
    try:
        if genai:
            genai.delete_file(uploaded_file.name)
            logger.debug(f"Đã xoá file Gemini: {uploaded_file.name}")
    except Exception as e:
        logger.warning(f"Lỗi khi xoá file Gemini '{uploaded_file.name}': {e}")

__all__ = [
    "UploadCache",
    "prepare_image",
    "upload_images_parallel",
    "delete_uploaded_file",
    "file_or_inline_for_model",
]
