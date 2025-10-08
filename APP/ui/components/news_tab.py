# -*- coding: utf-8 -*-
"""
Thành phần giao diện người dùng cho tab hiển thị tin tức kinh tế.
"""
from __future__ import annotations

import logging
import tkinter as tk
from tkinter import ttk
from typing import TYPE_CHECKING, Any, Dict, List

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
        self.frame.rowconfigure(0, weight=1) # Cập nhật row để treeview chiếm toàn bộ không gian

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

        self.tree.grid(row=0, column=0, sticky="nsew")

        # Scrollbar
        scrollbar = ttk.Scrollbar(self.frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.grid(row=0, column=1, sticky="ns")

        # Định nghĩa các tag màu sắc cho mức độ ảnh hưởng
        self.tree.tag_configure("high", background="#FADBD8")
        self.tree.tag_configure("medium", background="#FEF9E7")
        self.tree.tag_configure("low", background="#E8F8F5")

    def update_news_list(self, events: List[Dict[str, Any]]):
        """
        Xóa danh sách cũ và cập nhật Treeview với dữ liệu tin tức mới.

        Args:
            events (List[Dict[str, Any]]): Danh sách các sự kiện tin tức.
        """
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
