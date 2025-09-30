# src/utils/file_utils.py
from __future__ import annotations

import google.generativeai as genai
import logging

def _maybe_delete(uploaded_file):
    """
    Thực hiện xóa file đã upload lên Gemini nếu cấu hình cho phép.
    """
    try:
        genai.delete_file(uploaded_file.name)
    except Exception as e:
        logging.warning(f"Lỗi khi xoá file Gemini: {e}")
