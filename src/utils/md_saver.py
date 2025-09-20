from __future__ import annotations
from datetime import datetime
from typing import TYPE_CHECKING
from . import utils
import re

if TYPE_CHECKING:
    from ..gemini_batch_image_analyzer import GeminiFolderOnceApp, RunConfig
    from pathlib import Path

def extract_human_readable_report(text: str) -> str:
    """
    Extracts the human-readable parts (Task 2 and 3) from the AI's full response.
    """
    # Find the start of the human-readable summary (Task 2)
    # We use regex to be more flexible with potential whitespace or minor variations.
    match = re.search(r"###\s+NHIỆM VỤ 2", text, re.IGNORECASE)
    
    if match:
        # Return everything from the start of Task 2 to the end of the string
        return text[match.start():]
    else:
        # Fallback: if the specific header isn't found, return the original text
        # to avoid saving an empty file.
        return text

def save_md_report(app: "GeminiFolderOnceApp", text: str, cfg: "RunConfig") -> "Path":
    """
    Saves the markdown report file and cleans up old reports.
    Now extracts only the human-readable part of the report.
    """
    d = app._get_reports_dir(cfg.folder)
    if not d:
        return None
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = d / f"report_{ts}.md"
    
    # Extract only the human-readable part before saving
    human_report = extract_human_readable_report(text)
    
    out.write_text(human_report or "", encoding="utf-8")
    
    # Cleanup old .md files
    utils.cleanup_old_files(d, "report_*.md", 10)
    
    return out
