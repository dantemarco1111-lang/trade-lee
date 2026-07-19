"""
Trade Lee - drill generator.

Downloads 5-minute intraday data across four market packs (stocks/indices,
futures, forex, crypto), scans each for consolidation-then-breakout
patterns, labels each as a real breakout or a fakeout, builds a balanced
deck per pack, computes per-drill plain-language context notes (market-
appropriate — no volume language on forex, no jargon abbreviations), and
saves one JSON file per pack for the game (lightweight-charts renders the
candles client-side).

Run: python generate_drills.py
"""

import json
import math
import os
import random
import shutil

import numpy as np
import pandas as pd
import yfinance as yf

DRILLS_DIR = "drills"
RANDOM_SEED = 42
MAX_DECK_SIZE = 60
MIN_HEALTHY_DECK_SIZE = 30
MIN_SHIPPABLE_DECK_SIZE = 10  # below this, skip the pack entirely rather than ship a token deck

CONSOLIDATION_BARS = 9      # 45 minutes of 5-min bars
TIGHTNESS_PERCENTILE = 35   # window must be tighter than this pct of the period's own 45-min ranges
COOLDOWN_BARS = 12          # after a detected breakout, skip 60 min before scanning again
EXTENSION_MULTIPLE = 1.0    # "real breakout" = price extends >= 1x range height
PRIOR_PERIOD_PROXIMITY_PCT = 0.0025  # 0.25%
MIN_CONTEXT_BARS = 60       # chart always shows at least this many bars before the decision point

# Futures session-open effects worth calling out in context lines.
EQUITY_OPEN_ET = "09:30"
METALS_ENERGY_PIT_OPEN_ET = "08:20"
SESSION_OPEN_PROXIMITY_MIN = 15  # minutes


def pip_size(symbol):
    return 0.01 if "JPY" in symbol else 0.0001


# ============================================================
# MARKET PACK CONFIG
# ============================================================
# sessions: list of (session_key, start_ET, end_ET) — "start > end" wraps midnight.
# outcome_window_min: how many minutes forward to evaluate real-vs-fake.
MARKET_PACKS = {
    "stocks": {
        "label": "Stocks & Indices",
        "tickers": ["QQQ", "SPY", "IWM", "DIA"],
        "has_volume": True,
        "sessions": [("open", "09:30", "11:00"), ("midday", "11:00", "14:00"), ("power_hour", "14:00", "16:00")],
        "outcome_window_min": 60,
        "output_file": "drills.json",  # unchanged filename — keeps the live game working as-is
    },
    "futures": {
        "label": "Futures",
        "tickers": ["NQ=F", "ES=F", "GC=F", "CL=F", "SI=F"],
        "has_volume": True,
        "sessions": [("open", "09:30", "11:00"), ("midday", "11:00", "14:00"), ("power_hour", "14:00", "16:00"),
                     ("overnight", "18:00", "09:30")],
        "outcome_window_min": 60,
        "output_file": "drills-futures.json",
    },
    "forex": {
        "label": "Forex",
        "tickers": ["EURUSD=X", "GBPUSD=X", "USDJPY=X", "AUDUSD=X", "USDCAD=X"],
        "has_volume": False,
        "sessions": [("asian", "19:00", "03:00"), ("london", "03:00", "08:00"), ("new_york", "08:00", "17:00")],
        "outcome_window_min": 90,
        "output_file": "drills-forex.json",
    },
    "crypto": {
        "label": "Crypto",
        "tickers": ["BTC-USD", "ETH-USD", "SOL-USD"],
        "has_volume": True,
        "sessions": [("us_hours", "09:30", "16:00"), ("overnight", "16:00", "09:30")],
        "outcome_window_min": 60,
        "output_file": "drills-crypto.json",
    },
}


def download_data(symbol, interval="5m"):
    print(f"  Downloading {interval} data for {symbol}...")
    df = yf.download(
        symbol,
        period="60d",
        interval=interval,
        prepost=False,
        auto_adjust=False,
        progress=False,
    )
    if df.empty:
        print(f"    SKIP {symbol}: no data returned.")
        return None

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    df.index = df.index.tz_convert("America/New_York")

    # True Range / ATR — used as the "Activity" proxy for markets with no volume (forex).
    prev_close = df["Close"].shift(1)
    true_range = pd.concat(
        [df["High"] - df["Low"], (df["High"] - prev_close).abs(), (df["Low"] - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    df["ATR"] = true_range.rolling(14, min_periods=1).mean()

    return df


def session_mask(index, start_str, end_str):
    times = index.strftime("%H:%M")
    if start_str <= end_str:
        return (times >= start_str) & (times < end_str)
    return (times >= start_str) | (times < end_str)  # wraps midnight


def split_into_session_instances(df, start_str, end_str):
    """Returns [(label, session_df), ...] — one per calendar occurrence of the session window."""
    mask = session_mask(df.index, start_str, end_str)
    sub = df[mask]
    if sub.empty:
        return []
    sub = sub.copy()
    if start_str <= end_str:
        sub["_session_day"] = sub.index.date
    else:
        times = sub.index.strftime("%H:%M")
        is_tail = times < end_str
        sub["_session_day"] = np.where(is_tail, (sub.index - pd.Timedelta(days=1)).date, sub.index.date)

    instances = []
    for day, day_df in sub.groupby("_session_day"):
        instances.append((str(day), day_df.drop(columns="_session_day")))
    return instances


def compute_outcome(direction, range_high, range_low, range_height, breakout_idx, period_df, j, outcome_window_bars):
    n = len(period_df)
    highs = period_df["High"].values
    lows = period_df["Low"].values
    closes = period_df["Close"].values
    times = period_df.index

    if direction == "long":
        target_level = range_high + EXTENSION_MULTIPLE * range_height
    else:
        target_level = range_low - EXTENSION_MULTIPLE * range_height

    forward_end = min(j + outcome_window_bars, n - 1)
    for k in range(j + 1, forward_end + 1):
        bar_index = k - j - 1
        if direction == "long":
            if closes[k] < range_high:
                minutes = int((times[k] - breakout_idx).total_seconds() // 60)
                return "fake", None, minutes, bar_index, None
            if highs[k] >= target_level:
                multiple = round((highs[k] - range_high) / range_height, 2)
                return "real", multiple, None, bar_index, round(float(highs[k]), 6)
        else:
            if closes[k] > range_low:
                minutes = int((times[k] - breakout_idx).total_seconds() // 60)
                return "fake", None, minutes, bar_index, None
            if lows[k] <= target_level:
                multiple = round((range_low - lows[k]) / range_height, 2)
                return "real", multiple, None, bar_index, round(float(lows[k]), 6)

    return "fake", None, None, None, None  # fizzled: never resolved either way within the window


def find_breakouts_in_pack(df, symbol, pack_key, pack_cfg, outcome_window_bars):
    breakouts = []

    for session_key, start_str, end_str in pack_cfg["sessions"]:
        instances = split_into_session_instances(df, start_str, end_str)

        for inst_i, (label, period_df) in enumerate(instances):
            n = len(period_df)
            if n < CONSOLIDATION_BARS + 1:
                continue

            highs = period_df["High"].values
            lows = period_df["Low"].values
            closes = period_df["Close"].values
            activity = period_df["Volume"].values if pack_cfg["has_volume"] else period_df["ATR"].values
            times = period_df.index

            rolling_range = np.full(n, np.nan)
            for i in range(CONSOLIDATION_BARS - 1, n):
                window_hi = highs[i - CONSOLIDATION_BARS + 1: i + 1].max()
                window_lo = lows[i - CONSOLIDATION_BARS + 1: i + 1].min()
                rolling_range[i] = window_hi - window_lo

            valid_ranges = rolling_range[~np.isnan(rolling_range)]
            if len(valid_ranges) == 0:
                continue
            tight_threshold = np.percentile(valid_ranges, TIGHTNESS_PERCENTILE)

            prev_period_stats = None
            if inst_i > 0:
                _, prev_df = instances[inst_i - 1]
                if not prev_df.empty:
                    prev_period_stats = {"high": prev_df["High"].max(), "low": prev_df["Low"].min()}

            j = CONSOLIDATION_BARS
            while j < n:
                i = j - 1
                if np.isnan(rolling_range[i]) or rolling_range[i] > tight_threshold:
                    j += 1
                    continue

                range_high = highs[i - CONSOLIDATION_BARS + 1: i + 1].max()
                range_low = lows[i - CONSOLIDATION_BARS + 1: i + 1].min()
                range_height = range_high - range_low
                if range_height <= 0:
                    j += 1
                    continue

                if closes[j] > range_high:
                    direction = "long"
                elif closes[j] < range_low:
                    direction = "short"
                else:
                    j += 1
                    continue

                breakout_idx = times[j]
                outcome, extension_multiple, reversal_minutes, resolution_bar_index, resolved_price = compute_outcome(
                    direction, range_high, range_low, range_height, breakout_idx, period_df, j, outcome_window_bars
                )

                # Real consolidation length: walk backward from the fixed 9-bar tight
                # window as long as price kept staying inside [range_low, range_high] —
                # often longer than the 9-bar detection window itself.
                bar_minutes = (times[1] - times[0]).total_seconds() / 60 if n > 1 else 5
                consol_start = i - CONSOLIDATION_BARS + 1
                while consol_start > 0 and lows[consol_start - 1] >= range_low and highs[consol_start - 1] <= range_high:
                    consol_start -= 1
                consolidation_minutes = int(round((i - consol_start + 1) * bar_minutes))

                consol_avg_activity = activity[i - CONSOLIDATION_BARS + 1: i + 1].mean()
                breakout_activity = activity[j]
                breakout_price = round(float(closes[j]), 6)

                playout_end = min(j + 1 + outcome_window_bars, n)
                vwap_end = playout_end
                typical_price = (
                    period_df["High"].iloc[:vwap_end] + period_df["Low"].iloc[:vwap_end] + period_df["Close"].iloc[:vwap_end]
                ) / 3
                if pack_cfg["has_volume"]:
                    weight = period_df["Volume"].iloc[:vwap_end]
                    denom = weight.cumsum()
                    vwap_series = (typical_price * weight).cumsum() / denom.replace(0, np.nan)
                else:
                    vwap_series = typical_price.expanding().mean()  # no real volume on FX — a plain average price line

                # Chart context always shows >= MIN_CONTEXT_BARS candles before the decision
                # point, pulled from the full continuous series (may reach back before the
                # session boundary) — the outcome/VWAP logic above stays session-scoped, only
                # the visual lookback is extended.
                full_loc = df.index.get_loc(breakout_idx)
                context_start = max(0, full_loc - MIN_CONTEXT_BARS + 1)
                chart_df = df.iloc[context_start: full_loc + 1]
                playout_df = period_df.iloc[j + 1: playout_end]

                breakouts.append({
                    "symbol": symbol, "pack": pack_key, "session": session_key, "period_label": label,
                    "direction": direction, "range_high": range_high, "range_low": range_low,
                    "range_height": range_height, "breakout_ts": breakout_idx, "breakout_price": breakout_price,
                    "outcome": outcome, "extension_multiple": extension_multiple, "reversal_minutes": reversal_minutes,
                    "resolution_bar_index": resolution_bar_index, "resolved_price": resolved_price,
                    "consol_avg_activity": consol_avg_activity, "breakout_activity": breakout_activity,
                    "consolidation_minutes": consolidation_minutes,
                    "vwap_series": vwap_series, "chart_df": chart_df, "playout_df": playout_df,
                    "prior_period": prev_period_stats,
                })

                j += COOLDOWN_BARS

    return breakouts


def compute_context(b, pack_cfg):
    """Human-readable, jargon-free context notes; returns (primary_line, all_notes)."""
    notes = []
    direction = b["direction"]
    entry = b["chart_df"]["Close"].iloc[-1]
    symbol = b["symbol"]
    pack_key = b["pack"]

    prior = b["prior_period"]
    period_word = "session" if pack_key in ("forex", "futures") and b["session"] != "regular" else "yesterday's"
    if prior is not None:
        if direction == "long" and prior["high"] > 0:
            if abs(entry - prior["high"]) / prior["high"] < PRIOR_PERIOD_PROXIMITY_PCT:
                notes.append(("priorday", f"Broke out into {period_word} high — heavy sellers there" if period_word == "yesterday's"
                              else "Broke out into the prior session's high — heavy sellers there"))
        elif direction == "short" and prior["low"] > 0:
            if abs(entry - prior["low"]) / prior["low"] < PRIOR_PERIOD_PROXIMITY_PCT:
                notes.append(("priorday", f"Broke out into {period_word} low — heavy buyers there" if period_word == "yesterday's"
                              else "Broke out into the prior session's low — heavy buyers there"))

    avg_act = b["consol_avg_activity"]
    breakout_act = b["breakout_activity"]
    if avg_act and not math.isnan(avg_act) and avg_act > 0 and breakout_act and breakout_act > 0:
        ratio = breakout_act / avg_act
        if pack_cfg["has_volume"]:
            notes.append(("volume", f"Breakout volume {ratio:.1f}x the consolidation average"))
        else:
            notes.append(("activity", f"Breakout activity {ratio:.1f}x the consolidation average — no volume data on forex, so this tracks price movement instead"))

    if pack_cfg["has_volume"]:
        vwap_series = b["vwap_series"]
        if not vwap_series.empty and not pd.isna(vwap_series.iloc[-1]):
            vwap_at_breakout = vwap_series.iloc[-1]
            position = "above" if entry > vwap_at_breakout else "below"
            notes.append(("vwap", f"Price was {position} the day's average price (VWAP) at the breakout"))
    elif pack_key == "forex":
        range_pips = round(b["range_height"] / pip_size(symbol))
        notes.append(("pips", f"The range was about {range_pips} pips wide before the break"))

    if pack_key == "futures":
        breakout_hour_min = b["breakout_ts"].strftime("%H:%M")
        if symbol in ("NQ=F", "ES=F") and _within_minutes(breakout_hour_min, EQUITY_OPEN_ET, SESSION_OPEN_PROXIMITY_MIN):
            notes.append(("session_open", "This broke right at the 9:30 ET stock market open — a classic volatility trigger for index futures"))
        elif symbol in ("GC=F", "SI=F", "CL=F") and _within_minutes(breakout_hour_min, METALS_ENERGY_PIT_OPEN_ET, SESSION_OPEN_PROXIMITY_MIN):
            notes.append(("session_open", "This broke right around the 8:20 ET metals/energy pit open — activity often picks up here"))

    if pack_key == "forex":
        session_names = {"asian": "the Asian session", "london": "the London session", "new_york": "the New York session"}
        notes.append(("session", f"This range built during {session_names.get(b['session'], b['session'])}"))

    if pack_key == "crypto" and b["breakout_ts"].weekday() >= 5:
        notes.append(("weekend", "This happened over the weekend — liquidity is thinner and moves can be less reliable"))

    priority = {"priorday": 0, "volume": 1, "activity": 1, "session_open": 1, "vwap": 2, "pips": 2, "session": 3, "weekend": 3}
    notes.sort(key=lambda n: priority.get(n[0], 99))

    primary = notes[0][1] if notes else ""
    return primary, [n[1] for n in notes]


def _within_minutes(hhmm_a, hhmm_b, max_minutes):
    ha, ma = (int(x) for x in hhmm_a.split(":"))
    hb, mb = (int(x) for x in hhmm_b.split(":"))
    return abs((ha * 60 + ma) - (hb * 60 + mb)) <= max_minutes


# ============================================================
# LONG / SHORT / WAIT scenario detection (Phase 2)
# ============================================================
LSW_REFERENCE_BARS = 9
LSW_RESOLUTION_MULTIPLE = 0.75   # correct direction = price moves >= this x the reference range
LSW_VWAP_PROXIMITY_PCT = 0.0015
LSW_COOLDOWN_BARS = 10


def find_lsw_scenarios_in_pack(df, symbol, pack_key, pack_cfg, outcome_window_bars):
    scenarios = []
    for session_key, start_str, end_str in pack_cfg["sessions"]:
        instances = split_into_session_instances(df, start_str, end_str)
        for inst_i, (label, period_df) in enumerate(instances):
            n = len(period_df)
            if n < LSW_REFERENCE_BARS + 5:
                continue
            highs = period_df["High"].values
            lows = period_df["Low"].values
            closes = period_df["Close"].values
            times = period_df.index

            prior_period_stats = None
            if inst_i > 0:
                _, prev_df = instances[inst_i - 1]
                if not prev_df.empty:
                    prior_period_stats = {"high": prev_df["High"].max(), "low": prev_df["Low"].min()}

            # Running VWAP for this period (session-scoped, same convention as compute_context).
            typical_price = (period_df["High"] + period_df["Low"] + period_df["Close"]) / 3
            if pack_cfg["has_volume"]:
                weight = period_df["Volume"]
                vwap_running = (typical_price * weight).cumsum() / weight.cumsum().replace(0, np.nan)
            else:
                vwap_running = typical_price.expanding().mean()
            vwap_vals = vwap_running.values

            j = LSW_REFERENCE_BARS
            while j < n - 1:
                window_hi = highs[j - LSW_REFERENCE_BARS + 1: j + 1].max()
                window_lo = lows[j - LSW_REFERENCE_BARS + 1: j + 1].min()
                ref_range = window_hi - window_lo
                if ref_range <= 0:
                    j += 1
                    continue

                sub_type = None
                # 1) VWAP pullback: close is now near VWAP after being clearly away from it a few bars ago.
                if not math.isnan(vwap_vals[j]) and not math.isnan(vwap_vals[j - 3]):
                    now_dist = abs(closes[j] - vwap_vals[j]) / closes[j]
                    was_dist = abs(closes[j - 3] - vwap_vals[j - 3]) / closes[j - 3]
                    if now_dist < LSW_VWAP_PROXIMITY_PCT and was_dist > now_dist * 2.5:
                        sub_type = "vwap_pullback"
                # 2) Prior-period level test.
                if sub_type is None and prior_period_stats is not None:
                    if prior_period_stats["high"] > 0 and abs(closes[j] - prior_period_stats["high"]) / closes[j] < PRIOR_PERIOD_PROXIMITY_PCT:
                        sub_type = "prior_period_test"
                    elif prior_period_stats["low"] > 0 and abs(closes[j] - prior_period_stats["low"]) / closes[j] < PRIOR_PERIOD_PROXIMITY_PCT:
                        sub_type = "prior_period_test"
                # 3) Mid-range chop: sitting near the midpoint of the recent range.
                if sub_type is None:
                    range_mid = (window_hi + window_lo) / 2
                    if abs(closes[j] - range_mid) / ref_range < 0.25:
                        sub_type = "mid_range_chop"

                if sub_type is None:
                    j += 1
                    continue

                decision_idx = times[j]
                entry_price = closes[j]
                target_up = entry_price + LSW_RESOLUTION_MULTIPLE * ref_range
                target_down = entry_price - LSW_RESOLUTION_MULTIPLE * ref_range
                forward_end = min(j + outcome_window_bars, n - 1)
                correct_answer, resolution_bar_index = "wait", None
                for k in range(j + 1, forward_end + 1):
                    if highs[k] >= target_up:
                        correct_answer, resolution_bar_index = "long", k - j - 1
                        break
                    if lows[k] <= target_down:
                        correct_answer, resolution_bar_index = "short", k - j - 1
                        break

                playout_end = min(j + 1 + outcome_window_bars, n)
                full_loc = df.index.get_loc(decision_idx)
                context_start = max(0, full_loc - MIN_CONTEXT_BARS + 1)
                chart_df = df.iloc[context_start: full_loc + 1]
                playout_df = period_df.iloc[j + 1: playout_end]
                vwap_series = vwap_running.iloc[: j + 1 + outcome_window_bars]

                scenarios.append({
                    "symbol": symbol, "pack": pack_key, "session": session_key, "period_label": label,
                    "sub_type": sub_type, "correct_answer": correct_answer,
                    "resolution_bar_index": resolution_bar_index,
                    "decision_ts": decision_idx, "entry_price": round(float(entry_price), 6),
                    "range_high": window_hi, "range_low": window_lo,
                    "chart_df": chart_df, "playout_df": playout_df, "vwap_series": vwap_series,
                })

                j += LSW_COOLDOWN_BARS
    return scenarios


def compute_lsw_context(s, pack_cfg):
    notes = []
    sub_type = s["sub_type"]
    if sub_type == "vwap_pullback":
        notes.append("Price pulled back to the day's average price (VWAP) after being away from it")
    elif sub_type == "prior_period_test":
        notes.append("Price is testing a prior session's high or low")
    else:
        notes.append("Price is sitting mid-range — no clear edge either way yet")
    notes.append(f"Reference range for this call: {round(s['range_high'] - s['range_low'], 4)}")
    notes.append("Correct = price moves at least 0.75x that range in one direction; otherwise WAIT is correct")
    return notes[0], notes


def build_lsw_pack(pack_key, pack_cfg, timeframe, interval, output_file):
    print(f"\n=== LSW PACK: {pack_cfg['label']} ({timeframe}) ===")
    outcome_window_bars = pack_cfg["outcome_window_min"] // 5
    all_scenarios = []
    for symbol in pack_cfg["tickers"]:
        df = download_data(symbol, interval)
        if df is None:
            continue
        found = find_lsw_scenarios_in_pack(df, symbol, pack_key, pack_cfg, outcome_window_bars)
        all_scenarios.extend(found)
        longs = sum(1 for s in found if s["correct_answer"] == "long")
        shorts = sum(1 for s in found if s["correct_answer"] == "short")
        waits = sum(1 for s in found if s["correct_answer"] == "wait")
        print(f"    {symbol}: {len(found)} scenarios -> {longs} long / {shorts} short / {waits} wait")

    long_pool = [s for s in all_scenarios if s["correct_answer"] == "long"]
    short_pool = [s for s in all_scenarios if s["correct_answer"] == "short"]
    wait_pool = [s for s in all_scenarios if s["correct_answer"] == "wait"]

    random.seed(RANDOM_SEED)
    target_wait = round(MAX_DECK_SIZE * 0.30)
    target_dir = (MAX_DECK_SIZE - target_wait) // 2
    n_wait = min(len(wait_pool), target_wait)
    n_long = min(len(long_pool), target_dir)
    n_short = min(len(short_pool), target_dir)
    deck = (
        random.sample(wait_pool, n_wait) + random.sample(long_pool, n_long) + random.sample(short_pool, n_short)
    )
    random.shuffle(deck)

    print(f"  Pools: long={len(long_pool)} short={len(short_pool)} wait={len(wait_pool)}  Deck: {len(deck)} "
          f"(long={n_long}, short={n_short}, wait={n_wait})")

    if len(deck) < MIN_SHIPPABLE_DECK_SIZE:
        print(f"  SKIPPING LSW pack '{pack_key}': deck size {len(deck)} below shippable floor.")
        return None

    records = []
    for i, s in enumerate(deck, start=1):
        candles, playout_candles, vwap = build_candle_payload(s, pack_cfg["has_volume"])
        context, context_all = compute_lsw_context(s, pack_cfg)
        records.append({
            "id": f"lsw_{i:03d}",
            "ticker": s["symbol"],
            "market": pack_key,
            "drill_style": "long_short_wait",
            "session": s["session"],
            "timeframe": timeframe,
            "has_volume": pack_cfg["has_volume"],
            "date": s["period_label"],
            "sub_type": s["sub_type"],
            "correct_answer": s["correct_answer"],
            "resolution_bar_index": s["resolution_bar_index"],
            "entry_price": s["entry_price"],
            "context": context,
            "context_all": context_all,
            "range_high": round(float(s["range_high"]), 6),
            "range_low": round(float(s["range_low"]), 6),
            "breakout_time": int(s["decision_ts"].timestamp()),
            "candles": candles,
            "playout_candles": playout_candles,
            "vwap": vwap,
        })

    out_path = os.path.join(DRILLS_DIR, output_file)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)

    total = len(records)
    longs = sum(1 for r in records if r["correct_answer"] == "long")
    shorts = sum(1 for r in records if r["correct_answer"] == "short")
    waits = sum(1 for r in records if r["correct_answer"] == "wait")
    print(f"  --- LSW deck composition ({out_path}) ---")
    print(f"  Total: {total} (long={longs}, short={shorts}, wait={waits} -- wait pct={100*waits/total:.0f}%)")
    for symbol in pack_cfg["tickers"]:
        t = [r for r in records if r["ticker"] == symbol]
        if t:
            print(f"    {symbol}: {len(t)} scenarios")
    return records


# ============================================================
# PHASE 3 STRATEGY PACKS — shared helpers
# ============================================================
# See DETECTION.md for the plain-language version of every rule below.
PHASE3_COOLDOWN_BARS = 10
SWING_PIVOT_WINDOW = 5

_phase3_download_cache = {}


def download_data_cached(symbol, interval="5m"):
    """Ten Phase 3 packs all draw from the same handful of tickers — fetch each
    (symbol, interval) exactly once per run instead of once per pack (which was
    both wasteful and tripped intermittent yfinance rate-limit flakiness)."""
    key = (symbol, interval)
    if key not in _phase3_download_cache:
        _phase3_download_cache[key] = download_data(symbol, interval)
    return _phase3_download_cache[key]


def find_swing_pivots(highs, lows, window=SWING_PIVOT_WINDOW):
    """A bar is a swing high/low if it's the max/min of the window bars on each side of it."""
    n = len(highs)
    swing_high = np.zeros(n, dtype=bool)
    swing_low = np.zeros(n, dtype=bool)
    for i in range(window, n - window):
        if highs[i] == highs[i - window:i + window + 1].max():
            swing_high[i] = True
        if lows[i] == lows[i - window:i + window + 1].min():
            swing_low[i] = True
    return swing_high, swing_low


def resolve_hold_fail(direction, boundary_price, target_price, period_df, j, outcome_window_bars):
    """Shared forward scan for every Phase 3 "does the level hold" detector.
    direction='long' (bias is upward): FAIL if a close comes back below boundary_price;
    HOLD if a high reaches target_price first. direction='short' mirrors both checks.
    Unresolved (neither triggers before the window ends) defaults to FAIL — same
    skeptical-default convention the original breakout detector uses for "fake"."""
    highs = period_df["High"].values
    lows = period_df["Low"].values
    closes = period_df["Close"].values
    n = len(period_df)
    forward_end = min(j + outcome_window_bars, n - 1)
    for k in range(j + 1, forward_end + 1):
        bar_index = k - j - 1
        if direction == "long":
            if closes[k] < boundary_price:
                return "fail", bar_index
            if highs[k] >= target_price:
                return "hold", bar_index
        else:
            if closes[k] > boundary_price:
                return "fail", bar_index
            if lows[k] <= target_price:
                return "hold", bar_index
    return "fail", None


def compute_ema(closes_series, span):
    return closes_series.ewm(span=span, adjust=False).mean()


def running_vwap(period_df, has_volume):
    typical_price = (period_df["High"] + period_df["Low"] + period_df["Close"]) / 3
    if has_volume:
        weight = period_df["Volume"]
        return (typical_price * weight).cumsum() / weight.cumsum().replace(0, np.nan)
    return typical_price.expanding().mean()


def make_simple_context_fn(label_text_fn):
    def _fn(s, pack_cfg):
        text = label_text_fn(s)
        return text, [text]
    return _fn


# ---------- Opening Range Breakout ----------
ORB_WINDOW_BARS = 3  # first 15 minutes at 5-minute bars


def find_orb_scenarios_in_pack(df, symbol, pack_key, pack_cfg, outcome_window_bars):
    scenarios = []
    for session_key, start_str, end_str in pack_cfg["sessions"]:
        if session_key != "open":
            continue  # the opening range only means something for the session containing the actual open
        instances = split_into_session_instances(df, start_str, end_str)
        for label, period_df in instances:
            n = len(period_df)
            if n < ORB_WINDOW_BARS + 5:
                continue
            highs = period_df["High"].values
            lows = period_df["Low"].values
            closes = period_df["Close"].values
            times = period_df.index
            or_high = highs[:ORB_WINDOW_BARS].max()
            or_low = lows[:ORB_WINDOW_BARS].min()
            or_height = or_high - or_low
            if or_height <= 0:
                continue
            vwap_running = running_vwap(period_df, pack_cfg["has_volume"])

            for j in range(ORB_WINDOW_BARS, n - 1):
                if closes[j] > or_high:
                    direction = "long"
                elif closes[j] < or_low:
                    direction = "short"
                else:
                    continue
                breakout_idx = times[j]
                outcome, _, _, resolution_bar_index, _ = compute_outcome(
                    direction, or_high, or_low, or_height, breakout_idx, period_df, j, outcome_window_bars
                )
                correct_answer = "hold" if outcome == "real" else "fail"
                full_loc = df.index.get_loc(breakout_idx)
                context_start = max(0, full_loc - MIN_CONTEXT_BARS + 1)
                chart_df = df.iloc[context_start: full_loc + 1]
                playout_end = min(j + 1 + outcome_window_bars, n)
                playout_df = period_df.iloc[j + 1: playout_end]
                scenarios.append({
                    "symbol": symbol, "session": session_key, "period_label": label,
                    "correct_answer": correct_answer, "resolution_bar_index": resolution_bar_index,
                    "decision_ts": breakout_idx, "chart_df": chart_df, "playout_df": playout_df,
                    "vwap_series": vwap_running.iloc[:playout_end],
                    "extra_fields": {"direction": direction, "range_high": round(float(or_high), 6), "range_low": round(float(or_low), 6)},
                })
                break  # one opening-range call per session
    return scenarios


# ---------- VWAP Pullback ----------
VWAP_PB_TREND_LOOKBACK = 6
VWAP_PB_PROXIMITY_PCT = 0.0015
VWAP_PB_TREND_MULTIPLE = 2.5


def find_vwap_pullback_scenarios_in_pack(df, symbol, pack_key, pack_cfg, outcome_window_bars):
    scenarios = []
    for session_key, start_str, end_str in pack_cfg["sessions"]:
        instances = split_into_session_instances(df, start_str, end_str)
        for label, period_df in instances:
            n = len(period_df)
            if n < VWAP_PB_TREND_LOOKBACK + 15:
                continue
            highs = period_df["High"].values
            lows = period_df["Low"].values
            closes = period_df["Close"].values
            times = period_df.index
            vwap_running = running_vwap(period_df, pack_cfg["has_volume"])
            vwap_vals = vwap_running.values

            j = VWAP_PB_TREND_LOOKBACK
            while j < n - 1:
                back = j - VWAP_PB_TREND_LOOKBACK
                if math.isnan(vwap_vals[j]) or math.isnan(vwap_vals[back]):
                    j += 1
                    continue
                now_dist = abs(closes[j] - vwap_vals[j]) / closes[j]
                was_dist = abs(closes[back] - vwap_vals[back]) / closes[back]
                if now_dist >= VWAP_PB_PROXIMITY_PCT or was_dist < now_dist * VWAP_PB_TREND_MULTIPLE:
                    j += 1
                    continue
                direction = "long" if closes[back] > vwap_vals[back] else "short"
                pre_extreme = highs[back:j].max() if direction == "long" else lows[back:j].min()
                recent_range = highs[back:j + 1].max() - lows[back:j + 1].min()
                if recent_range <= 0:
                    j += 1
                    continue
                buffer = recent_range * 0.15
                if direction == "long":
                    boundary = vwap_vals[j] - buffer
                    target = pre_extreme + recent_range * 0.5
                else:
                    boundary = vwap_vals[j] + buffer
                    target = pre_extreme - recent_range * 0.5

                decision_idx = times[j]
                correct_answer, resolution_bar_index = resolve_hold_fail(direction, boundary, target, period_df, j, outcome_window_bars)
                full_loc = df.index.get_loc(decision_idx)
                context_start = max(0, full_loc - MIN_CONTEXT_BARS + 1)
                chart_df = df.iloc[context_start: full_loc + 1]
                playout_end = min(j + 1 + outcome_window_bars, n)
                playout_df = period_df.iloc[j + 1: playout_end]
                scenarios.append({
                    "symbol": symbol, "session": session_key, "period_label": label,
                    "correct_answer": correct_answer, "resolution_bar_index": resolution_bar_index,
                    "decision_ts": decision_idx, "chart_df": chart_df, "playout_df": playout_df,
                    "vwap_series": vwap_running.iloc[:playout_end],
                    "extra_fields": {"direction": direction},
                })
                j += PHASE3_COOLDOWN_BARS
    return scenarios


# ---------- Supply & Demand ----------
SD_BASE_BARS = 4
SD_DEPARTURE_ATR_MULT = 1.5


def find_supply_demand_scenarios_in_pack(df, symbol, pack_key, pack_cfg, outcome_window_bars):
    scenarios = []
    for session_key, start_str, end_str in pack_cfg["sessions"]:
        instances = split_into_session_instances(df, start_str, end_str)
        for label, period_df in instances:
            n = len(period_df)
            if n < SD_BASE_BARS + 20:
                continue
            highs = period_df["High"].values
            lows = period_df["Low"].values
            closes = period_df["Close"].values
            atr = period_df["ATR"].values
            times = period_df.index
            vwap_running = running_vwap(period_df, pack_cfg["has_volume"])

            rolling_range = np.full(n, np.nan)
            for i in range(SD_BASE_BARS - 1, n):
                rolling_range[i] = highs[i - SD_BASE_BARS + 1:i + 1].max() - lows[i - SD_BASE_BARS + 1:i + 1].min()
            valid = rolling_range[~np.isnan(rolling_range)]
            if len(valid) == 0:
                continue
            tight_threshold = np.percentile(valid, TIGHTNESS_PERCENTILE)

            j = SD_BASE_BARS
            while j < n - 1:
                base_end = j - 1
                if base_end < SD_BASE_BARS - 1 or np.isnan(rolling_range[base_end]) or rolling_range[base_end] > tight_threshold:
                    j += 1
                    continue
                base_high = highs[base_end - SD_BASE_BARS + 1: base_end + 1].max()
                base_low = lows[base_end - SD_BASE_BARS + 1: base_end + 1].min()
                departure_atr = atr[j]
                if math.isnan(departure_atr) or departure_atr <= 0 or (highs[j] - lows[j]) < SD_DEPARTURE_ATR_MULT * departure_atr:
                    j += 1
                    continue
                if closes[j] > base_high:
                    zone_kind = "demand"
                elif closes[j] < base_low:
                    zone_kind = "supply"
                else:
                    j += 1
                    continue

                retest_j = None
                for k in range(j + 1, n):
                    if lows[k] <= base_high and highs[k] >= base_low:
                        retest_j = k
                        break
                if retest_j is None or retest_j >= n - 1:
                    j += 1
                    continue

                zone_height = base_high - base_low
                buffer = max(zone_height * 0.2, 1e-9)
                if zone_kind == "demand":
                    direction = "long"
                    boundary = base_low - buffer
                    target = base_high + zone_height
                else:
                    direction = "short"
                    boundary = base_high + buffer
                    target = base_low - zone_height

                decision_idx = times[retest_j]
                correct_answer, resolution_bar_index = resolve_hold_fail(direction, boundary, target, period_df, retest_j, outcome_window_bars)
                full_loc = df.index.get_loc(decision_idx)
                context_start = max(0, full_loc - MIN_CONTEXT_BARS + 1)
                chart_df = df.iloc[context_start: full_loc + 1]
                playout_end = min(retest_j + 1 + outcome_window_bars, n)
                playout_df = period_df.iloc[retest_j + 1: playout_end]
                scenarios.append({
                    "symbol": symbol, "session": session_key, "period_label": label,
                    "correct_answer": correct_answer, "resolution_bar_index": resolution_bar_index,
                    "decision_ts": decision_idx, "chart_df": chart_df, "playout_df": playout_df,
                    "vwap_series": vwap_running.iloc[:playout_end],
                    "extra_fields": {"zone_kind": zone_kind, "zone_high": round(float(base_high), 6), "zone_low": round(float(base_low), 6)},
                })
                j = retest_j + PHASE3_COOLDOWN_BARS
    return scenarios


# ---------- Trend Pullback (EMA9/EMA20) ----------
EMA_FAST_SPAN = 9
EMA_SLOW_SPAN = 20
TREND_PB_LOOKBACK = 6


def find_trend_pullback_scenarios_in_pack(df, symbol, pack_key, pack_cfg, outcome_window_bars):
    scenarios = []
    for session_key, start_str, end_str in pack_cfg["sessions"]:
        instances = split_into_session_instances(df, start_str, end_str)
        for label, period_df in instances:
            n = len(period_df)
            if n < EMA_SLOW_SPAN + TREND_PB_LOOKBACK + 10:
                continue
            highs = period_df["High"].values
            lows = period_df["Low"].values
            closes_s = period_df["Close"]
            closes = closes_s.values
            times = period_df.index
            ema9 = compute_ema(closes_s, EMA_FAST_SPAN).values
            ema20 = compute_ema(closes_s, EMA_SLOW_SPAN).values
            vwap_running = running_vwap(period_df, pack_cfg["has_volume"])

            j = EMA_SLOW_SPAN + TREND_PB_LOOKBACK
            while j < n - 1:
                back = j - TREND_PB_LOOKBACK
                uptrend = bool((ema9[back:j + 1] > ema20[back:j + 1]).all()) and ema9[j] > ema9[back]
                downtrend = bool((ema9[back:j + 1] < ema20[back:j + 1]).all()) and ema9[j] < ema9[back]
                if not uptrend and not downtrend:
                    j += 1
                    continue
                direction = "long" if uptrend else "short"
                touches_ema9 = lows[j] <= ema9[j] <= highs[j]
                held_ema20 = closes[j] > ema20[j] if direction == "long" else closes[j] < ema20[j]
                if not touches_ema9 or not held_ema20:
                    j += 1
                    continue

                pre_extreme = highs[back:j].max() if direction == "long" else lows[back:j].min()
                recent_range = highs[back:j + 1].max() - lows[back:j + 1].min()
                if recent_range <= 0:
                    j += 1
                    continue
                buffer = recent_range * 0.15
                if direction == "long":
                    boundary = ema20[j] - buffer
                    target = pre_extreme + recent_range * 0.5
                else:
                    boundary = ema20[j] + buffer
                    target = pre_extreme - recent_range * 0.5

                decision_idx = times[j]
                correct_answer, resolution_bar_index = resolve_hold_fail(direction, boundary, target, period_df, j, outcome_window_bars)
                full_loc = df.index.get_loc(decision_idx)
                context_start = max(0, full_loc - MIN_CONTEXT_BARS + 1)
                chart_df = df.iloc[context_start: full_loc + 1]
                playout_end = min(j + 1 + outcome_window_bars, n)
                playout_df = period_df.iloc[j + 1: playout_end]
                scenarios.append({
                    "symbol": symbol, "session": session_key, "period_label": label,
                    "correct_answer": correct_answer, "resolution_bar_index": resolution_bar_index,
                    "decision_ts": decision_idx, "chart_df": chart_df, "playout_df": playout_df,
                    "vwap_series": vwap_running.iloc[:playout_end],
                    "extra_fields": {"direction": direction},
                })
                j += PHASE3_COOLDOWN_BARS
    return scenarios


# ---------- Mean Reversion (fade >2x ATR from VWAP) ----------
MR_ATR_EXTENDED_MULT = 2.0
MR_ATR_FAIL_MULT = 3.0
MR_ATR_HOLD_MULT = 1.0


def find_mean_reversion_scenarios_in_pack(df, symbol, pack_key, pack_cfg, outcome_window_bars):
    scenarios = []
    for session_key, start_str, end_str in pack_cfg["sessions"]:
        instances = split_into_session_instances(df, start_str, end_str)
        for label, period_df in instances:
            n = len(period_df)
            if n < 20:
                continue
            closes = period_df["Close"].values
            atr = period_df["ATR"].values
            times = period_df.index
            vwap_running = running_vwap(period_df, pack_cfg["has_volume"])
            vwap_vals = vwap_running.values

            j = 15
            while j < n - 1:
                if math.isnan(vwap_vals[j]) or math.isnan(atr[j]) or atr[j] <= 0:
                    j += 1
                    continue
                distance = closes[j] - vwap_vals[j]
                if abs(distance) < MR_ATR_EXTENDED_MULT * atr[j]:
                    j += 1
                    continue
                direction = "short" if distance > 0 else "long"  # fade back toward VWAP
                if direction == "short":
                    target = vwap_vals[j] + MR_ATR_HOLD_MULT * atr[j]
                    boundary = vwap_vals[j] + MR_ATR_FAIL_MULT * atr[j]
                else:
                    target = vwap_vals[j] - MR_ATR_HOLD_MULT * atr[j]
                    boundary = vwap_vals[j] - MR_ATR_FAIL_MULT * atr[j]

                decision_idx = times[j]
                correct_answer, resolution_bar_index = resolve_hold_fail(direction, boundary, target, period_df, j, outcome_window_bars)
                full_loc = df.index.get_loc(decision_idx)
                context_start = max(0, full_loc - MIN_CONTEXT_BARS + 1)
                chart_df = df.iloc[context_start: full_loc + 1]
                playout_end = min(j + 1 + outcome_window_bars, n)
                playout_df = period_df.iloc[j + 1: playout_end]
                scenarios.append({
                    "symbol": symbol, "session": session_key, "period_label": label,
                    "correct_answer": correct_answer, "resolution_bar_index": resolution_bar_index,
                    "decision_ts": decision_idx, "chart_df": chart_df, "playout_df": playout_df,
                    "vwap_series": vwap_running.iloc[:playout_end],
                    "extra_fields": {"fade_direction": direction},
                })
                j += PHASE3_COOLDOWN_BARS
    return scenarios


# ---------- Range Trading ----------
RANGE_BARS = 12
RANGE_TIGHTNESS_PERCENTILE = 30
RANGE_PROXIMITY_PCT = 0.002


def find_range_trading_scenarios_in_pack(df, symbol, pack_key, pack_cfg, outcome_window_bars):
    scenarios = []
    for session_key, start_str, end_str in pack_cfg["sessions"]:
        instances = split_into_session_instances(df, start_str, end_str)
        for label, period_df in instances:
            n = len(period_df)
            if n < RANGE_BARS + 15:
                continue
            highs = period_df["High"].values
            lows = period_df["Low"].values
            closes = period_df["Close"].values
            times = period_df.index
            vwap_running = running_vwap(period_df, pack_cfg["has_volume"])

            rolling_range = np.full(n, np.nan)
            for i in range(RANGE_BARS - 1, n):
                rolling_range[i] = highs[i - RANGE_BARS + 1:i + 1].max() - lows[i - RANGE_BARS + 1:i + 1].min()
            valid = rolling_range[~np.isnan(rolling_range)]
            if len(valid) == 0:
                continue
            tight_threshold = np.percentile(valid, RANGE_TIGHTNESS_PERCENTILE)

            j = RANGE_BARS
            while j < n - 1:
                i = j - 1
                if np.isnan(rolling_range[i]) or rolling_range[i] > tight_threshold:
                    j += 1
                    continue
                range_high = highs[i - RANGE_BARS + 1:i + 1].max()
                range_low = lows[i - RANGE_BARS + 1:i + 1].min()
                range_height = range_high - range_low
                if range_height <= 0:
                    j += 1
                    continue
                touches_high = (highs[i - RANGE_BARS + 1:i + 1] >= range_high - range_height * 0.05).sum()
                touches_low = (lows[i - RANGE_BARS + 1:i + 1] <= range_low + range_height * 0.05).sum()
                if touches_high < 2 or touches_low < 2:
                    j += 1
                    continue

                dist_high = abs(closes[j] - range_high) / range_high
                dist_low = abs(closes[j] - range_low) / range_low
                if dist_high < RANGE_PROXIMITY_PCT:
                    direction, boundary_side = "short", "high"
                elif dist_low < RANGE_PROXIMITY_PCT:
                    direction, boundary_side = "long", "low"
                else:
                    j += 1
                    continue

                buffer = range_height * 0.15
                if direction == "short":
                    boundary = range_high + buffer
                    target = range_low + range_height * 0.5
                else:
                    boundary = range_low - buffer
                    target = range_high - range_height * 0.5

                decision_idx = times[j]
                correct_answer, resolution_bar_index = resolve_hold_fail(direction, boundary, target, period_df, j, outcome_window_bars)
                full_loc = df.index.get_loc(decision_idx)
                context_start = max(0, full_loc - MIN_CONTEXT_BARS + 1)
                chart_df = df.iloc[context_start: full_loc + 1]
                playout_end = min(j + 1 + outcome_window_bars, n)
                playout_df = period_df.iloc[j + 1: playout_end]
                scenarios.append({
                    "symbol": symbol, "session": session_key, "period_label": label,
                    "correct_answer": correct_answer, "resolution_bar_index": resolution_bar_index,
                    "decision_ts": decision_idx, "chart_df": chart_df, "playout_df": playout_df,
                    "vwap_series": vwap_running.iloc[:playout_end],
                    "extra_fields": {"range_high": round(float(range_high), 6), "range_low": round(float(range_low), 6), "boundary_side": boundary_side},
                })
                j += PHASE3_COOLDOWN_BARS
    return scenarios


# ---------- ICT: Liquidity Sweep / Stop Hunt ----------
LS_SWEEP_LOOKAHEAD = 30


def find_liquidity_sweep_scenarios_in_pack(df, symbol, pack_key, pack_cfg, outcome_window_bars):
    scenarios = []
    for session_key, start_str, end_str in pack_cfg["sessions"]:
        instances = split_into_session_instances(df, start_str, end_str)
        for label, period_df in instances:
            n = len(period_df)
            if n < SWING_PIVOT_WINDOW * 2 + 20:
                continue
            highs = period_df["High"].values
            lows = period_df["Low"].values
            closes = period_df["Close"].values
            times = period_df.index
            vwap_running = running_vwap(period_df, pack_cfg["has_volume"])
            swing_high, swing_low = find_swing_pivots(highs, lows, SWING_PIVOT_WINDOW)
            pivot_idxs = [i for i in range(n) if swing_high[i] or swing_low[i]]

            j = SWING_PIVOT_WINDOW * 2
            while j < n - 1:
                candidates = [p for p in pivot_idxs if p < j - 1 and j - p <= LS_SWEEP_LOOKAHEAD]
                if not candidates:
                    j += 1
                    continue
                pivot_i = candidates[-1]
                if swing_high[pivot_i]:
                    level = highs[pivot_i]
                    pierced = highs[j] > level and closes[j] < level
                    direction = "short"
                elif swing_low[pivot_i]:
                    level = lows[pivot_i]
                    pierced = lows[j] < level and closes[j] > level
                    direction = "long"
                else:
                    j += 1
                    continue
                if not pierced:
                    j += 1
                    continue

                lb = max(0, j - SWING_PIVOT_WINDOW)
                recent_range = highs[lb:j + 1].max() - lows[lb:j + 1].min()
                if recent_range <= 0:
                    j += 1
                    continue
                buffer = recent_range * 0.1
                if direction == "short":
                    boundary = level + buffer
                    target = level - recent_range * 0.75
                else:
                    boundary = level - buffer
                    target = level + recent_range * 0.75

                decision_idx = times[j]
                hold_fail, resolution_bar_index = resolve_hold_fail(direction, boundary, target, period_df, j, outcome_window_bars)
                # relabeled to the pack's own vocabulary: "hold" of the reversal bias = a genuine sweep
                correct_answer = "sweep" if hold_fail == "hold" else "breakout"
                full_loc = df.index.get_loc(decision_idx)
                context_start = max(0, full_loc - MIN_CONTEXT_BARS + 1)
                chart_df = df.iloc[context_start: full_loc + 1]
                playout_end = min(j + 1 + outcome_window_bars, n)
                playout_df = period_df.iloc[j + 1: playout_end]
                scenarios.append({
                    "symbol": symbol, "session": session_key, "period_label": label,
                    "correct_answer": correct_answer, "resolution_bar_index": resolution_bar_index,
                    "decision_ts": decision_idx, "chart_df": chart_df, "playout_df": playout_df,
                    "vwap_series": vwap_running.iloc[:playout_end],
                    "extra_fields": {"swept_level": round(float(level), 6), "direction": direction},
                })
                j += PHASE3_COOLDOWN_BARS
    return scenarios


# ---------- ICT: Fair Value Gap ----------
def find_fvg_scenarios_in_pack(df, symbol, pack_key, pack_cfg, outcome_window_bars):
    scenarios = []
    for session_key, start_str, end_str in pack_cfg["sessions"]:
        instances = split_into_session_instances(df, start_str, end_str)
        for label, period_df in instances:
            n = len(period_df)
            if n < 15:
                continue
            highs = period_df["High"].values
            lows = period_df["Low"].values
            times = period_df.index
            vwap_running = running_vwap(period_df, pack_cfg["has_volume"])

            j = 2
            while j < n - 1:
                c1_high, c1_low = highs[j - 2], lows[j - 2]
                c3_high, c3_low = highs[j], lows[j]
                if c1_high < c3_low:
                    kind, gap_top, gap_bottom = "bullish", c3_low, c1_high
                elif c1_low > c3_high:
                    kind, gap_top, gap_bottom = "bearish", c1_low, c3_high
                else:
                    j += 1
                    continue
                if gap_top - gap_bottom <= 0:
                    j += 1
                    continue

                fill_bar_index = None
                forward_end = min(j + outcome_window_bars, n - 1)
                for k in range(j + 1, forward_end + 1):
                    if lows[k] <= gap_top and highs[k] >= gap_bottom:
                        fill_bar_index = k - j - 1
                        break
                correct_answer = "fill" if fill_bar_index is not None else "no_fill"

                decision_idx = times[j]
                full_loc = df.index.get_loc(decision_idx)
                context_start = max(0, full_loc - MIN_CONTEXT_BARS + 1)
                chart_df = df.iloc[context_start: full_loc + 1]
                playout_end = min(j + 1 + outcome_window_bars, n)
                playout_df = period_df.iloc[j + 1: playout_end]
                scenarios.append({
                    "symbol": symbol, "session": session_key, "period_label": label,
                    "correct_answer": correct_answer, "resolution_bar_index": fill_bar_index,
                    "decision_ts": decision_idx, "chart_df": chart_df, "playout_df": playout_df,
                    "vwap_series": vwap_running.iloc[:playout_end],
                    "extra_fields": {"kind": kind, "gap_top": round(float(gap_top), 6), "gap_bottom": round(float(gap_bottom), 6)},
                })
                j += PHASE3_COOLDOWN_BARS
    return scenarios


# ---------- ICT: Order Blocks ----------
OB_DISPLACEMENT_ATR_MULT = 1.5


def find_order_block_scenarios_in_pack(df, symbol, pack_key, pack_cfg, outcome_window_bars):
    scenarios = []
    for session_key, start_str, end_str in pack_cfg["sessions"]:
        instances = split_into_session_instances(df, start_str, end_str)
        for label, period_df in instances:
            n = len(period_df)
            if n < 20:
                continue
            highs = period_df["High"].values
            lows = period_df["Low"].values
            closes = period_df["Close"].values
            opens = period_df["Open"].values
            atr = period_df["ATR"].values
            times = period_df.index
            vwap_running = running_vwap(period_df, pack_cfg["has_volume"])

            j = 15
            while j < n - 1:
                if math.isnan(atr[j]) or atr[j] <= 0 or (highs[j] - lows[j]) < OB_DISPLACEMENT_ATR_MULT * atr[j]:
                    j += 1
                    continue
                is_up = closes[j] > opens[j]
                prev_i = j - 1
                prev_is_down = closes[prev_i] < opens[prev_i]
                prev_is_up = closes[prev_i] > opens[prev_i]
                if is_up and prev_is_down:
                    zone_kind, zone_high, zone_low = "bullish", highs[prev_i], lows[prev_i]
                elif not is_up and prev_is_up:
                    zone_kind, zone_high, zone_low = "bearish", highs[prev_i], lows[prev_i]
                else:
                    j += 1
                    continue

                retest_j = None
                for k in range(j + 1, n):
                    if lows[k] <= zone_high and highs[k] >= zone_low:
                        retest_j = k
                        break
                if retest_j is None or retest_j >= n - 1:
                    j += 1
                    continue

                zone_height = zone_high - zone_low
                if zone_height <= 0:
                    j += 1
                    continue
                buffer = zone_height * 0.2
                if zone_kind == "bullish":
                    direction = "long"
                    boundary = zone_low - buffer
                    target = zone_high + zone_height
                else:
                    direction = "short"
                    boundary = zone_high + buffer
                    target = zone_low - zone_height

                decision_idx = times[retest_j]
                correct_answer, resolution_bar_index = resolve_hold_fail(direction, boundary, target, period_df, retest_j, outcome_window_bars)
                full_loc = df.index.get_loc(decision_idx)
                context_start = max(0, full_loc - MIN_CONTEXT_BARS + 1)
                chart_df = df.iloc[context_start: full_loc + 1]
                playout_end = min(retest_j + 1 + outcome_window_bars, n)
                playout_df = period_df.iloc[retest_j + 1: playout_end]
                scenarios.append({
                    "symbol": symbol, "session": session_key, "period_label": label,
                    "correct_answer": correct_answer, "resolution_bar_index": resolution_bar_index,
                    "decision_ts": decision_idx, "chart_df": chart_df, "playout_df": playout_df,
                    "vwap_series": vwap_running.iloc[:playout_end],
                    "extra_fields": {"zone_kind": zone_kind, "zone_high": round(float(zone_high), 6), "zone_low": round(float(zone_low), 6)},
                })
                j = retest_j + PHASE3_COOLDOWN_BARS
    return scenarios


# ---------- ICT: Market Structure (BOS vs CHoCH) ----------
def find_market_structure_scenarios_in_pack(df, symbol, pack_key, pack_cfg, outcome_window_bars):
    # Scans the full regular session (not the fragmented open/midday/power_hour
    # windows) — swing highs/lows need room to separate, and a trend needs more
    # than a 1.5-hour window to establish.
    scenarios = []
    for session_key, start_str, end_str in [("full_day", "09:30", "16:00")]:
        instances = split_into_session_instances(df, start_str, end_str)
        for label, period_df in instances:
            n = len(period_df)
            if n < SWING_PIVOT_WINDOW * 4 + 10:
                continue
            highs = period_df["High"].values
            lows = period_df["Low"].values
            closes = period_df["Close"].values
            times = period_df.index
            vwap_running = running_vwap(period_df, pack_cfg["has_volume"])
            swing_high, swing_low = find_swing_pivots(highs, lows, SWING_PIVOT_WINDOW)
            sh_idxs = [i for i in range(n) if swing_high[i]]
            sl_idxs = [i for i in range(n) if swing_low[i]]

            j = SWING_PIVOT_WINDOW * 3
            while j < n - 1:
                prior_sh = [i for i in sh_idxs if i < j - 1]
                prior_sl = [i for i in sl_idxs if i < j - 1]
                if len(prior_sh) < 2 or len(prior_sl) < 2:
                    j += 1
                    continue
                last_sh, prev_sh = prior_sh[-1], prior_sh[-2]
                last_sl, prev_sl = prior_sl[-1], prior_sl[-2]
                uptrend = highs[last_sh] > highs[prev_sh] and lows[last_sl] > lows[prev_sl] and last_sl > prev_sh
                downtrend = highs[last_sh] < highs[prev_sh] and lows[last_sl] < lows[prev_sl] and last_sh > prev_sl
                if not uptrend and not downtrend:
                    j += 1
                    continue

                correct_answer = None
                if uptrend and closes[j] > highs[last_sh]:
                    correct_answer = "bos"
                elif uptrend and closes[j] < lows[last_sl]:
                    correct_answer = "choch"
                elif downtrend and closes[j] < lows[last_sl]:
                    correct_answer = "bos"
                elif downtrend and closes[j] > highs[last_sh]:
                    correct_answer = "choch"
                if correct_answer is None:
                    j += 1
                    continue

                decision_idx = times[j]
                full_loc = df.index.get_loc(decision_idx)
                context_start = max(0, full_loc - MIN_CONTEXT_BARS + 1)
                chart_df = df.iloc[context_start: full_loc + 1]
                playout_end = min(j + 1 + outcome_window_bars, n)
                playout_df = period_df.iloc[j + 1: playout_end]
                scenarios.append({
                    "symbol": symbol, "session": session_key, "period_label": label,
                    "correct_answer": correct_answer, "resolution_bar_index": None,
                    "decision_ts": decision_idx, "chart_df": chart_df, "playout_df": playout_df,
                    "vwap_series": vwap_running.iloc[:playout_end],
                    "extra_fields": {"trend": "up" if uptrend else "down"},
                })
                j += PHASE3_COOLDOWN_BARS
    return scenarios


# ---------- ICT: SMT Divergence (correlated pair) ----------
SMT_PAIR = ("QQQ", "SPY")


def find_smt_scenarios(df_a, df_b, symbol_a, symbol_b, pack_cfg, outcome_window_bars):
    # Full regular session, same reasoning as Market Structure: swing pivots
    # need more room to separate than a single fragmented open/midday/power_hour
    # window gives them.
    scenarios = []
    for session_key, start_str, end_str in [("full_day", "09:30", "16:00")]:
        instances_a = split_into_session_instances(df_a, start_str, end_str)
        instances_b = dict(split_into_session_instances(df_b, start_str, end_str))
        for label, period_a in instances_a:
            if label not in instances_b:
                continue
            period_b = instances_b[label]
            shared_idx = period_a.index.intersection(period_b.index)
            if len(shared_idx) < SWING_PIVOT_WINDOW * 4 + 10:
                continue
            period_a = period_a.loc[shared_idx]
            period_b = period_b.loc[shared_idx]
            n = len(period_a)
            highs_a, lows_a = period_a["High"].values, period_a["Low"].values
            highs_b, lows_b = period_b["High"].values, period_b["Low"].values
            times = period_a.index
            vwap_running = running_vwap(period_a, pack_cfg["has_volume"])
            sh_a, sl_a = find_swing_pivots(highs_a, lows_a, SWING_PIVOT_WINDOW)
            sh_idxs = [i for i in range(n) if sh_a[i]]
            sl_idxs = [i for i in range(n) if sl_a[i]]

            j = SWING_PIVOT_WINDOW * 3
            while j < n - 1:
                prior_sh = [i for i in sh_idxs if i < j - 1]
                prior_sl = [i for i in sl_idxs if i < j - 1]
                bearish_smt = bullish_smt = False
                ref_i = None
                if prior_sh and sh_a[j]:
                    last_sh = prior_sh[-1]
                    if highs_a[j] > highs_a[last_sh] and highs_b[j] < highs_b[last_sh]:
                        bearish_smt, ref_i = True, last_sh
                if not bearish_smt and prior_sl and sl_a[j]:
                    last_sl = prior_sl[-1]
                    if lows_a[j] < lows_a[last_sl] and lows_b[j] > lows_b[last_sl]:
                        bullish_smt, ref_i = True, last_sl
                if not bearish_smt and not bullish_smt:
                    j += 1
                    continue

                lb = max(0, j - SWING_PIVOT_WINDOW)
                recent_range = highs_a[lb:j + 1].max() - lows_a[lb:j + 1].min()
                if recent_range <= 0:
                    j += 1
                    continue
                if bearish_smt:
                    direction = "short"
                    boundary = highs_a[j] + recent_range * 0.1
                    target = highs_a[ref_i] - recent_range * 0.75
                else:
                    direction = "long"
                    boundary = lows_a[j] - recent_range * 0.1
                    target = lows_a[ref_i] + recent_range * 0.75

                decision_idx = times[j]
                hold_fail, resolution_bar_index = resolve_hold_fail(direction, boundary, target, period_a, j, outcome_window_bars)
                correct_answer = "confirmed" if hold_fail == "hold" else "failed"
                full_loc = df_a.index.get_loc(decision_idx)
                context_start = max(0, full_loc - MIN_CONTEXT_BARS + 1)
                chart_df = df_a.iloc[context_start: full_loc + 1]
                compare_df = df_b.reindex(chart_df.index, method="nearest", tolerance=pd.Timedelta(minutes=10))
                playout_end = min(j + 1 + outcome_window_bars, n)
                playout_df = period_a.iloc[j + 1: playout_end]
                scenarios.append({
                    "symbol": symbol_a, "session": session_key, "period_label": label,
                    "correct_answer": correct_answer, "resolution_bar_index": resolution_bar_index,
                    "decision_ts": decision_idx, "chart_df": chart_df, "playout_df": playout_df,
                    "vwap_series": vwap_running.iloc[:playout_end], "compare_df": compare_df,
                    "extra_fields": {"compare_symbol": symbol_b, "smt_type": "bearish" if bearish_smt else "bullish"},
                })
                j += PHASE3_COOLDOWN_BARS
    return scenarios


# ---------- ICT: Kill Zones ----------
# Built from forex data (EUR/USD) since it's the only pack with round-the-clock
# candles that actually cover these overnight-for-US-markets hours.
KZ_LONDON_START, KZ_LONDON_END = "02:00", "05:00"
KZ_NY_START, KZ_NY_END = "07:00", "10:00"
KZ_SAMPLE_STEP_BARS = 6  # every 30 minutes


def classify_kill_zone(ts):
    hhmm = ts.strftime("%H:%M")
    if KZ_LONDON_START <= hhmm < KZ_LONDON_END:
        return "london"
    if KZ_NY_START <= hhmm < KZ_NY_END:
        return "new_york"
    return "neither"


def find_kill_zone_scenarios(df, symbol, pack_cfg, outcome_window_bars):
    scenarios = []
    n = len(df)
    for j in range(MIN_CONTEXT_BARS, n - 1, KZ_SAMPLE_STEP_BARS):
        decision_idx = df.index[j]
        context_start = max(0, j - MIN_CONTEXT_BARS + 1)
        playout_end = min(j + 1 + outcome_window_bars, n)
        chart_df = df.iloc[context_start: j + 1]
        playout_df = df.iloc[j + 1: playout_end]
        # VWAP has no real session boundary on this continuous-time pack — scope
        # the running average to just the visible window instead of the full
        # 60-day series (which is both meaningless and a huge payload).
        window_df = df.iloc[context_start: playout_end]
        vwap_series = running_vwap(window_df, pack_cfg["has_volume"])
        scenarios.append({
            "symbol": symbol, "session": "n/a", "period_label": str(decision_idx.date()),
            "correct_answer": classify_kill_zone(decision_idx), "resolution_bar_index": None,
            "decision_ts": decision_idx, "chart_df": chart_df, "playout_df": playout_df,
            "vwap_series": vwap_series,
            "extra_fields": {},
        })
    return scenarios


def ensure_visual_range(record, candles):
    """Guarantee every drill record has range_high/range_low — the shared game
    UI (orange zone shading, playout proximity pulse, P&L magnitude) depends on
    them existing. Reuses a pack-specific zone/gap field where one exists,
    otherwise falls back to the last 10 visible candles' high/low as a generic
    "recent range" so packs without a natural zone concept still render fine."""
    if "range_high" in record and "range_low" in record:
        return
    zone_high = record.get("zone_high", record.get("gap_top"))
    zone_low = record.get("zone_low", record.get("gap_bottom"))
    if zone_high is not None and zone_low is not None:
        record["range_high"] = zone_high
        record["range_low"] = zone_low
        return
    recent = candles[-10:] if len(candles) >= 10 else candles
    record["range_high"] = round(max(c["high"] for c in recent), 6)
    record["range_low"] = round(min(c["low"] for c in recent), 6)


# ---------- generic Phase 3 pack builder (hold/fail & 2-way classification packs) ----------
def build_binary_pack(pack_key, pack_cfg, timeframe, interval, output_file, drill_style,
                       find_fn, context_fn, id_prefix, label_a="hold", label_b="fail", tickers=None):
    print(f"\n=== {drill_style.upper()} PACK: {pack_cfg['label']} ({timeframe}) ===")
    outcome_window_bars = pack_cfg["outcome_window_min"] // 5
    all_scenarios = []
    for symbol in (tickers if tickers is not None else pack_cfg["tickers"]):
        df = download_data_cached(symbol, interval)
        if df is None:
            continue
        found = find_fn(df, symbol, pack_key, pack_cfg, outcome_window_bars)
        all_scenarios.extend(found)
        a_count = sum(1 for s in found if s["correct_answer"] == label_a)
        b_count = sum(1 for s in found if s["correct_answer"] == label_b)
        print(f"    {symbol}: {len(found)} scenarios -> {a_count} {label_a} / {b_count} {label_b}")

    pool_a = [s for s in all_scenarios if s["correct_answer"] == label_a]
    pool_b = [s for s in all_scenarios if s["correct_answer"] == label_b]
    n_pair = min(len(pool_a), len(pool_b), MAX_DECK_SIZE // 2)
    random.seed(RANDOM_SEED)
    sampled_a = random.sample(pool_a, n_pair) if len(pool_a) > n_pair else pool_a
    sampled_b = random.sample(pool_b, n_pair) if len(pool_b) > n_pair else pool_b
    deck = sampled_a + sampled_b
    random.shuffle(deck)

    print(f"  Pools: {label_a}={len(pool_a)} {label_b}={len(pool_b)}  Deck: {len(deck)}")
    if len(deck) < MIN_SHIPPABLE_DECK_SIZE:
        print(f"  SKIPPING pack '{drill_style}': deck size {len(deck)} below shippable floor.")
        return None

    records = []
    for i, s in enumerate(deck, start=1):
        candles, playout_candles, vwap = build_candle_payload(s, pack_cfg["has_volume"])
        context, context_all = context_fn(s, pack_cfg)
        record = {
            "id": f"{id_prefix}_{i:03d}", "ticker": s["symbol"], "market": pack_key,
            "drill_style": drill_style, "session": s["session"], "timeframe": timeframe,
            "has_volume": pack_cfg["has_volume"], "date": s["period_label"],
            "correct_answer": s["correct_answer"], "resolution_bar_index": s["resolution_bar_index"],
            "context": context, "context_all": context_all,
            "breakout_time": int(s["decision_ts"].timestamp()),
            "candles": candles, "playout_candles": playout_candles, "vwap": vwap,
        }
        if "compare_df" in s:
            comp = s["compare_df"]
            record["compare_symbol"] = s["extra_fields"].get("compare_symbol")
            record["compare_series"] = [
                {"time": int(ts.timestamp()), "value": round(float(row["Close"]), 6)}
                for ts, row in comp.iterrows() if not pd.isna(row["Close"])
            ]
        record.update(s.get("extra_fields", {}))
        ensure_visual_range(record, candles)
        records.append(record)

    out_path = os.path.join(DRILLS_DIR, output_file)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)

    total = len(records)
    a_total = sum(1 for r in records if r["correct_answer"] == label_a)
    b_total = sum(1 for r in records if r["correct_answer"] == label_b)
    print(f"  --- {drill_style} deck composition ({out_path}) ---")
    print(f"  Total: {total} ({label_a}={a_total}, {label_b}={b_total})")
    return records


def build_smt_pack(pack_key, pack_cfg, timeframe, interval, output_file):
    symbol_a, symbol_b = SMT_PAIR
    print(f"\n=== SMT_DIVERGENCE PACK: {symbol_a} vs {symbol_b} ({timeframe}) ===")
    df_a = download_data_cached(symbol_a, interval)
    df_b = download_data_cached(symbol_b, interval)
    if df_a is None or df_b is None:
        print("  SKIPPING SMT pack: could not download both symbols.")
        return None
    outcome_window_bars = pack_cfg["outcome_window_min"] // 5
    scenarios = find_smt_scenarios(df_a, df_b, symbol_a, symbol_b, pack_cfg, outcome_window_bars)
    confirmed = sum(1 for s in scenarios if s["correct_answer"] == "confirmed")
    failed = sum(1 for s in scenarios if s["correct_answer"] == "failed")
    print(f"    {len(scenarios)} scenarios -> {confirmed} confirmed / {failed} failed")

    pool_a = [s for s in scenarios if s["correct_answer"] == "confirmed"]
    pool_b = [s for s in scenarios if s["correct_answer"] == "failed"]
    n_pair = min(len(pool_a), len(pool_b), MAX_DECK_SIZE // 2)
    random.seed(RANDOM_SEED)
    sampled_a = random.sample(pool_a, n_pair) if len(pool_a) > n_pair else pool_a
    sampled_b = random.sample(pool_b, n_pair) if len(pool_b) > n_pair else pool_b
    deck = sampled_a + sampled_b
    random.shuffle(deck)
    print(f"  Deck: {len(deck)}")
    if len(deck) < MIN_SHIPPABLE_DECK_SIZE:
        print(f"  SKIPPING SMT pack: deck size {len(deck)} below shippable floor.")
        return None

    records = []
    for i, s in enumerate(deck, start=1):
        candles, playout_candles, vwap = build_candle_payload(s, pack_cfg["has_volume"])
        smt_type = s["extra_fields"]["smt_type"]
        context = f"{'Bearish' if smt_type == 'bearish' else 'Bullish'} SMT divergence vs {symbol_b}"
        comp = s["compare_df"]
        compare_series = [
            {"time": int(ts.timestamp()), "value": round(float(row["Close"]), 6)}
            for ts, row in comp.iterrows() if not pd.isna(row["Close"])
        ]
        record = {
            "id": f"smt_{i:03d}", "ticker": s["symbol"], "market": pack_key,
            "drill_style": "smt_divergence", "session": s["session"], "timeframe": timeframe,
            "has_volume": pack_cfg["has_volume"], "date": s["period_label"],
            "correct_answer": s["correct_answer"], "resolution_bar_index": s["resolution_bar_index"],
            "context": context, "context_all": [context],
            "breakout_time": int(s["decision_ts"].timestamp()),
            "candles": candles, "playout_candles": playout_candles, "vwap": vwap,
            "compare_symbol": symbol_b, "compare_series": compare_series, "smt_type": smt_type,
        }
        ensure_visual_range(record, candles)
        records.append(record)

    out_path = os.path.join(DRILLS_DIR, output_file)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)
    print(f"  --- smt_divergence deck composition ({out_path}) ---")
    print(f"  Total: {len(records)}")
    return records


def build_kill_zone_pack(pack_cfg, timeframe, interval, output_file, symbol="EURUSD=X"):
    print(f"\n=== KILL_ZONES PACK: {symbol} ({timeframe}) ===")
    df = download_data_cached(symbol, interval)
    if df is None:
        print("  SKIPPING kill zones pack: no data.")
        return None
    outcome_window_bars = pack_cfg["outcome_window_min"] // 5
    scenarios = find_kill_zone_scenarios(df, symbol, pack_cfg, outcome_window_bars)
    pools = {k: [s for s in scenarios if s["correct_answer"] == k] for k in ("london", "new_york", "neither")}
    for k, pool in pools.items():
        print(f"    {k}: {len(pool)} candidates")

    n_each = min(len(pools["london"]), len(pools["new_york"]), len(pools["neither"]), MAX_DECK_SIZE // 3)
    random.seed(RANDOM_SEED)
    deck = []
    for k, pool in pools.items():
        deck.extend(random.sample(pool, n_each) if len(pool) > n_each else pool)
    random.shuffle(deck)
    print(f"  Deck: {len(deck)}")
    if len(deck) < MIN_SHIPPABLE_DECK_SIZE:
        print(f"  SKIPPING kill zones pack: deck size {len(deck)} below shippable floor.")
        return None

    records = []
    for i, s in enumerate(deck, start=1):
        candles, playout_candles, vwap = build_candle_payload(s, pack_cfg["has_volume"])
        et_time = s["decision_ts"].strftime("%H:%M ET")
        context = f"Candle timestamp: {et_time}"
        record = {
            "id": f"kz_{i:03d}", "ticker": s["symbol"], "market": "forex",
            "drill_style": "kill_zones", "session": s["session"], "timeframe": timeframe,
            "has_volume": pack_cfg["has_volume"], "date": s["period_label"],
            "correct_answer": s["correct_answer"], "resolution_bar_index": None,
            "context": context, "context_all": [context],
            "breakout_time": int(s["decision_ts"].timestamp()),
            "candles": candles, "playout_candles": playout_candles, "vwap": vwap,
        }
        ensure_visual_range(record, candles)
        records.append(record)

    out_path = os.path.join(DRILLS_DIR, output_file)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)
    print(f"  --- kill_zones deck composition ({out_path}) ---")
    print(f"  Total: {len(records)}")
    return records


def generate_phase3_packs():
    """Additive — does not touch the existing market-pack or LSW files.
    All classical + ICT packs are built from the stocks 5m dataset (SMT uses
    QQQ vs SPY specifically; Kill Zones uses forex EUR/USD instead, since it's
    the only pack with round-the-clock candles). See DETECTION.md."""
    os.makedirs(DRILLS_DIR, exist_ok=True)
    stocks_cfg = MARKET_PACKS["stocks"]
    forex_cfg = MARKET_PACKS["forex"]

    build_binary_pack("stocks", stocks_cfg, "5m", "5m", "drills-orb.json", "orb",
                       find_orb_scenarios_in_pack,
                       make_simple_context_fn(lambda s: f"Opening range breakout to the {'upside' if s['extra_fields']['direction'] == 'long' else 'downside'}"),
                       "orb")
    build_binary_pack("stocks", stocks_cfg, "5m", "5m", "drills-vwap-pullback.json", "vwap_pullback",
                       find_vwap_pullback_scenarios_in_pack,
                       make_simple_context_fn(lambda s: "Price pulled back to VWAP after trending away from it"),
                       "vwappb")
    build_binary_pack("stocks", stocks_cfg, "5m", "5m", "drills-supply-demand.json", "supply_demand",
                       find_supply_demand_scenarios_in_pack,
                       make_simple_context_fn(lambda s: f"Retest of a {s['extra_fields']['zone_kind']} zone"),
                       "sd")
    build_binary_pack("stocks", stocks_cfg, "5m", "5m", "drills-trend-pullback.json", "trend_pullback",
                       find_trend_pullback_scenarios_in_pack,
                       make_simple_context_fn(lambda s: "Pullback to the EMA9/20 in an established trend"),
                       "tpb")
    build_binary_pack("stocks", stocks_cfg, "5m", "5m", "drills-mean-reversion.json", "mean_reversion",
                       find_mean_reversion_scenarios_in_pack,
                       make_simple_context_fn(lambda s: "Price is 2x+ ATR away from VWAP"),
                       "mr")
    build_binary_pack("stocks", stocks_cfg, "5m", "5m", "drills-range-trading.json", "range_trading",
                       find_range_trading_scenarios_in_pack,
                       make_simple_context_fn(lambda s: f"Price is testing the range {s['extra_fields']['boundary_side']}"),
                       "rt")
    build_binary_pack("stocks", stocks_cfg, "5m", "5m", "drills-liquidity-sweep.json", "liquidity_sweep",
                       find_liquidity_sweep_scenarios_in_pack,
                       make_simple_context_fn(lambda s: "Price pierced a prior swing level and closed back inside"),
                       "ls", label_a="sweep", label_b="breakout")
    build_binary_pack("stocks", stocks_cfg, "5m", "5m", "drills-fvg.json", "fair_value_gap",
                       find_fvg_scenarios_in_pack,
                       make_simple_context_fn(lambda s: f"A {s['extra_fields']['kind']} Fair Value Gap just formed"),
                       "fvg", label_a="no_fill", label_b="fill")
    build_binary_pack("stocks", stocks_cfg, "5m", "5m", "drills-order-blocks.json", "order_blocks",
                       find_order_block_scenarios_in_pack,
                       make_simple_context_fn(lambda s: f"Retest of a {s['extra_fields']['zone_kind']} order block"),
                       "ob")
    build_binary_pack("stocks", stocks_cfg, "5m", "5m", "drills-market-structure.json", "market_structure",
                       find_market_structure_scenarios_in_pack,
                       make_simple_context_fn(lambda s: f"Structure break in an existing {s['extra_fields']['trend']}trend"),
                       "ms", label_a="bos", label_b="choch")
    build_smt_pack("stocks", stocks_cfg, "5m", "5m", "drills-smt-divergence.json")
    build_kill_zone_pack(forex_cfg, "5m", "5m", "drills-kill-zones.json")


def _candles_from_df(df, has_volume):
    candles = []
    for ts, row in df.iterrows():
        activity_val = row["Volume"] if has_volume else row["ATR"]
        candles.append({
            "time": int(ts.timestamp()),
            "open": round(float(row["Open"]), 6),
            "high": round(float(row["High"]), 6),
            "low": round(float(row["Low"]), 6),
            "close": round(float(row["Close"]), 6),
            "volume": int(activity_val) if has_volume and not pd.isna(activity_val) else (round(float(activity_val), 6) if not has_volume and not pd.isna(activity_val) else 0),
        })
    return candles


def build_candle_payload(b, has_volume):
    candles = _candles_from_df(b["chart_df"], has_volume)
    playout_candles = _candles_from_df(b["playout_df"], has_volume)
    vwap_series = b["vwap_series"]
    vwap = [{"time": int(ts.timestamp()), "value": round(float(v), 6)} for ts, v in vwap_series.items() if not pd.isna(v)]
    return candles, playout_candles, vwap


def build_pack(pack_key, pack_cfg, timeframe, interval, output_file):
    print(f"\n=== PACK: {pack_cfg['label']} ({timeframe}) ===")
    all_breakouts = []
    skipped_symbols = []
    # Bar-count windows stay fixed across timeframes on purpose: at 15m each
    # window covers 3x the wall-clock time of 5m ("longer lookback"), and the
    # coarser bars surface a different, complementary set of patterns from
    # the same 60 days of history.
    outcome_window_bars = pack_cfg["outcome_window_min"] // 5

    for symbol in pack_cfg["tickers"]:
        df = download_data(symbol, interval)
        if df is None:
            skipped_symbols.append((symbol, "no data returned"))
            continue
        found = find_breakouts_in_pack(df, symbol, pack_key, pack_cfg, outcome_window_bars)
        if len(found) < 4:
            print(f"    SKIP {symbol}: only {len(found)} qualifying breakouts — too thin for a balanced deck.")
            skipped_symbols.append((symbol, f"only {len(found)} breakouts found"))
            continue
        all_breakouts.extend(found)
        reals = sum(1 for b in found if b["outcome"] == "real")
        fakes = sum(1 for b in found if b["outcome"] == "fake")
        print(f"    {symbol}: {len(found)} breakouts -> {reals} real / {fakes} fake")

    if skipped_symbols:
        print(f"  Skipped symbols in {pack_key}: " + ", ".join(f"{s} ({r})" for s, r in skipped_symbols))

    real_pool = [b for b in all_breakouts if b["outcome"] == "real"]
    fake_pool = [b for b in all_breakouts if b["outcome"] == "fake"]

    n_pair = min(len(real_pool), len(fake_pool), MAX_DECK_SIZE // 2)
    random.seed(RANDOM_SEED)
    sampled_real = random.sample(real_pool, n_pair) if len(real_pool) > n_pair else real_pool
    sampled_fake = random.sample(fake_pool, n_pair) if len(fake_pool) > n_pair else fake_pool
    deck = sampled_real + sampled_fake
    random.shuffle(deck)

    print(f"  Real pool: {len(real_pool)}  Fake pool: {len(fake_pool)}  Balanced deck: {len(deck)}")

    if len(deck) < MIN_SHIPPABLE_DECK_SIZE:
        print(f"  SKIPPING PACK '{pack_key}' ({timeframe}): deck size {len(deck)} is below the shippable floor "
              f"({MIN_SHIPPABLE_DECK_SIZE}). Not writing {output_file}.")
        return None
    if len(deck) < MIN_HEALTHY_DECK_SIZE:
        print(f"  WARNING: pack '{pack_key}' deck size {len(deck)} is below the {MIN_HEALTHY_DECK_SIZE}-drill "
              f"target (shipping anyway — still above the shippable floor).")

    records = []
    for i, b in enumerate(deck, start=1):
        drill_id = f"{pack_key}_{i:03d}"
        candles, playout_candles, vwap = build_candle_payload(b, pack_cfg["has_volume"])
        context, context_all = compute_context(b, pack_cfg)

        avg_act = b["consol_avg_activity"]
        activity_ratio = (
            round(float(b["breakout_activity"] / avg_act), 3)
            if avg_act and not math.isnan(avg_act) and avg_act > 0 else 1.0
        )

        records.append({
            "id": drill_id,
            "ticker": b["symbol"],
            "market": pack_key,
            "session": b["session"],
            "timeframe": timeframe,
            "has_volume": pack_cfg["has_volume"],
            "date": b["period_label"],
            "direction": b["direction"],
            "outcome": b["outcome"],
            "extension_multiple": b["extension_multiple"],
            "reversal_minutes": b["reversal_minutes"],
            "resolution_bar_index": b["resolution_bar_index"],
            "resolved_price": b["resolved_price"],
            "breakout_price": b["breakout_price"],
            "volume_ratio": activity_ratio,
            "context": context,
            "context_all": context_all,
            "range_high": round(float(b["range_high"]), 6),
            "range_low": round(float(b["range_low"]), 6),
            "consolidation_minutes": b["consolidation_minutes"],
            "prior_period_high": round(float(b["prior_period"]["high"]), 6) if b["prior_period"] else None,
            "prior_period_low": round(float(b["prior_period"]["low"]), 6) if b["prior_period"] else None,
            "breakout_time": int(b["breakout_ts"].timestamp()),
            "candles": candles,
            "playout_candles": playout_candles,
            "vwap": vwap,
        })

    out_path = os.path.join(DRILLS_DIR, output_file)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)

    total = len(records)
    reals = sum(1 for r in records if r["outcome"] == "real")
    fakes = sum(1 for r in records if r["outcome"] == "fake")
    print(f"\n  --- {pack_cfg['label']} deck composition ({out_path}) ---")
    print(f"  Total: {total} (real={reals}, fake={fakes})")
    for symbol in pack_cfg["tickers"]:
        t_records = [r for r in records if r["ticker"] == symbol]
        if not t_records:
            continue
        t_real = sum(1 for r in t_records if r["outcome"] == "real")
        t_fake = sum(1 for r in t_records if r["outcome"] == "fake")
        print(f"    {symbol}: {len(t_records)} drills ({t_real} real / {t_fake} fake)")
    for session_key, _, _ in pack_cfg["sessions"]:
        s_records = [r for r in records if r["session"] == session_key]
        if s_records:
            print(f"    session={session_key}: {len(s_records)} drills")

    return records


TIMEFRAMES = {
    "5m": {"interval": "5m", "filename_suffix": ""},
    "15m": {"interval": "15m", "filename_suffix": "-15m"},
}


def generate_market_packs():
    if os.path.exists(DRILLS_DIR):
        shutil.rmtree(DRILLS_DIR)
    os.makedirs(DRILLS_DIR)

    results = {}
    for pack_key, pack_cfg in MARKET_PACKS.items():
        for timeframe, tf_cfg in TIMEFRAMES.items():
            base_name, ext = os.path.splitext(pack_cfg["output_file"])
            output_file = f"{base_name}{tf_cfg['filename_suffix']}{ext}"
            results[(pack_key, timeframe)] = build_pack(
                pack_key, pack_cfg, timeframe, tf_cfg["interval"], output_file
            )

    print("\n=== SUMMARY ===")
    for (pack_key, timeframe), records in results.items():
        base_name, ext = os.path.splitext(MARKET_PACKS[pack_key]["output_file"])
        output_file = f"{base_name}{TIMEFRAMES[timeframe]['filename_suffix']}{ext}"
        if records is None:
            print(f"  {pack_key} ({timeframe}): SKIPPED (not enough data)")
        else:
            print(f"  {pack_key} ({timeframe}): {len(records)} drills -> {output_file}")


def generate_lsw_pack():
    """Additive — does not touch the existing market-pack files."""
    os.makedirs(DRILLS_DIR, exist_ok=True)
    build_lsw_pack("stocks", MARKET_PACKS["stocks"], "5m", "5m", "drills-lsw.json")


def main():
    generate_market_packs()
    generate_lsw_pack()
    generate_phase3_packs()


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "lsw":
        generate_lsw_pack()
    elif len(sys.argv) > 1 and sys.argv[1] == "phase3":
        generate_phase3_packs()
    else:
        main()
