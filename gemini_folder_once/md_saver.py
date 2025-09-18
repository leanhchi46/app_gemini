from __future__ import annotations
from datetime import datetime
from typing import TYPE_CHECKING
from . import utils

if TYPE_CHECKING:
    from ..gemini_batch_image_analyzer import GeminiFolderOnceApp, RunConfig
    from pathlib import Path

def save_md_report(app: "GeminiFolderOnceApp", text: str, cfg: "RunConfig") -> "Path":
    """
    Saves the markdown report file and cleans up old reports.
    """
    d = app._get_reports_dir(cfg.folder)
    if not d:
        return None
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = d / f"report_{ts}.md"
    out.write_text(text or "", encoding="utf-8")
    
    # Cleanup old .md files
    utils.cleanup_old_files(d, "report_*.md", 10)
    
    return out
