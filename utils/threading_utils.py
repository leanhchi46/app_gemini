"""
Hàng đợi UI, thread-safe, các tiện ích liên quan đến threading
"""

import queue

def enqueue_ui(ui_queue, func):
    """
    Đưa hàm vào hàng đợi UI thread-safe.
    """
    ui_queue.put(func)

def poll_ui_queue(root, ui_queue, interval_ms=80):
    """
    Lặp kiểm tra hàng đợi UI và thực thi các hàm trong main thread.
    """
    try:
        while True:
            func = ui_queue.get_nowait()
            try:
                func()
            except Exception:
                pass
    except queue.Empty:
        pass
    root.after(interval_ms, lambda: poll_ui_queue(root, ui_queue, interval_ms))
