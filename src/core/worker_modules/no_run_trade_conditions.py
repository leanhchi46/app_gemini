from __future__ import annotations
from typing import TYPE_CHECKING, Tuple, List, Dict, Any
import logging
from datetime import datetime
from zoneinfo import ZoneInfo # Thêm import ZoneInfo
import time # Thêm import time

from src.utils import md_saver, json_saver
from src.utils.mt5_utils import _killzone_ranges_vn, info_get, pip_size_from_info, session_ranges_today
from src.services import news

logger = logging.getLogger(__name__) # Khởi tạo logger

if TYPE_CHECKING:
    from scripts.tool import TradingToolApp
    from src.config.config import RunConfig
    from src.utils.safe_data import SafeMT5Data

def check_no_run_conditions(app: "TradingToolApp", cfg: "RunConfig") -> Tuple[bool, str]:
    logger.debug("Bắt đầu hàm check_no_run_conditions.")
    """
    Kiểm tra các điều kiện NO-RUN.
    Trả về (True, "") nếu không có điều kiện NO-RUN nào được kích hoạt,
    hoặc (False, "Lý do") nếu có.
    """
    now = datetime.now()
    reasons = []

    # 1. Kiểm tra cuối tuần (Thứ Bảy hoặc Chủ Nhật)
    if cfg.no_run_weekend_enabled and now.weekday() >= 5:  # 5 là Thứ Bảy, 6 là Chủ Nhật
        reasons.append("Không chạy vào cuối tuần.")

    # 2. Kiểm tra Kill Zone
    if cfg.no_run_killzone_enabled:
        kill_zones_data = _killzone_ranges_vn(d=now, target_tz="Asia/Ho_Chi_Minh")
        is_in_kill_zone = False
        active_kill_zone = ""
        now_hhmm = now.strftime("%H:%M")

        for zone_name, zone_times in kill_zones_data.items():
            start_time_str = zone_times["start"]
            end_time_str = zone_times["end"]

            if start_time_str > end_time_str: # Kill zone kéo dài qua nửa đêm
                if now_hhmm >= start_time_str or now_hhmm < end_time_str:
                    is_in_kill_zone = True
                    active_kill_zone = zone_name
                    break
            elif start_time_str <= now_hhmm < end_time_str:
                is_in_kill_zone = True
                active_kill_zone = zone_name
                break
        
        if not is_in_kill_zone:
            reasons.append("Không chạy ngoài các Kill Zone đã định nghĩa.")
        else:
            # Nếu đang trong kill zone, chúng ta có thể ghi log hoặc cập nhật trạng thái
            # nhưng không thêm vào lý do thoát nếu các điều kiện khác cho phép
            pass

    # TODO: Thêm các điều kiện NO-RUN khác tại đây (ví dụ: ngày lễ, trạng thái thị trường đặc biệt)
    
    if reasons:
        return False, "\n- ".join(reasons)
    
    return True, f"Đang chạy trong {active_kill_zone if cfg.no_run_killzone_enabled else 'các điều kiện cho phép'}."

def evaluate_no_trade_conditions(
    safe_mt5_data: SafeMT5Data,
    cfg: "RunConfig",
    cache_events: List[Dict[str, Any]],
    cache_fetch_time: float,
    ttl_sec: int
) -> Tuple[bool, List[str], List[Dict[str, Any]], float, int]:
    logger.debug("Bắt đầu hàm evaluate_no_trade_conditions.")
    """
    Đánh giá các điều kiện NO-TRADE.
    Trả về (True, [], ...) nếu không có điều kiện NO-TRADE nào được kích hoạt,
    hoặc (False, ["Lý do"], ...) nếu có.
    """
    # TODO: Triển khai logic kiểm tra NO-TRADE thực tế tại đây
    # Ví dụ: Kiểm tra tin tức, spread, v.v.

    reasons = []
    current_events = cache_events
    current_fetch_time = cache_fetch_time

    # Lấy thông tin cần thiết từ safe_mt5_data hoặc mt5_dict
    mt5_raw_data = safe_mt5_data.raw if safe_mt5_data and safe_mt5_data.raw else {}
    symbol_info = mt5_raw_data.get("info", {})
    tick_data = mt5_raw_data.get("tick", {})
    current_price = float(tick_data.get("bid") or tick_data.get("last") or 0.0)
    
    # Cập nhật cache tin tức nếu cần
    if current_events is None or (time.time() - current_fetch_time) > ttl_sec:
        try:
            # app._refresh_news_cache sẽ được gọi ở context_coordinator,
            # ở đây ta chỉ sử dụng dữ liệu đã được cache
            # Nếu cần fetch lại, logic này sẽ phức tạp hơn và có thể cần refactor
            pass 
        except Exception as e:
            logger.warning(f"Lỗi khi làm mới cache tin tức trong NO-TRADE: {e}")

    # 1. Kiểm tra tin tức quan trọng
    if cfg.trade_news_block_enabled:
        is_in_window, news_reason = news.is_within_news_window(
            events=current_events,
            symbol=cfg.mt5_symbol,
            minutes_before=cfg.trade_news_block_before_min,
            minutes_after=cfg.trade_news_block_after_min,
        )
        if is_in_window:
            reasons.append(f"Tin tức quan trọng: {news_reason}")

    # 2. Kiểm tra Spread cao
    if cfg.nt_spread_factor > 0:
        current_spread_points = info_get(symbol_info, "spread_current", 0)
        point_size = info_get(symbol_info, "point", 0.0)
        if point_size > 0:
            current_spread_pips = current_spread_points * point_size / pip_size_from_info(symbol_info)
            if current_spread_pips > cfg.nt_spread_factor:
                reasons.append(f"Spread quá cao ({current_spread_pips:.2f} pips > {cfg.nt_spread_factor:.2f} pips).")

    # 3. Kiểm tra Biến động thấp/cao bất thường (sử dụng ATR M5)
    if cfg.nt_min_atr_m5_pips > 0:
        atr_m5 = mt5_raw_data.get("volatility", {}).get("ATR", {}).get("M5")
        if atr_m5 is not None:
            point_size = info_get(symbol_info, "point", 0.0)
            if point_size > 0:
                atr_m5_pips = atr_m5 / pip_size_from_info(symbol_info)
                if atr_m5_pips < cfg.nt_min_atr_m5_pips:
                    reasons.append(f"Biến động thị trường quá thấp (ATR M5 {atr_m5_pips:.2f} pips < {cfg.nt_min_atr_m5_pips:.2f} pips).")
        else:
            reasons.append("Không có dữ liệu ATR M5 để kiểm tra biến động.")

    # 4. Kiểm tra Giờ giao dịch cụ thể (phiên)
    now_vn = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh"))
    sessions_today = session_ranges_today(None) # Lấy phiên hiện tại
    current_hhmm = now_vn.strftime("%H:%M")
    
    is_allowed_session = False
    if cfg.nt_allow_session_asia:
        asia_session = sessions_today.get("asia", {})
        if asia_session and asia_session["start"] <= current_hhmm < asia_session["end"]:
            is_allowed_session = True
    if cfg.nt_allow_session_london:
        london_session = sessions_today.get("london", {})
        if london_session and london_session["start"] <= current_hhmm < london_session["end"]:
            is_allowed_session = True
    if cfg.nt_allow_session_ny:
        ny_am_session = sessions_today.get("newyork_am", {})
        ny_pm_session = sessions_today.get("newyork_pm", {})
        if (ny_am_session and ny_am_session["start"] <= current_hhmm < ny_am_session["end"]) or \
           (ny_pm_session and (ny_pm_session["start"] <= current_hhmm or current_hhmm < ny_pm_session["end"])): # Xử lý qua nửa đêm
            is_allowed_session = True
    
    if not (cfg.nt_allow_session_asia or cfg.nt_allow_session_london or cfg.nt_allow_session_ny):
        # Nếu không có phiên nào được phép, mặc định cho phép để không chặn hoàn toàn
        is_allowed_session = True 
    
    if not is_allowed_session:
        reasons.append("Không nằm trong phiên giao dịch được phép.")

    # 5. Kiểm tra Khoảng cách đến các mức quan trọng (Key Levels)
    if cfg.nt_min_dist_keylvl_pips > 0 and current_price > 0:
        key_levels_nearby = mt5_raw_data.get("key_levels_nearby", [])
        for level in key_levels_nearby:
            dist_pips = level.get("distance_pips")
            if dist_pips is not None and dist_pips < cfg.nt_min_dist_keylvl_pips:
                reasons.append(f"Giá quá gần mức key level {level.get('name')} ({dist_pips:.2f} pips < {cfg.nt_min_dist_keylvl_pips:.2f} pips).")

    # TODO: Thêm các điều kiện NO-TRADE khác tại đây
    
    if reasons:
        return False, reasons, current_events, current_fetch_time, ttl_sec
    
    return True, [], current_events, current_fetch_time, ttl_sec

def check_all_preconditions(
    app: "TradingToolApp",
    cfg: "RunConfig",
    safe_mt5_data: SafeMT5Data,
    mt5_dict: Dict,
    context_block: str,
    mt5_json_full: str
) -> Tuple[bool, str]:
    logger.debug("Bắt đầu hàm check_all_preconditions.")
    """
    Kiểm tra tổng hợp các điều kiện NO-RUN và NO-TRADE.
    Trả về (True, "") nếu tất cả các điều kiện đều thỏa,
    hoặc (False, "Lý do") nếu có điều kiện không thỏa.
    """
    # 1. Kiểm tra NO-RUN
    should_run, no_run_reason = check_no_run_conditions(app, cfg) # Truyền cfg vào hàm kiểm tra NO-RUN
    if not should_run:
        app.ui_status(no_run_reason)
        app._log_trade_decision({
            "stage": "no-run-skip",
            "t": app._tnow_str(), # Sử dụng hàm _tnow_str từ app
            "reason": no_run_reason
        }, folder_override=(app.mt5_symbol_var.get().strip() or None))
        logger.info(f"Điều kiện No-Run được kích hoạt: {no_run_reason}, thoát sớm.")
        return False, no_run_reason

    # 2. Kiểm tra NO-TRADE
    if cfg.nt_enabled and mt5_dict:
        ok_nt, reasons_nt, _, _, _ = evaluate_no_trade_conditions(
            safe_mt5_data, cfg, cache_events=app.ff_cache_events_local,
            cache_fetch_time=app.ff_cache_fetch_time, ttl_sec=int(getattr(cfg, 'news_cache_ttl_sec', 300) or 300)
        )
        app.last_no_trade_ok = bool(ok_nt)
        app.last_no_trade_reasons = list(reasons_nt or [])
        if not ok_nt:
            app._log_trade_decision({
                "stage": "no-trade",
                "t": app._tnow_str(), # Sử dụng hàm _tnow_str từ app
                "reasons": reasons_nt
            }, folder_override=(app.mt5_symbol_var.get().strip() or None))
            
            note = "NO-TRADE: Điều kiện giao dịch không thỏa.\n- " + "\n- ".join(reasons_nt)
            if context_block:
                note += f"\n\n{context_block}"
            if mt5_json_full:
                note += f"\n\n[PHỤ LỤC_MT5_JSON]\n{mt5_json_full}"
            
            app.combined_report_text = note
            app.ui_status(note) # Cập nhật UI status
            # ui_utils.ui_detail_replace(app, note) # Sẽ được gọi sau trong main_worker
            
            # Lưu báo cáo Markdown và JSON trực tiếp
            md_saver.save_md_report(app, note, cfg)
            json_saver.save_json_report(app, note, cfg, [], context_block) # names=[] vì không có ảnh
            
            # ui_utils.ui_refresh_history_list(app) # Sẽ được gọi sau trong main_worker
            
            logger.info(f"Điều kiện No-Trade được kích hoạt: {', '.join(reasons_nt)}, thoát sớm.")
            return False, note
    
    return True, ""
