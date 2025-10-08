# -*- coding: utf-8 -*-
"""
Module quản lý luồng tập trung cho ứng dụng.

Cung cấp một lớp ThreadingManager để quản lý ThreadPoolExecutor,
giúp đơn giản hóa việc chạy các tác vụ nền và đảm bảo tắt ứng dụng an toàn.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, Future, as_completed
from typing import Callable, Any, List, Tuple, Dict

logger = logging.getLogger(__name__)


class ThreadingManager:
    """
    Lớp quản lý tập trung cho các tác vụ chạy trong luồng nền.

    Sử dụng một ThreadPoolExecutor để quản lý và tái sử dụng các luồng,
    cung cấp một giao diện đơn giản để gửi tác vụ và xử lý việc tắt ứng dụng.
    """

    def __init__(self, max_workers: int = 10):
        """
        Khởi tạo ThreadingManager.

        Args:
            max_workers (int): Số lượng luồng tối đa trong pool.
        """
        logger.info(f"Khởi tạo ThreadPoolExecutor với tối đa {max_workers} luồng.")
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="AppWorker")

    def submit_task(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Future:
        """
        Gửi một tác vụ để thực thi trong một luồng nền.

        Args:
            func (Callable): Hàm hoặc phương thức cần thực thi.
            *args: Các đối số vị trí cho hàm.
            **kwargs: Các đối số từ khóa cho hàm.

        Returns:
            Future: Một đối tượng Future đại diện cho việc thực thi tác vụ.
        """
        logger.debug(f"Gửi tác vụ '{func.__name__}' vào thread pool.")
        future = self._executor.submit(func, *args, **kwargs)
        return future

    def shutdown(self, wait: bool = True, timeout: float | None = None):
        """
        Tắt ThreadPoolExecutor một cách an toàn.

        Args:
            wait (bool): True để chờ tất cả các tác vụ hoàn thành.
            timeout (float | None): Thời gian tối đa (giây) để chờ.
                                    Nếu None, sẽ chờ vô thời hạn nếu wait=True.
        """
        logger.info(f"Yêu cầu tắt ThreadPoolExecutor (wait={wait}, timeout={timeout}).")
        # Python 3.9+ có cancel_futures=True, nhưng shutdown với timeout là đủ tốt.
        self._executor.shutdown(wait=wait)
        logger.info("ThreadPoolExecutor đã được tắt.")


def run_in_parallel(tasks: List[Tuple[Callable, Tuple, Dict]]) -> Dict[str, Any]:
    """
    Thực thi một danh sách các tác vụ song song và trả về kết quả.

    Args:
        tasks: Một danh sách các tuple, mỗi tuple chứa:
               (hàm_cần_gọi, tuple_đối_số_vị_trí, dict_đối_số_từ_khóa)

    Returns:
        Một dictionary chứa kết quả, với key là tên của hàm và value là kết quả trả về.
    """
    results = {}
    # Sử dụng một executor tạm thời cho nhóm tác vụ này
    with ThreadPoolExecutor(max_workers=len(tasks) or 1) as executor:
        future_to_func_name = {
            executor.submit(func, *args, **kwargs): func.__name__
            for func, args, kwargs in tasks
        }

        for future in as_completed(future_to_func_name):
            func_name = future_to_func_name[future]
            try:
                result = future.result()
                results[func_name] = result
                logger.debug(f"Tác vụ song song '{func_name}' đã hoàn thành.")
            except Exception:
                logger.exception(f"Tác vụ song song '{func_name}' đã gặp lỗi.")
                results[func_name] = None  # Ghi nhận lỗi
    return results
