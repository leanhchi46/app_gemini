"""
Gọi model Gemini, quản lý API key, upload file, sinh báo cáo
"""

def upload_file_to_gemini(path: str, mime_type: str, display_name: str, genai_lib=None):
    """
    Upload file lên Gemini, trả về đối tượng file.
    """
    if genai_lib is None:
        import google.generativeai as genai_lib
    return genai_lib.upload_file(path=path, mime_type=mime_type, display_name=display_name)

def generate_content_with_retry(model, parts, tries=2, base_delay=2.0):
    """
    Gọi model Gemini với retry.
    """
    import time
    last = None
    for i in range(tries):
        try:
            return model.generate_content(parts, request_options={"timeout": 1200})
        except Exception as e:
            last = e
            if i == tries - 1:
                raise
            time.sleep(base_delay)
            base_delay *= 1.7
    raise last
