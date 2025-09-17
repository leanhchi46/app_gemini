from __future__ import annotations
from typing import Any, Optional

class SafeMT5Data:
    """
    A wrapper class for the MT5 data dictionary to provide safe access to nested
    values, preventing 'NoneType' object has no attribute 'get' errors.
    """
    def __init__(self, data: Optional[dict[str, Any]]):
        self._data = data if data is not None else {}

    @property
    def raw(self) -> dict[str, Any]:
        """Returns the raw underlying data dictionary."""
        return self._data

    def get(self, key: str, default: Any = None) -> Any:
        """Safe getter for top-level keys."""
        return self._data.get(key, default)

    def get_tick_value(self, key: str, default: Any = None) -> Any:
        """Safely gets a value from the 'tick' dictionary."""
        return (self._data.get("tick") or {}).get(key, default)

    def get_info_value(self, key: str, default: Any = None) -> Any:
        """Safely gets a value from the 'info' dictionary."""
        return (self._data.get("info") or {}).get(key, default)

    def get_pip_value(self, key: str, default: Any = None) -> Any:
        """Safely gets a value from the 'pip' dictionary."""
        return (self._data.get("pip") or {}).get(key, default)

    def get_daily_level(self, key: str, default: Any = None) -> Any:
        """Safely gets a value from the 'levels.daily' dictionary."""
        return ((self._data.get("levels") or {}).get("daily") or {}).get(key, default)

    def get_prev_day_level(self, key: str, default: Any = None) -> Any:
        """Safely gets a value from the 'levels.prev_day' dictionary."""
        return ((self._data.get("levels") or {}).get("prev_day") or {}).get(key, default)

    def get_vwap(self, key: str, default: Any = None) -> Any:
        """Safely gets a value from the 'vwap' dictionary."""
        return (self._data.get("vwap") or {}).get(key, default)

    def get_ema(self, timeframe: str, key: str, default: Any = None) -> Any:
        """Safely gets an EMA value for a given timeframe."""
        return (((self._data.get("trend_refs") or {}).get("EMA") or {}).get(timeframe) or {}).get(key, default)
        
    def get_ict_pattern(self, pattern_key: str, default: Any = None) -> Any:
        """Safely gets a value from the 'ict_patterns' dictionary."""
        return (self._data.get("ict_patterns") or {}).get(pattern_key, default)

    def get_rr_projection(self, key: str, default: Any = None) -> Any:
        """Safely gets a value from the 'rr_projection' dictionary."""
        return (self._data.get("rr_projection") or {}).get(key, default)

    def get_plan_value(self, key: str, default: Any = None) -> Any:
        """Safely gets a value from the 'plan' dictionary."""
        return (self._data.get("plan") or {}).get(key, default)
