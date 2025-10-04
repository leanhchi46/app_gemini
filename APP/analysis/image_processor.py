from __future__ import annotations

import json
import hashlib
import mimetypes
import time
from pathlib import Path
from typing import Any, Optional, Tuple, List, TYPE_CHECKING, Dict
from concurrent.futures import ThreadPoolExecutor, as_completed
import logging

from APP.configs.workspace_config import get_workspace_dir, get_upload_cache_path

logger = logging.getLogger(__name__)

try:
    import google.generativeai as genai
except ImportError:
    genai = None
    logger.warning("Không thể import google.generativeai.")

try:
    from PIL import Image
except ImportError:
    Image = None
    logger.warning("Không thể import PIL.Image. Tối ưu hóa ảnh sẽ bị vô hiệu hóa.")

if TYPE_CHECKING:
    from APP.ui.app_ui import AppUI
    from APP.configs.app_config import RunConfig


class UploadCache:
    @staticmethod
    def load() -> dict:
        cache_path = get_upload_cache_path()
        try:
            if cache_path.exists():
                return json.loads(cache_path.read_text(encoding="utf-8"))
        except (IOError, json.JSONDecodeError) as e:
            logger.error(f"Lỗi khi tải upload cache: {e}")
        return {}

    @staticmethod
    def save(cache: dict):
        cache_path = get_upload_cache_path()
        try:
            cache_path.write_text(json.dumps(cache, indent=2), encoding="utf-8")
        except IOError as e:
            logger.error(f"Lỗi khi lưu upload cache: {e}")

    @staticmethod
    def _file_sig(path: str) -> str:
        p = Path(path)
        try:
            size = p.stat().st_size
            mtime = int(p.stat().st_mtime)
            h = hashlib.sha1(p.read_bytes()).hexdigest()
            return f"{size}:{mtime}:{h[:16]}"
        except IOError as e:
            logger.warning(f"Lỗi khi tạo chữ ký tệp cho '{path}': {e}")
            return ""

    @staticmethod
    def lookup(cache: dict, path: str) -> str:
        rec = cache.get(str(path))
        if not rec:
            return ""
        sig_now = UploadCache._file_sig(path)
        return rec.get("remote_name", "") if sig_now and rec.get("sig") == sig_now else ""

    @staticmethod
    def put(cache: dict, path: str, remote_name: str):
        cache[str(path)] = {"sig": UploadCache._file_sig(path), "remote_name": remote_name}


def prepare_image(path: str, *, optimize: bool) -> str:
    if not optimize or not Image:
        return path
    try:
        src = Path(path)
        tmpdir = get_workspace_dir() / "tmp_upload"
        tmpdir.mkdir(parents=True, exist_ok=True)
        out = tmpdir / (src.stem + "_opt.jpg")
        with Image.open(src) as im:
            work = im.copy()
            if work.width > 1600:
                aspect = work.height / work.width
                work = work.resize((1600, int(1600 * aspect)), Image.Resampling.LANCZOS)
            if work.mode in ("RGBA", "LA"):
                background = Image.new("RGB", work.size, (255, 255, 255))
                background.paste(work, (0, 0), work)
                work = background
            elif work.mode != "RGB":
                work = work.convert("RGB")
            work.save(out, format="JPEG", quality=85, optimize=True)
        if out.stat().st_size >= src.stat().st_size:
            out.unlink(missing_ok=True)
            return str(src)
        return str(out)
    except Exception as e:
        logger.error(f"Lỗi khi chuẩn bị ảnh '{path}': {e}")
        return path


def prepare_images_for_upload(
    paths: List[str], names: List[str], cache_enabled: bool, optimize: bool
) -> Tuple[Dict, List, List]:
    """Chuẩn bị hình ảnh để tải lên, kiểm tra cache."""
    cache = UploadCache.load() if cache_enabled else {}
    prepared_map = {}
    to_upload = []
    file_slots = [None] * len(paths)

    for i, (p, n) in enumerate(zip(paths, names)):
        if cache_enabled:
            cached_remote = UploadCache.lookup(cache, p)
            if cached_remote:
                try:
                    f = genai.get_file(cached_remote)
                    if f.state.name == "ACTIVE":
                        file_slots[i] = f
                        prepared_map[i] = None
                        continue
                except Exception:
                    pass  # Tải lên lại nếu get_file thất bại

        upath = prepare_image(p, optimize=optimize)
        to_upload.append((i, p, n, upath))
        prepared_map[i] = upath
    return prepared_map, file_slots, to_upload


def update_upload_cache(uploaded_files: List[Tuple[Any, str]]):
    """Cập nhật và lưu cache upload."""
    cache = UploadCache.load()
    for f, p in uploaded_files:
        UploadCache.put(cache, p, f.name)
    UploadCache.save(cache)


def as_inline_media_part(path: str) -> dict:
    """Chuyển đổi một tệp thành một phần media inline cho API."""
    mime, _ = mimetypes.guess_type(path)
    with open(path, "rb") as f:
        data = f.read()
    return {"mime_type": mime or "application/octet-stream", "data": data}


def file_or_inline_for_model(file_obj, prepared_path: Optional[str], original_path: str) -> object:
    """Trả về đối tượng tệp nếu ACTIVE, nếu không trả về dữ liệu inline."""
    if file_obj and file_obj.state.name == "ACTIVE":
        return file_obj
    use_path = prepared_path or original_path
    return as_inline_media_part(use_path)


def prepare_media_for_gemini(file_slots: List, prepared_map: Dict, paths: List[str]) -> List:
    """Chuẩn bị danh sách media (tệp hoặc inline) để gửi đến Gemini."""
    all_media = []
    for i, f in enumerate(file_slots):
        if f is None:
            all_media.append(as_inline_media_part(prepared_map.get(i) or paths[i]))
        else:
            all_media.append(file_or_inline_for_model(f, prepared_map.get(i), paths[i]))
    return all_media


def upload_one_file(item: tuple) -> tuple[int, str, Any]:
    """Tải một tệp lên Gemini và chờ cho đến khi nó ở trạng thái ACTIVE."""
    if not genai:
        raise RuntimeError("SDK google-generativeai chưa được cài đặt.")
    
    item_idx, original_path, display_name, upload_path = item
    mime_type, _ = mimetypes.guess_type(upload_path)
    
    uploaded_file = genai.upload_file(
        path=upload_path, mime_type=mime_type, display_name=display_name
    )

    for _ in range(10):
        time.sleep(0.6)
        file = genai.get_file(uploaded_file.name)
        if file.state.name == "ACTIVE":
            return item_idx, original_path, file
        if file.state.name == "FAILED":
            raise RuntimeError(f"Tải tệp '{display_name}' thất bại.")
            
    return item_idx, original_path, uploaded_file


def upload_images_parallel(
    app: AppUI, cfg: RunConfig, to_upload: List[Tuple], file_slots: List
) -> Tuple[List, List]:
    """Tải lên nhiều hình ảnh song song bằng ThreadPoolExecutor."""
    if not to_upload:
        return file_slots, []

    uploaded_files = []
    max_workers = min(len(to_upload), cfg.upload_workers)
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        app.active_executor = executor
        future_to_info = {executor.submit(upload_one_file, item): item[0] for item in to_upload}

        for future in as_completed(future_to_info):
            if app.stop_flag:
                break
            
            try:
                item_idx, original_path, file_obj = future.result()
                file_slots[item_idx] = file_obj
                uploaded_files.append((file_obj, original_path))
                app.update_tree_row(item_idx, "Đã upload")
            except Exception as e:
                item_idx = future_to_info[future]
                logger.error(f"Lỗi khi tải lên tệp cho chỉ mục {item_idx}: {e}")
                app.update_tree_row(item_idx, "Lỗi upload")

    app.active_executor = None
    return file_slots, uploaded_files


def delete_uploaded_files(uploaded_files: List[Tuple[Any, str]]):
    """Xóa các tệp đã được tải lên khỏi Gemini."""
    if not genai:
        return
    for file_obj, _ in uploaded_files:
        try:
            genai.delete_file(file_obj.name)
            logger.info(f"Đã xóa tệp Gemini: {file_obj.name}")
        except Exception as e:
            logger.warning(f"Lỗi khi xóa tệp Gemini '{file_obj.name}': {e}")
