# Trade Lee — Detection Rules

Plain-language, auditable documentation of exactly how every strategy-pack
drill in Trade Lee is generated from real OHLCV candle data. If you can read
Python, `generate_drills.py` is the ground truth; this file exists so you
don't have to — every rule below is the rule the code actually runs, not an
aspirational description.

All packs in this file are generated from the **stocks 5-minute dataset**
(QQQ/SPY/IWM/DIA) only, for now — same scoping as the Phase 2 Long/Short/Wait
pack. Multi-market versions may follow later.

Every detector shares two conventions from the original breakout detector:
- The visible chart always shows **at least 60 candles** before the decision
  point (`MIN_CONTEXT_BARS`), pulled from the continuous series even if that
  reaches back before the current session's own window.
- "Session" = one calendar occurrence of a named intraday window (e.g. the
  9:30–11:00 ET "open" session), the same session-splitting used everywhere
  else in the app.

---

## Classical packs

### Opening Range Breakout (ORB)
- **Opening range** = the high/low of the first **3 five-minute bars** of the
  day's "open" session (9:30–9:45 ET). This is the most common convention
  (5/15/30-minute variants all exist; we use 15 minutes as the widely-cited
  "balanced" choice).
- **Breakout** = a later candle's **close** beyond the opening-range high
  (long) or low (short). A wick alone that closes back inside does not count
  — this close-based rule is the one detail nearly every source agrees on.
- **Outcome**: reuses the same real/fake resolution as the Classic breakout
  drill — "real" if price later reaches 1x the opening range's height beyond
  the break level; "fake" if price closes back inside the range first.
- **Honest caveat**: there's no universal standard for window length or for
  "close beyond" vs. "touch" — this is a documented convention choice, not an
  industry-wide fixed rule. Failed-breakout-then-reversal is a well-known,
  common failure mode, not a rare edge case.

### VWAP Pullback
- **VWAP** = session-cumulative volume-weighted average price, reset at the
  start of each session (same VWAP already drawn on every chart).
- **Setup**: price sits clearly on one side of VWAP (>2.5x its own eventual
  approach distance) for several bars, then closes within 0.15% of VWAP —
  the "pullback."
- **Hold vs. fail**: within the following window, HOLD = price extends
  beyond its pre-pullback extreme in the original trend direction; FAIL =
  price closes through VWAP on the opposite side by a comparable amount.
- **Honest caveat**: no source gives one universal numeric "how close counts
  as touching VWAP" — some traders use standard-deviation bands instead of
  the raw line. Our 0.15% proximity and the hold/fail thresholds below are a
  documented convention, not a universal standard.

### Supply & Demand Zones
- **Base**: 4 consecutive bars whose combined range is tight relative to
  recent volatility (below the 35th percentile of recent 45-minute ranges —
  the same tightness test the Classic breakout detector uses).
- **Departure**: the base is immediately followed by a strong directional
  candle (range ≥ 1.5x the 14-bar ATR) moving away from the base — that base
  becomes the zone (demand zone below an up-move, supply zone above a
  down-move).
- **Retest hold vs. fail**: the first time price returns into the zone, HOLD
  = price reverses away again in the original departure direction; FAIL =
  a candle closes through the zone's far edge.
- **Honest caveat**: zone boundaries are a convention choice (base width,
  breakout-candle strength) — different traders draw different boxes on the
  same chart. Zones are commonly treated as weaker after each retest; this
  detector only ever tests the *first* retest.

### Trend Pullback (EMA9 / EMA20)
- **Trend filter**: EMA9 above EMA20 and both rising over the last 6 bars =
  uptrend context (mirrored for downtrends).
- **Pullback**: price closes within a small tolerance of EMA9 without
  closing below EMA20.
- **Hold vs. fail**: HOLD = price later makes a new high beyond the
  pre-pullback high (continuation); FAIL = a candle closes below EMA20
  (trend-failure signal).
- **Honest caveat**: EMA9/20 is one popular convention among many
  moving-average pairs; whipsaws are common in choppy, non-trending stretches
  where the EMAs repeatedly cross without a sustained trend.

### Mean Reversion (fade >2x ATR from VWAP)
- **ATR**: 14-bar Wilder Average True Range (already computed for every
  candle in the pipeline).
- **Trigger**: price's distance from VWAP reaches ≥ 2x ATR — "extended."
- **Fade hold vs. fail**: HOLD (the fade works) = price reverts back to
  within 1x ATR of VWAP; FAIL = price extends even further away (≥ 3x ATR)
  before reverting.
- **Honest caveat**: this setup assumes range-bound conditions — on genuine
  trend days price can stay extended from VWAP far longer than 2x ATR, which
  is exactly when fading is most dangerous. The 2x/3x ATR thresholds are a
  documented convention, not a law of markets.

### Range Trading
- **Range**: a 12-bar window whose height sits in the bottom 30th percentile
  of recent 45-minute ranges (a calmer, longer version of the same tightness
  test used elsewhere), with the range's own high/low touched at least twice
  each.
- **Setup**: price approaches within 0.2% of either range boundary.
- **Hold vs. fail**: HOLD = price bounces back toward the opposite boundary;
  FAIL = a candle closes beyond the boundary (the range is breaking).
- **Honest caveat**: no fixed number of touches makes a range "official," and
  a range silently turning into pre-trend consolidation is only obvious in
  hindsight — this detector cannot distinguish the two in advance, and
  neither can a human trader in real time.

---

## ICT / Smart Money Concepts (SMC) pack

**Read this before the lesson content, not after:** Smart Money Concepts is a
**discretionary trading framework, not settled or independently validated
science**. Every concept below has a precise-sounding mechanical definition
here because we had to pick *one* convention to make a drill out of it — but
in live trading, identifying "the" relevant swing point, candle, or zone is
genuinely subjective, and two experienced SMC traders can mark the same chart
differently. Independent research consistently finds that SMC concepts map
closely onto older, classical technical-analysis ideas under new names (Dow
Theory for market structure, Market Profile's low-volume nodes for Fair
Value Gaps, and plain supply/demand teaching for order blocks), and that no
peer-reviewed or independently reproduced study confirms a standalone
statistical edge for any of them. We teach it because a huge number of
retail traders encounter this vocabulary and deserve an honest, mechanical
explanation of what it actually claims — not because the underlying claims
about "smart money" intent are proven. No guru-worship here: nobody's track
record is cited as evidence, because track records aren't evidence.

### Liquidity Sweep / Stop Hunt
- **Definition**: a prior swing high/low (a 5-bar local pivot) is pierced
  intrabar (wick) but the piercing candle **closes back on the original
  side**. That's the whole mechanical difference from a real breakout, which
  closes through and stays through.
- **Judged as**: "Sweep" (reverses away from the level afterward) vs.
  "Breakout" (a later candle in the window does close through after all).
- **Honest caveat**: the "stops cluster there and get run deliberately"
  story is not independently verified — what's real and well-studied is that
  stop orders cluster near obvious levels and can cause brief price
  cascades; the "smart money did this on purpose" framing is a narrative
  layered on top of that real, older observation.

### Fair Value Gap (FVG)
- **Definition**: three consecutive candles where candle 1's high sits below
  candle 3's low (bullish gap) or candle 1's low sits above candle 3's high
  (bearish gap). The gap box is the space between those two prices.
- **Judged as**: "Fill" (price later trades back into the box) vs. "No-Fill"
  (it never does, within the window).
- **Honest caveat**: whether "fill" means any wick touch or a full close
  through the box is not standardized — that single definition choice
  swings reported win rates significantly in public backtests. We use the
  wick-touch definition (the more common one) and say so.

### Order Blocks
- **Definition**: the last opposing-color candle immediately before a
  displacement move (a candle with range ≥ 1.5x the 14-bar ATR). A bullish
  order block is the last down-candle before a sharp rally.
- **Judged as**: on the first retest of that candle's range, "Hold"
  (reverses away again, continuing the original move) vs. "Fail" (a candle
  closes through it).
- **Honest caveat**: mechanically this is the same shape as our classical
  Supply & Demand detector above, just anchored to a single candle instead
  of a multi-bar base — independent commentary treats "order block" largely
  as a rebrand of decades-older supply/demand teaching.

### Market Structure — BOS vs. CHoCH
- **Definition**: track alternating swing highs/lows (5-bar local pivots).
  In an established uptrend, a close above the last swing high is a
  **Break of Structure (BOS)** — continuation. A close below the last swing
  *low* against the trend is a **Change of Character (CHoCH)** — the first
  structural evidence the trend may be flipping.
- **Judged as**: a straight two-choice "BOS or CHoCH?" quiz at the break bar
  — this one isn't predicting the future, it's pattern recognition against
  an objective rule.
- **Honest caveat**: this is mechanically identical to Dow Theory's century-
  old definition of a trend (higher highs/higher lows) and trend change
  (failure to make one). The swing-pivot lookback is a parameter choice —
  shorter lookbacks find "structure breaks" much more often, so what counts
  as market structure is timeframe-dependent, not objective, in real use.

### SMT Divergence
- **Definition**: compares QQQ against SPY (both already in our stocks
  pack, tightly correlated) at matched timestamps. Bearish SMT = QQQ prints
  a new swing high while SPY fails to exceed its own prior swing high in the
  same window (or the mirror image at swing lows for bullish SMT).
- **Judged as**: does the divergence resolve — does the leading instrument
  (QQQ) reverse back below its prior swing level within the window ("SMT
  confirmed") or push on to a genuine new extreme ("SMT failed")? Shown as
  two synced price lines on one chart (QQQ candles, SPY overlaid on its own
  scale) so the divergence is visible directly.
- **Honest caveat**: this only means anything if the two instruments are
  actually correlated at the time — correlation regimes shift, and this
  detector doesn't check for that, matching how the concept is used (or
  misused) in practice.

### Kill Zones
- **Definition** (times are a convention — sources vary by up to an hour):
  **London Kill Zone = 2:00–5:00 AM ET**, **New York Kill Zone = 7:00–10:00
  AM ET**. A candle's timestamp (already stored in ET) is checked against
  these two windows.
- **Judged as**: a quick multiple-choice quiz — "London / New York /
  Neither?" — against the candle's real timestamp. No prediction involved.
- **Honest caveat**: ICT-aligned sources themselves don't agree on the exact
  boundaries (some cite 2–4 AM for London, others 8:30–11 AM for New York).
  The only well-established fact underneath this is the much older, general
  observation that session opens/overlaps see more volume — the specific
  hour boundaries are heuristics, not derived from data.

---

## Sources consulted

- [Opening Range Breakout Strategy — FTMO x OANDA](https://ftmo.oanda.com/blog/opening-range-breakout-strategy-how-to-master-the-1530-us-session/) · [False Breakouts — ORB Setups](https://orbsetups.com/doc/false-breakouts/)
- [VWAP — StockCharts ChartSchool](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/volume-weighted-average-price-vwap) · [VWAP Pullback Strategy — FTMO](https://ftmo.com/en/blog/the-vwap-pullback-strategy-trade-with-volume-not-emotion/)
- [Supply and Demand vs. Support and Resistance — The5ers](https://the5ers.com/difference-between-supply-and-demand-and-support-resistance/)
- [Understanding Moving Averages — CME Group](https://www.cmegroup.com/education/courses/technical-analysis/understanding-moving-averages)
- [Average True Range (ATR) — StockCharts ChartSchool](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/average-true-range-atr) · [Mean reversion (finance) — Wikipedia](https://en.wikipedia.org/wiki/Mean_reversion_(finance))
- [Sideways Markets Explained — Investopedia](https://www.investopedia.com/terms/s/sidewaysmarket.asp) · [Support and Resistance — CME Group](https://www.cmegroup.com/education/courses/technical-analysis/support-and-resistance)
- [Liquidity Sweep Explained — liquidityscan.io](https://liquidityscan.io/blog/liquidity-sweep-explained-the-ict-stop-hunt) · Osler, ["Stop-Loss Orders and Price Cascades in Currency Markets" — NY Fed](https://www.newyorkfed.org/medialibrary/media/research/staff_reports/sr150.pdf)
- [Valid ICT Fair Value Gap — Inner Circle Trader](https://innercircletrader.net/tutorials/valid-ict-fair-value-gap/) · [The Illusion of Edge: SMC, Survivorship Bias, and Market Reality](https://wire.insiderfinance.io/the-illusion-of-edge-smc-survivorship-bias-and-market-reality-ae7873ef154d)
- [ICT Order Block Explained](https://innercircletrader.net/tutorials/ict-order-block/) · [Is ICT Trading Legit? — critical overview](https://phidiaspropfirm.com/education/is-ict-legit)
- [BOS vs CHOCH — Inner Circle Trader](https://innercircletrader.net/tutorials/break-of-structure-vs-change-of-character/)
- [ICT SMT Divergence Explained](https://innercircletrader.net/tutorials/ict-smt-divergence-smart-money-technique/) · [Intermarket Analysis — StockCharts ChartSchool](https://chartschool.stockcharts.com/table-of-contents/market-analysis/intermarket-analysis)
- [ICT Killzones — Inner Circle Trader](https://innercircletrader.net/tutorials/master-ict-kill-zones/) · [The downfall of ICT — BabyPips forum discussion](https://forums.babypips.com/t/the-downfall-of-ict-inner-circle-trader/834125)
