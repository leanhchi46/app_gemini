from __future__ import annotations

from typing import Tuple, List, Optional, Dict, Any

from .config import RunConfig
from .mt5_utils import pip_size_from_info
from . import news


def check_spread(mt5_ctx: dict, cfg: RunConfig) -> Optional[str]:
    """Return reason string if current spread is too high, else None.

    Prefers 5m p90, falls back to median; compares using nt_spread_factor
    with a lower bound of 1.0, matching existing behavior.
    """
    info = (mt5_ctx.get("info") or {})
    tick_stats = (mt5_ctx.get("tick_stats_5m") or {})
    spread_cur = info.get("spread_current")
    p90_sp = tick_stats.get("p90_spread")
    median_sp = tick_stats.get("median_spread")
    if spread_cur is None:
        return None
    try:
        fac = max(1.0, float(cfg.nt_spread_factor))
    except Exception:
        fac = 1.0
    if p90_sp:
        if spread_cur > p90_sp * fac:
            return f"Spread cao (cur={spread_cur}, p90={p90_sp}, factor={fac})"
    elif median_sp:
        if spread_cur > median_sp * (fac + 0.1):
            return f"Spread cao (cur={spread_cur}, median~{median_sp})"
    return None


def check_atr_m5(mt5_ctx: dict, cfg: RunConfig) -> Optional[str]:
    """Return reason string if ATR M5 (in pips) is too low, else None."""
    info = (mt5_ctx.get("info") or {})
    vol = (mt5_ctx.get("volatility") or {}).get("ATR") or {}
    atr_m5 = vol.get("M5")
    pip_size = pip_size_from_info(info)
    if not atr_m5 or not pip_size or pip_size <= 0:
        return None
    try:
        atr_m5_pips = float(atr_m5) / pip_size
        if atr_m5_pips < float(cfg.nt_min_atr_m5_pips):
            return f"ATR M5 th?p ({atr_m5_pips:.1f} pips)"
    except Exception:
        pass
    return None


def check_liquidity(mt5_ctx: dict, cfg: RunConfig) -> Optional[str]:
    """Return reason string if ticks-per-minute is below threshold, else None."""
    tick_stats = (mt5_ctx.get("tick_stats_5m") or {})
    tpm = tick_stats.get("ticks_per_min")
    if tpm is None:
        return None
    try:
        if tpm < int(cfg.nt_min_ticks_per_min):
            return f"Thanh kho?n th?p (ticks/min={tpm})"
    except Exception:
        pass
    return None


def pretrade_hard_filters(mt5_ctx: dict, cfg: RunConfig) -> Tuple[bool, List[str], List[str]]:
    """Evaluate NO-TRADE hard filters using MT5 context and run config.

    Returns a tuple (ok, reasons). If ok is False, reasons contains human
    readable explanations for why trading should be skipped.
    """
    if not getattr(cfg, "nt_enabled", False):
        return True, [], []

    reasons: List[str] = []
    codes: List[str] = []
    checks: List[tuple] = [
        (check_spread, "spread"),
        (check_atr_m5, "atr_m5"),
        (check_liquidity, "liquidity"),
    ]
    for fn, code in checks:
        try:
            why = fn(mt5_ctx, cfg)
            if why:
                reasons.append(why)
                codes.append(code)
        except Exception:
            # Ignore individual check failures and proceed conservatively
            pass
    return (len(reasons) == 0), reasons, codes


def _allowed_session_now(mt5_ctx: dict, cfg: RunConfig) -> bool:
    """Return True if current time falls within any allowed session.

    Uses `mt5_ctx["sessions_today"]` with keys: asia, london, newyork_pre, newyork_post
    and RunConfig flags trade_allow_session_asia/london/ny.
    If all three flags are False (no explicit restriction), allow all times.
    """
    try:
        ss = (mt5_ctx.get("sessions_today") or {})
        from datetime import datetime

        now = datetime.now().strftime("%H:%M")

        def _in(r: Optional[Dict[str, Any]]) -> bool:
            return bool(r and r.get("start") and r.get("end") and r["start"] <= now < r["end"])

        ok = False
        if getattr(cfg, "trade_allow_session_asia", False) and _in(ss.get("asia")):
            ok = True
        if getattr(cfg, "trade_allow_session_london", False) and _in(ss.get("london")):
            ok = True
        if getattr(cfg, "trade_allow_session_ny", False) and (
            _in(ss.get("newyork_pre")) or _in(ss.get("newyork_post"))
        ):
            ok = True

        if not (
            getattr(cfg, "trade_allow_session_asia", False)
            or getattr(cfg, "trade_allow_session_london", False)
            or getattr(cfg, "trade_allow_session_ny", False)
        ):
            # No restrictions configured -> allow
            ok = True
        return ok
    except Exception:
        # On any error, do not block by session
        return True


def evaluate(
    mt5_ctx: dict,
    cfg: RunConfig,
    *,
    cache_events: Optional[List[Dict[str, Any]]] = None,
    cache_fetch_time: Optional[float] = None,
    ttl_sec: int = 300,
) -> Tuple[bool, List[str], List[Dict[str, Any]], float, Dict[str, Any]]:
    """Evaluate hard no-trade rules plus news/session gates.

    Returns (ok, reasons, events_cache, fetch_time).
    - ok=False means trade should be skipped; reasons contains human messages.
    - events_cache/fetch_time reflect updated news cache (if fetched).
    """
    # Start with existing hard filters
    ok_hard, reasons, codes = pretrade_hard_filters(mt5_ctx, cfg)

    # Session gate
    sess_ok = _allowed_session_now(mt5_ctx, cfg)
    if not sess_ok:
        reasons.append("Ngoai phien cho phep")
        codes.append("session")

    # News window gate
    events: List[Dict[str, Any]] = cache_events or []
    fetch_ts: float = float(cache_fetch_time or 0.0)
    try:
        before = int(getattr(cfg, "trade_news_block_before_min", 0) or 0)
    except Exception:
        before = 0
    try:
        after = int(getattr(cfg, "trade_news_block_after_min", 0) or 0)
    except Exception:
        after = 0
    # Respect runtime toggle: when disabled, do not block around news
    try:
        enabled = bool(getattr(cfg, "trade_news_block_enabled", True))
    except Exception:
        enabled = True
    if not enabled:
        before = 0
        after = 0

    news_hit: Optional[Dict[str, Any]] = None
    if (before > 0) or (after > 0):
        try:
            in_window, why, events, fetch_ts = news.within_news_window_cfg_cached(
                cfg,
                before,
                after,
                cache_events=events,
                cache_fetch_time=fetch_ts,
                ttl_sec=max(60, int(ttl_sec or 0)),
            )
            if in_window:
                # 'why' includes event title/currency + time
                reasons.append(f"Tin manh gan day: {why}")
                codes.append("news")
                # Try to find the matched event for meta
                try:
                    from datetime import datetime, timedelta
                    now_local = datetime.now().astimezone()
                    allowed = news.symbol_currencies(getattr(cfg, "mt5_symbol", ""))
                    for ev in events or []:
                        t = ev.get("when")
                        if not t:
                            continue
                        if allowed and ev.get("curr") and ev["curr"] not in allowed:
                            continue
                        if (t - timedelta(minutes=before)) <= now_local <= (t + timedelta(minutes=after)):
                            news_hit = ev
                            break
                except Exception:
                    news_hit = None
        except Exception:
            # Fail-open: on news check error, do not block
            pass

    ok = (len(reasons) == 0) and ok_hard and sess_ok
    meta = {"codes": codes[:], "news_hit": news_hit}
    return ok, reasons, events, fetch_ts, meta
