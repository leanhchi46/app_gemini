"""
Xử lý ảnh, nạp ảnh, tối ưu ảnh trước khi upload
"""

from pathlib import Path

def prepare_image_for_upload_cfg(path: str, optimize: bool, ImageLib=None, app_dir=None) -> str:
    """
    Xử lý ảnh: tối ưu lossless nếu cần, trả về đường dẫn file đã chuẩn bị.
    """
    if not optimize or ImageLib is None:
        return path
    try:
        src = Path(path)
        tmpdir = Path(app_dir) / "tmp_upload" if app_dir else Path("./tmp_upload")
        tmpdir.mkdir(parents=True, exist_ok=True)
        out = tmpdir / (src.stem + "_opt.png")
        with ImageLib.open(src) as im:
            im.load()
            has_alpha = (im.mode in ("RGBA", "LA")) or ("transparency" in im.info)
            work = im.convert("RGBA") if has_alpha else im.convert("RGB")
        work.save(out, format="PNG", optimize=True)
        work.close()
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