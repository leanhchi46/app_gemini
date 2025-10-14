from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from APP.configs.app_config import RunConfig
from APP.services import mt5_service
from APP.utils.safe_data import SafeData


@dataclass(frozen=True)
class SpreadMetrics:
    current_pips: Optional[float]
    threshold_pips: Optional[float]
    median_5m_pips: Optional[float]
    p90_5m_pips: Optional[float]
    median_30m_pips: Optional[float]
    p90_30m_pips: Optional[float]
    atr_pct: Optional[float]

    def to_dict(self) -> dict[str, Optional[float]]:
        return {
            "current_pips": self.current_pips,
            "threshold_pips": self.threshold_pips,
            "median_5m_pips": self.median_5m_pips,
            "p90_5m_pips": self.p90_5m_pips,
            "median_30m_pips": self.median_30m_pips,
            "p90_30m_pips": self.p90_30m_pips,
            "atr_pct": self.atr_pct,
        }


@dataclass(frozen=True)
class AtrMetrics:
    atr_m5_pips: Optional[float]
    min_required_pips: Optional[float]
    adr20_pips: Optional[float]
    atr_pct_of_adr20: Optional[float]

    def to_dict(self) -> dict[str, Optional[float]]:
        return {
            "atr_m5_pips": self.atr_m5_pips,
            "min_required_pips": self.min_required_pips,
            "adr20_pips": self.adr20_pips,
            "atr_pct_of_adr20": self.atr_pct_of_adr20,
        }


@dataclass(frozen=True)
class KeyLevelSnapshot:
    name: Optional[str]
    price: Optional[float]
    relation: Optional[str]
    distance_pips: Optional[float]

    def to_dict(self) -> dict[str, Optional[float | str]]:
        return {
            "name": self.name,
            "price": self.price,
            "relation": self.relation,
            "distance_pips": self.distance_pips,
        }


@dataclass(frozen=True)
class KeyLevelMetrics:
    nearest: Optional[KeyLevelSnapshot]
    threshold_pips: Optional[float]
    levels: tuple[KeyLevelSnapshot, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "nearest": self.nearest.to_dict() if self.nearest else None,
            "threshold_pips": self.threshold_pips,
            "levels": [level.to_dict() for level in self.levels],
        }


@dataclass(frozen=True)
class NoTradeMetrics:
    spread: SpreadMetrics
    atr: AtrMetrics
    key_levels: KeyLevelMetrics
    collected_at: Optional[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "spread": self.spread.to_dict(),
            "atr": self.atr.to_dict(),
            "key_levels": self.key_levels.to_dict(),
            "collected_at": self.collected_at,
        }


def _points_stat_to_pips(value: Any, info: dict | Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(mt5_service.points_to_pips(float(value), info))
    except Exception:
        return None


def _price_to_pips(price_delta: Any, info: dict | Any) -> Optional[float]:
    if price_delta is None:
        return None
    point = mt5_service.info_get(info, "point", 0.0)
    if not point:
        return None
    try:
        points = float(price_delta) / float(point)
    except (TypeError, ValueError):
        return None
    return mt5_service.points_to_pips(points, info)


def _build_key_level_snapshots(levels: list[dict[str, Any]] | None) -> tuple[KeyLevelSnapshot, ...]:
    if not levels:
        return ()
    snapshots: list[KeyLevelSnapshot] = []
    for level in levels:
        snapshots.append(
            KeyLevelSnapshot(
                name=level.get("name"),
                price=_try_float(level.get("price")),
                relation=level.get("relation"),
                distance_pips=_try_float(level.get("distance_pips")),
            )
        )
    return tuple(snapshots)


def _try_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def collect_no_trade_metrics(
    safe_mt5_data: Optional[SafeData], cfg: Optional[RunConfig] = None
) -> Optional[NoTradeMetrics]:
    """Extracts reusable telemetry for No-Trade conditions and UI surfaces."""

    if not safe_mt5_data or not safe_mt5_data.is_valid():
        return None

    info = safe_mt5_data.get("info") or {}
    tick = safe_mt5_data.get("tick") or {}

    current_spread = None
    if info and tick:
        current_spread = mt5_service.get_spread_pips(info, tick)

    tick_stats_5m = safe_mt5_data.get("tick_stats_5m") or {}
    tick_stats_30m = safe_mt5_data.get("tick_stats_30m") or {}

    spread_metrics = SpreadMetrics(
        current_pips=_try_float(current_spread),
        threshold_pips=_try_float(getattr(cfg.no_trade, "spread_max_pips", None) if cfg else None),
        median_5m_pips=_points_stat_to_pips(tick_stats_5m.get("median_spread"), info),
        p90_5m_pips=_points_stat_to_pips(tick_stats_5m.get("p90_spread"), info),
        median_30m_pips=_points_stat_to_pips(tick_stats_30m.get("median_spread"), info),
        p90_30m_pips=_points_stat_to_pips(tick_stats_30m.get("p90_spread"), info),
        atr_pct=_try_float((safe_mt5_data.get("atr_norm") or {}).get("spread_as_pct_of_atr_m5")),
    )

    atr_price = safe_mt5_data.get_nested("volatility.ATR.M5")
    adr_block = safe_mt5_data.get("adr") or {}
    adr20_price = adr_block.get("d20")

    atr_metrics = AtrMetrics(
        atr_m5_pips=_price_to_pips(atr_price, info),
        min_required_pips=_try_float(getattr(cfg.no_trade, "min_atr_m5_pips", None) if cfg else None),
        adr20_pips=_price_to_pips(adr20_price, info),
        atr_pct_of_adr20=_try_compute_ratio(atr_price, adr20_price),
    )

    key_levels = _build_key_level_snapshots(safe_mt5_data.get("key_levels_nearby"))
    nearest_level = _pick_nearest_level(key_levels)

    key_level_metrics = KeyLevelMetrics(
        nearest=nearest_level,
        threshold_pips=_try_float(getattr(cfg.no_trade, "min_dist_keylvl_pips", None) if cfg else None),
        levels=key_levels,
    )

    collected_at = safe_mt5_data.get("broker_time")

    return NoTradeMetrics(
        spread=spread_metrics,
        atr=atr_metrics,
        key_levels=key_level_metrics,
        collected_at=collected_at,
    )


def _pick_nearest_level(levels: tuple[KeyLevelSnapshot, ...]) -> Optional[KeyLevelSnapshot]:
    nearest: Optional[KeyLevelSnapshot] = None
    nearest_dist = float("inf")
    for level in levels:
        if level.distance_pips is None:
            continue
        dist = abs(level.distance_pips)
        if dist < nearest_dist:
            nearest = level
            nearest_dist = dist
    return nearest


def _try_compute_ratio(numerator: Any, denominator: Any) -> Optional[float]:
    try:
        num = float(numerator)
        den = float(denominator)
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    if den == 0:
        return None
    return (num / den) * 100.0
