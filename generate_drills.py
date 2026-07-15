"""
Trade Lee - Phase 0 drill generator.

Downloads 5-minute intraday data for QQQ, SPY, and IWM, scans for ANY
consolidation-then-breakout pattern during the trading session (not just the
opening range), labels each as a real breakout or a fakeout, builds a
balanced deck, computes per-drill context notes, and saves drills.json for
the quiz app (lightweight-charts renders the candles client-side).
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
TICKERS = ["QQQ", "SPY", "IWM"]

SESSION_START = "09:30"
SESSION_END = "16:00"
BREAKOUT_WINDOW_END = "15:00"  # last time a breakout candle may occur

CONSOLIDATION_BARS = 9      # 45 minutes of 5-min bars
TIGHTNESS_PERCENTILE = 35   # window must be tighter than this pct of the day's own 45-min ranges
COOLDOWN_BARS = 12          # after a detected breakout, skip 60 min before scanning again
OUTCOME_WINDOW_BARS = 12    # evaluate the next 60 minutes for real-vs-fake
EXTENSION_MULTIPLE = 1.0    # "real breakout" = price extends >= 1x range height

PRIOR_DAY_PROXIMITY_PCT = 0.0025  # 0.25%
RANDOM_SEED = 42
MAX_DECK_SIZE = 60


def download_data(ticker):
    print(f"Downloading 5m data for {ticker}...")
    df = yf.download(
        ticker,
        period="60d",
        interval="5m",
        prepost=False,
        auto_adjust=False,
        progress=False,
    )
    if df.empty:
        print(f"  WARNING: no data returned for {ticker}, skipping.")
        return None

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    df.index = df.index.tz_convert("America/New_York")

    return df


def compute_outcome(direction, range_high, range_low, range_height, breakout_idx, day_regular, j):
    """
    Walk forward up to OUTCOME_WINDOW_BARS candles after the breakout candle (index j).
    'fake'  = a candle CLOSES back inside the range before the extension target is hit.
    'real'  = price reaches 1x range height beyond the broken level, without first
              closing back inside the range.
    If neither happens within the window, default to 'fake' (didn't convincingly follow through).

    Returns: outcome, extension_multiple, reversal_minutes, resolution_bar_index, resolved_price
    resolution_bar_index is 0-based into the playout window (k - j - 1); None if it never resolved.
    """
    n = len(day_regular)
    highs = day_regular["High"].values
    lows = day_regular["Low"].values
    closes = day_regular["Close"].values
    times = day_regular.index

    if direction == "long":
        target_level = range_high + EXTENSION_MULTIPLE * range_height
    else:
        target_level = range_low - EXTENSION_MULTIPLE * range_height

    forward_end = min(j + OUTCOME_WINDOW_BARS, n - 1)
    for k in range(j + 1, forward_end + 1):
        bar_index = k - j - 1
        if direction == "long":
            if closes[k] < range_high:
                minutes = int((times[k] - breakout_idx).total_seconds() // 60)
                return "fake", None, minutes, bar_index, None
            if highs[k] >= target_level:
                multiple = round((highs[k] - range_high) / range_height, 2)
                return "real", multiple, None, bar_index, round(float(highs[k]), 4)
        else:
            if closes[k] > range_low:
                minutes = int((times[k] - breakout_idx).total_seconds() // 60)
                return "fake", None, minutes, bar_index, None
            if lows[k] <= target_level:
                multiple = round((range_low - lows[k]) / range_height, 2)
                return "real", multiple, None, bar_index, round(float(lows[k]), 4)

    return "fake", None, None, None, None  # fizzled: never resolved either way within the window


def find_breakouts(df, ticker):
    breakouts = []
    dates = sorted(set(df.index.date))

    for day_i, day in enumerate(dates):
        day_df = df[df.index.date == day]
        day_regular = day_df.between_time(SESSION_START, SESSION_END, inclusive="left")
        n = len(day_regular)
        if n < CONSOLIDATION_BARS + 1:
            continue

        highs = day_regular["High"].values
        lows = day_regular["Low"].values
        closes = day_regular["Close"].values
        volumes = day_regular["Volume"].values
        times = day_regular.index

        rolling_range = np.full(n, np.nan)
        for i in range(CONSOLIDATION_BARS - 1, n):
            window_hi = highs[i - CONSOLIDATION_BARS + 1: i + 1].max()
            window_lo = lows[i - CONSOLIDATION_BARS + 1: i + 1].min()
            rolling_range[i] = window_hi - window_lo

        valid_ranges = rolling_range[~np.isnan(rolling_range)]
        if len(valid_ranges) == 0:
            continue
        tight_threshold = np.percentile(valid_ranges, TIGHTNESS_PERCENTILE)

        prev_day_stats = None
        if day_i > 0:
            prev_df = df[df.index.date == dates[day_i - 1]]
            prev_regular = prev_df.between_time(SESSION_START, SESSION_END, inclusive="left")
            if not prev_regular.empty:
                prev_day_stats = {
                    "high": prev_regular["High"].max(),
                    "low": prev_regular["Low"].min(),
                    "close": prev_regular["Close"].iloc[-1],
                }

        j = CONSOLIDATION_BARS  # first index that could be a breakout candle
        while j < n:
            if times[j] > pd.Timestamp(f"{day} {BREAKOUT_WINDOW_END}", tz=times.tz):
                break

            i = j - 1  # last consolidation candle
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
                direction, range_high, range_low, range_height, breakout_idx, day_regular, j
            )

            consol_avg_volume = volumes[i - CONSOLIDATION_BARS + 1: i + 1].mean()
            breakout_volume = volumes[j]
            breakout_price = round(float(closes[j]), 4)

            playout_end = min(j + 1 + OUTCOME_WINDOW_BARS, n)
            vwap_end = playout_end

            typical_price = (
                day_regular["High"].iloc[:vwap_end]
                + day_regular["Low"].iloc[:vwap_end]
                + day_regular["Close"].iloc[:vwap_end]
            ) / 3
            vol_upto = day_regular["Volume"].iloc[:vwap_end]
            vwap_series = (typical_price * vol_upto).cumsum() / vol_upto.cumsum()

            chart_df = day_regular.iloc[: j + 1]
            playout_df = day_regular.iloc[j + 1: playout_end]

            breakouts.append(
                {
                    "ticker": ticker,
                    "date": str(day),
                    "direction": direction,
                    "range_high": range_high,
                    "range_low": range_low,
                    "range_height": range_height,
                    "breakout_ts": breakout_idx,
                    "breakout_price": breakout_price,
                    "outcome": outcome,
                    "extension_multiple": extension_multiple,
                    "reversal_minutes": reversal_minutes,
                    "resolution_bar_index": resolution_bar_index,
                    "resolved_price": resolved_price,
                    "consol_avg_volume": consol_avg_volume,
                    "breakout_volume": breakout_volume,
                    "vwap_series": vwap_series,
                    "chart_df": chart_df,
                    "playout_df": playout_df,
                    "prior_day": prev_day_stats,
                }
            )

            j += COOLDOWN_BARS  # avoid re-detecting the same move repeatedly

    return breakouts


def compute_context(b):
    """Human-readable, jargon-free context notes; returns (primary_line, all_notes)."""
    notes = []  # (priority_key, text)

    direction = b["direction"]
    entry = b["chart_df"]["Close"].iloc[-1]

    prior = b["prior_day"]
    if prior is not None:
        if direction == "long" and prior["high"] > 0:
            if abs(entry - prior["high"]) / prior["high"] < PRIOR_DAY_PROXIMITY_PCT:
                notes.append(("priorday", "Broke out into yesterday's high — heavy sellers there"))
        elif direction == "short" and prior["low"] > 0:
            if abs(entry - prior["low"]) / prior["low"] < PRIOR_DAY_PROXIMITY_PCT:
                notes.append(("priorday", "Broke out into yesterday's low — heavy buyers there"))

    avg_vol = b["consol_avg_volume"]
    breakout_vol = b["breakout_volume"]
    if avg_vol and not math.isnan(avg_vol) and avg_vol > 0:
        vol_ratio = breakout_vol / avg_vol
        notes.append(("volume", f"Breakout volume {vol_ratio:.1f}x the consolidation average"))

    vwap_series = b["vwap_series"]
    if not vwap_series.empty:
        vwap_at_breakout = vwap_series.iloc[-1]
        position = "above" if entry > vwap_at_breakout else "below"
        notes.append(("vwap", f"Price was {position} VWAP at the breakout"))

    priority = {"priorday": 0, "volume": 1, "vwap": 2}
    notes.sort(key=lambda n: priority.get(n[0], 99))

    primary = notes[0][1] if notes else ""
    return primary, [n[1] for n in notes]


def _candles_from_df(df):
    candles = []
    for ts, row in df.iterrows():
        candles.append(
            {
                "time": int(ts.timestamp()),
                "open": round(float(row["Open"]), 4),
                "high": round(float(row["High"]), 4),
                "low": round(float(row["Low"]), 4),
                "close": round(float(row["Close"]), 4),
                "volume": int(row["Volume"]) if not pd.isna(row["Volume"]) else 0,
            }
        )
    return candles


def build_candle_payload(b):
    candles = _candles_from_df(b["chart_df"])
    playout_candles = _candles_from_df(b["playout_df"])

    vwap_series = b["vwap_series"]
    vwap = [
        {"time": int(ts.timestamp()), "value": round(float(v), 4)}
        for ts, v in vwap_series.items()
        if not pd.isna(v)
    ]
    return candles, playout_candles, vwap


def main():
    random.seed(RANDOM_SEED)

    if os.path.exists(DRILLS_DIR):
        shutil.rmtree(DRILLS_DIR)
    os.makedirs(DRILLS_DIR)

    all_breakouts = []
    for ticker in TICKERS:
        df = download_data(ticker)
        if df is None:
            continue
        found = find_breakouts(df, ticker)
        all_breakouts.extend(found)
        reals = sum(1 for b in found if b["outcome"] == "real")
        fakes = sum(1 for b in found if b["outcome"] == "fake")
        print(f"  {ticker}: {len(found)} breakouts -> {reals} real / {fakes} fake")

    real_pool = [b for b in all_breakouts if b["outcome"] == "real"]
    fake_pool = [b for b in all_breakouts if b["outcome"] == "fake"]

    n_pair = min(len(real_pool), len(fake_pool), MAX_DECK_SIZE // 2)
    sampled_real = random.sample(real_pool, n_pair) if len(real_pool) > n_pair else real_pool
    sampled_fake = random.sample(fake_pool, n_pair) if len(fake_pool) > n_pair else fake_pool

    deck = sampled_real + sampled_fake
    random.shuffle(deck)

    print(f"\nReal-breakout pool: {len(real_pool)} across all tickers")
    print(f"Fakeout pool: {len(fake_pool)} across all tickers")
    print(f"Balanced deck size: {len(deck)} ({len(sampled_real)} real / {len(sampled_fake)} fake)")

    records = []
    for i, b in enumerate(deck, start=1):
        drill_id = f"drill_{i:03d}"
        candles, playout_candles, vwap = build_candle_payload(b)
        context, context_all = compute_context(b)

        avg_vol = b["consol_avg_volume"]
        volume_ratio = (
            round(float(b["breakout_volume"] / avg_vol), 3)
            if avg_vol and not math.isnan(avg_vol) and avg_vol > 0
            else 1.0
        )

        records.append(
            {
                "id": drill_id,
                "ticker": b["ticker"],
                "date": b["date"],
                "direction": b["direction"],
                "outcome": b["outcome"],
                "extension_multiple": b["extension_multiple"],
                "reversal_minutes": b["reversal_minutes"],
                "resolution_bar_index": b["resolution_bar_index"],
                "resolved_price": b["resolved_price"],
                "breakout_price": b["breakout_price"],
                "volume_ratio": volume_ratio,
                "context": context,
                "context_all": context_all,
                "range_high": round(float(b["range_high"]), 4),
                "range_low": round(float(b["range_low"]), 4),
                "breakout_time": int(b["breakout_ts"].timestamp()),
                "candles": candles,
                "playout_candles": playout_candles,
                "vwap": vwap,
            }
        )
        detail = f"+{b['extension_multiple']}x" if b["outcome"] == "real" else f"back in {b['reversal_minutes']}min" if b["reversal_minutes"] is not None else "fizzled"
        print(f"  {drill_id}: {b['ticker']} {b['date']} -> {b['outcome']:4s} ({detail})  [{context}]")

    with open(os.path.join(DRILLS_DIR, "drills.json"), "w") as f:
        json.dump(records, f, indent=2)

    total = len(records)
    reals = sum(1 for r in records if r["outcome"] == "real")
    fakes = sum(1 for r in records if r["outcome"] == "fake")

    print(f"\n=== FINAL DECK COMPOSITION ===")
    print(f"Total drills: {total}  (real={reals}, fake={fakes})")
    for ticker in TICKERS:
        t_records = [r for r in records if r["ticker"] == ticker]
        t_real = sum(1 for r in t_records if r["outcome"] == "real")
        t_fake = sum(1 for r in t_records if r["outcome"] == "fake")
        print(f"  {ticker}: {len(t_records)} drills ({t_real} real / {t_fake} fake)")

    if not (40 <= total <= 60):
        print(f"\nNOTE: deck size {total} is outside the 40-60 target range "
              f"(limited by how many qualifying breakouts exist in ~60 days of 5m data across these 3 tickers).")


if __name__ == "__main__":
    main()
