from __future__ import annotations
from datetime import datetime, timedelta
from typing import TYPE_CHECKING
import logging # Thêm import logging
from collections import defaultdict

logger = logging.getLogger(__name__) # Khởi tạo logger

try:
    import MetaTrader5 as mt5
except ImportError as e: # Thêm alias cho exception
    mt5 = None
    logger.warning(f"Không thể import MetaTrader5: {e}. Chức năng backtester sẽ bị hạn chế.")

if TYPE_CHECKING:
    pass

def _calculate_stats(win_loss_dict: dict) -> dict:
    """
    Hàm trợ giúp để tính tỷ lệ thắng từ một từ điển có dạng {'wins': x, 'losses': y}.

    Args:
        win_loss_dict: Từ điển chứa số lần thắng và thua.

    Returns:
        Một từ điển chứa số lần thắng, thua, tổng số và tỷ lệ thắng.
    """
    logger.debug(f"Bắt đầu hàm _calculate_stats với dict: {win_loss_dict}")
    stats = {}
    for key, value in win_loss_dict.items():
        wins = value.get("wins", 0)
        losses = value.get("losses", 0)
        total = wins + losses
        win_rate = (wins / total) if total > 0 else None
        stats[key] = {"wins": wins, "losses": losses, "total": total, "win_rate": win_rate}
    logger.debug(f"Kết thúc hàm _calculate_stats. Stats: {stats}")
    return stats

def evaluate_trade_outcomes(proposed_trades: list[dict], symbol: str) -> dict:
    """
    Phân tích kết quả của các giao dịch đã được đề xuất trước đó bằng cách sử dụng
    dữ liệu lịch sử MT5 và phân loại kết quả theo ngữ cảnh mà giao dịch được đề xuất.

    Args:
        proposed_trades: Danh sách các từ điển giao dịch được đề xuất.
        symbol: Ký hiệu giao dịch để lấy dữ liệu lịch sử.

    Returns:
        Một từ điển chứa tóm tắt kết quả và hiệu suất theo ngữ cảnh.
    """
    logger.debug(f"Bắt đầu hàm evaluate_trade_outcomes cho symbol: {symbol}, số trades: {len(proposed_trades)}")
    if not proposed_trades or mt5 is None or not mt5.is_connected():
        logger.warning("Không có trades được đề xuất hoặc MT5 không kết nối.")
        logger.debug("Kết thúc hàm evaluate_trade_outcomes (không có trades hoặc MT5 không kết nối).")
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
                logger.debug(f"Không có dữ liệu rates cho trade từ {start_time_utc} đến {end_time_utc}.")
                continue

            triggered = False
            outcome = "untriggered"

            for candle in rates:
                high, low = float(candle["high"]), float(candle["low"])
                if not triggered and ((direction == "long" and low <= entry_price) or (direction == "short" and high >= entry_price)):
                    triggered = True
                    logger.debug(f"Trade triggered tại entry {entry_price}.")
                
                if triggered:
                    if direction == "long":
                        if low <= sl_price:
                            outcome = "loss"
                            break
                        if high >= tp_price:
                            outcome = "win"
                            break
                    elif direction == "short":
                        if high >= sl_price:
                            outcome = "loss"
                            break
                        if low <= tp_price:
                            outcome = "win"
                            break
            
            if outcome in ["win", "loss"]:
                if outcome == "win":
                    total_wins += 1
                else:
                    total_losses += 1
                logger.debug(f"Trade outcome: {outcome}")

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
                logger.debug("Trade untriggered.")

        except (ValueError, KeyError) as e:
            logger.warning(f"Lỗi khi xử lý trade: {trade}. Chi tiết: {e}")
            continue

    total_evaluated = total_wins + total_losses
    overall_win_rate = (total_wins / total_evaluated) if total_evaluated > 0 else None

    final_results = {
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
    logger.debug(f"Kết thúc hàm evaluate_trade_outcomes. Kết quả: {final_results}")
    return final_results
