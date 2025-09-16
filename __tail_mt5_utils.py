        "M15": _series_from_mt5(symbol, mt5.TIMEFRAME_M15, n_m15),
        "H1": _series_from_mt5(symbol, mt5.TIMEFRAME_H1, n_h1),
    }

    # Higher timeframe levels
    daily = _hl_from(symbol, mt5.TIMEFRAME_D1, 2) or {}
    prev_day: dict[str, float] | None = None
    try:
        d2 = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_D1, 1, 1)
        if d2 is not None and len(d2) == 1:
            prev_day = {"high": float(d2[0]["high"]), "low": float(d2[0]["low"])}
    except Exception:
        prev_day = None
    weekly = _hl_from(symbol, mt5.TIMEFRAME_W1, 1) or {}
    prev_week: dict[str, float] | None = None
    try:
        w2 = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_W1, 1, 1)
        if w2 is not None and len(w2) == 1:
            prev_week = {"high": float(w2[0]["high"]), "low": float(w2[0]["low"])}
    except Exception:
        prev_week = None
    monthly = _hl_from(symbol, mt5.TIMEFRAME_MN1, 1) or {}

    # Enrich daily
    midnight_open = None
    if series["M1"]:
        for r in series["M1"]:
            if str(r["time"]).endswith("00:00:00"):
                midnight_open = r["open"]
                break
    if daily:
        hi = daily.get("high")
        lo = daily.get("low")
        eq50 = (hi + lo) / 2.0 if (hi and lo) else None
        daily["eq50"] = eq50
        daily["midnight_open"] = midnight_open

    # Sessions and VWAPs
    sessions_today = session_ranges_today(series["M1"]) if series["M1"] else {}
    vwap_day = vwap_from_rates([r for r in series["M1"] if str(r["time"])[:10] == datetime.now().strftime("%Y-%m-%d")])
    vwaps: dict[str, float | None] = {"day": vwap_day}
    for sess in ["asia", "london", "newyork_pre", "newyork_post"]:
        rng = sessions_today.get(sess, {})
        sub: list[dict] = []
        if rng and rng.get("start") and rng.get("end"):
            for r in series["M1"]:
                hh = str(r["time"])[11:16]
                if str(r["time"])[:10] == datetime.now().strftime("%Y-%m-%d") and rng["start"] <= hh < rng["end"]:
                    sub.append(r)
        vwaps[sess] = vwap_from_rates(sub) if sub else None

    # Trend refs (EMA) and ATR
    ema_block: dict[str, dict[str, float | None]] = {}
    for k in ["M1", "M5", "M15", "H1"]:
        closes = [float(r["close"]) for r in series.get(k, [])]
        ema_block[k] = {"ema50": ema(closes, 50) if closes else None, "ema200": ema(closes, 200) if closes else None}

    atr_block: dict[str, float | None] = {}
    atr_m5_now, tr_m5 = atr_series(series.get("M5", []), period=14)
    atr_block["M5"] = atr_m5_now
    atr_block["M1"] = atr_series(series.get("M1", []), period=14)[0]
    atr_block["M15"] = atr_series(series.get("M15", []), period=14)[0]
    atr_block["H1"] = atr_series(series.get("H1", []), period=14)[0]

    # Volatility regime: based on EMA M5 separation vs ATR
    vol_regime = None
    try:
        e50 = ema_block["M5"]["ema50"]
        e200 = ema_block["M5"]["ema200"]
        if e50 is not None and e200 is not None and atr_m5_now:
            vol_regime = "trending" if abs(e50 - e200) > (atr_m5_now * 0.2) else "choppy"
    except Exception:
        pass

    # Key levels around cp
    key_near = _nearby_key_levels(cp, info, daily, prev_day)

    # ADR and day position
    adr = adr_stats(symbol, n=20)
    day_open = daily.get("open") if daily else None
    prev_close = None
    try:
        d1_prev_close_arr = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_D1, 1, 1)
        if d1_prev_close_arr is not None and len(d1_prev_close_arr) == 1:
            prev_close = float(d1_prev_close_arr[0]["close"])  # type: ignore[index]
    except Exception:
        pass
    day_range = None
    day_range_pct = None
    if daily and adr and adr.get("d20"):
        if daily.get("high") and daily.get("low"):
            day_range = float(daily["high"]) - float(daily["low"])  # type: ignore[index]
            day_range_pct = (day_range / float(adr["d20"])) * 100.0  # type: ignore[index]

    pos_in_day = None
    try:
        if daily and cp:
            lo = float(daily.get("low", 0.0))
            hi = float(daily.get("high", 0.0))
            if hi > lo:
                pos_in_day = (cp - lo) / (hi - lo)
    except Exception:
        pos_in_day = None

    # Killzone detection using DST-aware VN schedule
    kills = _killzone_ranges_vn()
    now_hhmm = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).strftime("%H:%M")
    kill_active = None
    mins_to_next = None
    try:
        def _mins(t1: str, t2: str) -> int:
            h1, m1 = map(int, t1.split(":"))
            h2, m2 = map(int, t2.split(":"))
            return (h2 - h1) * 60 + (m2 - m1)

        order = ["london", "newyork_pre", "newyork_post"]
        for k in order:
            st, ed = kills[k]["start"], kills[k]["end"]
            if st <= now_hhmm < ed:
                kill_active = k
                break
        if kill_active is None:
            for k in order:
                st = kills[k]["start"]
                if now_hhmm < st:
                    mins_to_next = _mins(now_hhmm, st)
                    break
    except Exception:
        pass

    # Round levels around current price (25/50/75 pip) – optional simple set
    round_levels = []
    try:
        ppp = points_per_pip_from_info(info_obj)
        point = float(info_obj.get("point") or 0.0)
        pip = point * ppp if point else 0.0
        if cp and pip:
            pivots = [int(math.floor((cp / pip))) * pip + (s * pip / 100.0) for s in (0, 25, 50, 75)]
            seen: set[float] = set()
            for price in pivots:
                if price in seen:
                    continue
                seen.add(price)
                dist_pips = abs(cp - price) / (point * ppp)
                round_levels.append(
                    {
                        "level": f"{int(round((price % 1) / pip * 100)) if pip > 0 else 0:02d}",
                        "price": round(price, int(info_obj.get("digits") or 5)),
                        "distance_pips": round(dist_pips, 2),
                    }
                )
    except Exception:
        round_levels = []

    # Normalize spread relative to ATR M5
    spread_points = None
    if tick and info and getattr(info, "point", None):
        b = float(getattr(tick, "bid", 0.0))
        a = float(getattr(tick, "ask", 0.0))
        spread_points = (a - b) / (getattr(info, "point", 0.01) or 0.01) if (a > 0 and b > 0) else None
    atr_norm = {"spread_as_pct_of_atr_m5": None}
    if spread_points and atr_m5_now and atr_m5_now > 0 and getattr(info, "point", None):
        atr_norm["spread_as_pct_of_atr_m5"] = (spread_points / (atr_m5_now / (getattr(info, "point", 0.01) or 0.01))) * 100.0

    # Risk block from plan (optional, minimal)
    risk_model = None
    rr_projection = None
    if plan and info and ppp and (val := value_per_point(symbol, info)):
        try:
            entry = plan.get("entry")
            sl = plan.get("sl")
            tp1 = plan.get("tp1")
            tp2 = plan.get("tp2")
            if entry and sl and tp1 and tp2:
                rr1 = abs(tp1 - entry) / abs(entry - sl) if entry != sl else None
                rr2 = abs(tp2 - entry) / abs(entry - sl) if entry != sl else None
                rr_projection = {"tp1_rr": rr1, "tp2_rr": rr2}
            risk_model = {"value_per_point": val, "points_per_pip": ppp}
        except Exception:
            pass

    payload = {
        "MT5_DATA": {
            "symbol": symbol,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "broker_time": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "account": account_obj,
            "info": info_obj,
            "symbol_rules": rules_obj,
            "pip": {
                "points_per_pip": points_per_pip_from_info(info_obj),
                "value_per_point": value_per_point(symbol, info),
                "pip_value_per_lot": (
                    (value_per_point(symbol, info) or 0.0) * points_per_pip_from_info(info_obj)
                ),
            },
            "tick": tick_obj,
            "tick_stats_5m": tick_stats_5m or None,
            "tick_stats_30m": tick_stats_30m or None,
            "levels": {
                "daily": daily or None,
                "prev_day": prev_day or None,
                "weekly": weekly or None,
                "prev_week": prev_week or None,
                "monthly": monthly or None,
            },
            "day_open": daily.get("open") if daily else None,
            "prev_day_close": prev_close,
            "adr": adr or None,
            "day_range": day_range,
            "day_range_pct_of_adr20": (float(day_range_pct) if day_range_pct is not None else None),
            "position_in_day_range": (float(pos_in_day) if pos_in_day is not None else None),
            "sessions_today": sessions_today or None,
            "volatility": {"ATR": atr_block},
            "volatility_regime": vol_regime,
            "trend_refs": {"EMA": ema_block},
            "vwap": vwaps,
            "kills": kills,
            "killzone_active": kill_active,
            "mins_to_next_killzone": mins_to_next,
            "key_levels_nearby": key_near,
            "round_levels": round_levels or None,
            "atr_norm": atr_norm,
            "risk_model": risk_model,
            "rr_projection": rr_projection,
        }
    }

    if return_json:
        try:
            return json.dumps(payload, ensure_ascii=False)
        except Exception:
            return str(payload)
    return payload


__all__ = [
    "connect",
    "ensure_initialized",
    "points_per_pip_from_info",
    "pip_size_from_info",
    "value_per_point",
    "quantiles",
    "ema",
    "atr_series",
    "vwap_from_rates",
    "adr_stats",
    "session_ranges_today",
    "build_context",
]
