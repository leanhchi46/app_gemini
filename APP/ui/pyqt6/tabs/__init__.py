"""Các tab PyQt6 riêng biệt cho cửa sổ chính."""

from .overview import OverviewTab
from .chart import ChartTabWidget
from .history import HistoryEntry, HistoryTabWidget
from .news import NewsTabWidget
from .options import OptionsTabWidget
from .prompt import PromptTabWidget
from .report import ReportEntry, ReportTabWidget

__all__ = [
    "OverviewTab",
    "ChartTabWidget",
    "NewsTabWidget",
    "PromptTabWidget",
    "HistoryTabWidget",
    "HistoryEntry",
    "ReportTabWidget",
    "ReportEntry",
    "OptionsTabWidget",
]
