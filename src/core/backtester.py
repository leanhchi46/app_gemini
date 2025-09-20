from __future__ import annotations
from datetime import datetime, timezone, timedelta
from typing import TYPE_CHECKING
from collections import defaultdict

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None

if TYPE_CHECKING:
    from scripts.tool import TradingToolApp

def _calculate_stats(win_loss_dict):
    """Helper to calculate win rate from a dict of {'wins': x, 'losses': y}."""
    stats = {}
    for key, value in win_loss_dict.items():
        wins = value.get("wins", 0)
        losses = value.get("losses", 0)
        total = wins + losses
        win_rate = (wins / total) if total > 0 else None
        stats[key] = {"wins": wins, "losses": losses, "total": total, "win_rate": win_rate}
    return stats

def evaluate_trade_outcomes(proposed_trades: list[dict], symbol: str) -> dict:
    """
    Analyzes the outcome of previously proposed trades using historical MT5 data,
    and categorizes the results by the context in which the trade was proposed.
    """
    if not proposed_trades or mt5 is None or not mt5.is_connected():
        return {"summary": {"total_proposed": len(proposed_trades), "wins": 0, "losses": 0, "untriggered": 0, "win_rate": None}}

    stats = {
        "by_session": defaultdict(lambda: defaultdict(int)),
        "by_trend_checklist": defaultdict(lambda: defaultdict(int)),
        "by_volatility_regime": defaultdict(lambda: defaultdict(int)),
        "by_trend_regime": defaultdict(lambda: defaultdict(int)),
    }
    
    untriggered = 0
    total_wins = 0
    total_losses = 0

    proposed_trades.sort(key=lambda x: x.get("timestamp_utc", ""))

    for trade in proposed_trades:
        try:
            setup = trade["setup"]
            entry_price = float(setup["entry"])
            sl_price = float(setup["sl"])
            tp_price = float(setup["tp1"])
            direction = setup["direction"]
            
            start_time_utc = datetime.fromisoformat(trade["timestamp_utc"])
            end_time_utc = start_time_utc + timedelta(hours=24)

            rates = mt5.copy_rates_range(symbol, mt5.TIMEFRAME_M1, start_time_utc, end_time_utc)

            if rates is None or len(rates) == 0:
                continue

            triggered = False
            outcome = "untriggered"

            for candle in rates:
                high, low = float(candle["high"]), float(candle["low"])
                if not triggered and ((direction == "long" and low <= entry_price) or (direction == "short" and high >= entry_price)):
                    triggered = True
                
                if triggered:
                    if direction == "long":
                        if low <= sl_price: outcome = "loss"; break
                        if high >= tp_price: outcome = "win"; break
                    elif direction == "short":
                        if high >= sl_price: outcome = "loss"; break
                        if low <= tp_price: outcome = "win"; break
            
            if outcome in ["win", "loss"]:
                if outcome == "win": total_wins += 1
                else: total_losses += 1

                ctx = trade.get("context_snapshot", {})
                if ctx.get("session"):
                    stats["by_session"][ctx["session"]][outcome + "s"] += 1
                if ctx.get("trend_checklist"):
                    stats["by_trend_checklist"][ctx["trend_checklist"]][outcome + "s"] += 1
                if ctx.get("volatility_regime"):
                    stats["by_volatility_regime"][ctx["volatility_regime"]][outcome + "s"] += 1
                if ctx.get("trend_regime"):
                    stats["by_trend_regime"][ctx["trend_regime"]][outcome + "s"] += 1
            else:
                untriggered += 1

        except (ValueError, KeyError):
            continue

    total_evaluated = total_wins + total_losses
    overall_win_rate = (total_wins / total_evaluated) if total_evaluated > 0 else None

    return {
        "summary": {
            "total_proposed": len(proposed_trades),
            "total_evaluated": total_evaluated,
            "wins": total_wins,
            "losses": total_losses,
            "untriggered": untriggered,
            "win_rate": overall_win_rate,
        },
        "performance_by_context": {
            "session": _calculate_stats(stats["by_session"]),
            "checklist_trend": _calculate_stats(stats["by_trend_checklist"]),
            "volatility_regime": _calculate_stats(stats["by_volatility_regime"]),
            "trend_regime": _calculate_stats(stats["by_trend_regime"]),
        }
    }
