from __future__ import annotations
from typing import Any, Optional
from datetime import datetime

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

    def get_active_session(self) -> Optional[str]:
        """Determines the currently active trading session."""
        sessions = self._data.get("sessions_today", {})
        if not sessions:
            return None
        
        now_hhmm = datetime.now().strftime("%H:%M")
        
        for session_name, details in sessions.items():
            start = details.get("start")
            end = details.get("end")
            if start and end and start <= now_hhmm < end:
                return session_name
        return None

    def get_atr_pips(self, timeframe: str, default: float = 0.0) -> float:
        """Safely gets the ATR for a timeframe and converts it to pips."""
        try:
            atr_val = (self._data.get("volatility", {}).get("ATR", {}) or {}).get(timeframe)
            pip_size = self.get_pip_value("size")
            if atr_val is not None and pip_size is not None and pip_size > 0:
                return atr_val / pip_size
        except (TypeError, ValueError):
            pass
        return default
