"""
Quản lý cache upload, workspace, trạng thái phiên làm việc
"""

import json
from pathlib import Path


def load_upload_cache(path: Path) -> dict:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def save_upload_cache(cache: dict, path: Path):
    try:
        path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def cache_lookup(cache: dict, path: str, file_sig_func) -> str:
    rec = cache.get(path)
    if not rec:
        return ""
    sig_now = file_sig_func(path)
    return rec["remote_name"] if sig_now and rec.get("sig") == sig_now else ""


def cache_put(cache: dict, path: str, remote_name: str, file_sig_func):
    cache[path] = {"sig": file_sig_func(path), "remote_name": remote_name}