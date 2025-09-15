from __future__ import annotations

import json
import hashlib
import mimetypes
import time
from pathlib import Path
from typing import Optional, Tuple

try:
    import google.generativeai as genai  # type: ignore
except Exception as _e:  # pragma: no cover - import validated by caller
    genai = None  # type: ignore

try:
    from PIL import Image  # type: ignore
except Exception:  # pragma: no cover - optional optimization
    Image = None  # type: ignore

from .constants import APP_DIR, UPLOAD_CACHE_JSON


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
    """Optionally convert the image to an optimized PNG copy, else return original path.
    If optimization produces a larger file, keeps the original.
    """
    if not optimize or Image is None:
        return path
    try:
        src = Path(path)
        tmpdir = app_dir / "tmp_upload"
        tmpdir.mkdir(parents=True, exist_ok=True)
        out = tmpdir / (src.stem + "_opt.png")

        with Image.open(src) as im:  # type: ignore[attr-defined]
            im.load()
            has_alpha = (im.mode in ("RGBA", "LA")) or ("transparency" in im.info)
            work = im.convert("RGBA") if has_alpha else im.convert("RGB")
        work.save(out, format="PNG", optimize=True)  # type: ignore[attr-defined]
        work.close()  # type: ignore[union-attr]

        try:
            if out.stat().st_size >= src.stat().st_size:
                try:
                    out.unlink()
                except Exception:
                    pass
                return str(src)
        except Exception:
            try:
                out.unlink()
            except Exception:
                pass
            return str(src)

        return str(out)
    except Exception:
        return path


def as_inline_media_part(path: str) -> dict:
    mime, _ = mimetypes.guess_type(path)
    with open(path, "rb") as f:
        data = f.read()
    return {"mime_type": mime or "application/octet-stream", "data": data}


def file_or_inline_for_model(file_obj, prepared_path: Optional[str], original_path: str) -> object:
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
        raise RuntimeError("google-generativeai SDK missing. Install: pip install google-generativeai")

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
        except Exception:
            if retries <= 1:
                raise
        time.sleep(delay)
        retries -= 1
        delay = min(delay * 1.5, 3.0)
    return (p, uf)

