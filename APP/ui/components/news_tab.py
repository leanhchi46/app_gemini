# -*- coding: utf-8 -*-
"""
Thành phần giao diện người dùng cho tab hiển thị tin tức kinh tế.
"""
from __future__ import annotations

import logging
import tkinter as tk
from datetime import datetime
from tkinter import ttk
from typing import TYPE_CHECKING, Any, Dict, List, Optional

import pytz

if TYPE_CHECKING:
    from APP.ui.app_ui import AppUI

logger = logging.getLogger(__name__)


class NewsTab:
    """
    Quản lý giao diện và logic cho tab "News".
    """

    def __init__(self, app: "AppUI", parent: ttk.Notebook):
        """
        Khởi tạo tab News.

        Args:
            app (AppUI): Instance của ứng dụng chính.
            parent (ttk.Notebook): Widget notebook cha.
        """
        self.app = app
        self.frame = ttk.Frame(parent, padding=8)
        parent.add(self.frame, text="News")

        self._build_widgets()

    def _build_widgets(self):
        """Xây dựng các thành phần con của tab."""
        self.frame.columnconfigure(0, weight=1)
        self.frame.rowconfigure(1, weight=1)  # Cập nhật row để treeview chiếm toàn bộ không gian

        header_frame = ttk.Frame(self.frame)
        header_frame.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        header_frame.columnconfigure(0, weight=1)

        self.last_updated_var = tk.StringVar(value="Chưa có dữ liệu tin tức từ dịch vụ nền.")
        self.last_updated_label = ttk.Label(header_frame, textvariable=self.last_updated_var, anchor="w")
        self.last_updated_label.grid(row=0, column=0, sticky="w")

        # Treeview để hiển thị danh sách tin tức
        cols = ("time", "country", "event", "impact")
        self.tree = ttk.Treeview(self.frame, columns=cols, show="headings")
        
        # Định dạng các cột
        self.tree.heading("time", text="Thời gian (Local)")
        self.tree.column("time", width=150, anchor="w")
        
        self.tree.heading("country", text="Quốc gia")
        self.tree.column("country", width=100, anchor="w")

        self.tree.heading("event", text="Sự kiện")
        self.tree.column("event", width=500, anchor="w")

        self.tree.heading("impact", text="Tầm ảnh hưởng")
        self.tree.column("impact", width=100, anchor="center")

        self.tree.grid(row=1, column=0, sticky="nsew")

        # Scrollbar
        scrollbar = ttk.Scrollbar(self.frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.grid(row=1, column=1, sticky="ns")

        # Định nghĩa các tag màu sắc cho mức độ ảnh hưởng
        self.tree.tag_configure("high", background="#FADBD8")
        self.tree.tag_configure("medium", background="#FEF9E7")
        self.tree.tag_configure("low", background="#E8F8F5")

    def update_news_list(
        self,
        events: List[Dict[str, Any]],
        *,
        last_updated: Optional[datetime] = None,
        timezone: Optional[str] = None,
    ):
        """
        Xóa danh sách cũ và cập nhật Treeview với dữ liệu tin tức mới.

        Args:
            events (List[Dict[str, Any]]): Danh sách các sự kiện tin tức.
            last_updated (datetime | None): Thời điểm cache được cập nhật lần cuối.
            timezone (str | None): Múi giờ địa phương để hiển thị thời gian.
        """
        tz_label = self._format_last_updated(last_updated, timezone, len(events))
        self.last_updated_var.set(tz_label)

        # Xóa tất cả các mục hiện có
        for item in self.tree.get_children():
            self.tree.delete(item)

        if not events:
            # Cung cấp hướng dẫn chi tiết hơn cho người dùng
            guidance_message = (
                "Không tìm thấy sự kiện nào. Vui lòng kiểm tra:\n"
                "1. Đã nhập Symbol trong Options -> Services -> MT5.\n"
                "2. Đã bật FMP hoặc TE và nhập API key trong Options -> API Keys.\n"
                "3. Có thể không có tin tức quan trọng nào trong 7 ngày tới."
            )
            self.tree.insert("", "end", values=("", "", guidance_message, ""))
            return

        # Thêm các mục mới
        for event in events:
            impact_str = str(event.get("impact", "")).lower()
            if "high" in impact_str or "3" in impact_str:
                tag = "high"
            elif "medium" in impact_str or "2" in impact_str:
                tag = "medium"
            else:
                tag = "low"

            self.tree.insert(
                "",
                "end",
                values=(
                    event.get("when_local", "").strftime("%Y-%m-%d %H:%M") if event.get("when_local") else "N/A",
                    event.get("country", "N/A"),
                    event.get("title", "N/A"),
                    impact_str.capitalize(),
                ),
                tags=(tag,),
            )

    def _format_last_updated(
        self,
        last_updated: Optional[datetime],
        timezone: Optional[str],
        event_count: int,
    ) -> str:
        """Định dạng thông báo thời gian cập nhật cuối cho label giao diện."""

        if not last_updated:
            return "Chưa có dữ liệu tin tức từ dịch vụ nền."

        tz_name = timezone or "UTC"
        try:
            tz = pytz.timezone(tz_name)
            localized = last_updated.astimezone(tz)
        except Exception:
            logger.debug("Không thể chuyển đổi múi giờ '%s', sử dụng UTC.", tz_name)
            tz_name = "UTC"
            localized = last_updated.astimezone(pytz.utc)

        return (
            f"Cập nhật lần cuối: {localized.strftime('%Y-%m-%d %H:%M')} ({tz_name})"
            f" | {event_count} sự kiện quan trọng"
        )
