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


def main():
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


if __name__ == "__main__":
    main()
