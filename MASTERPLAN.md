# Trade Lee — Master Build Plan: "The Complete Day-Trading Trainer"

This file is the persistent source of truth for this build. Any session
(including a fresh one with no memory of prior conversations) should:
1. Read this file first.
2. Find the first unchecked phase and resume there.
3. Verify + commit + push after EVERY phase (never batch multiple phases into one commit).
4. Never regress existing features: daily drill, accounts/auth, global leaderboard,
   power-ups economy, Speed Run, Challenge a Friend, adaptive timer, market packs
   (stocks/futures/forex/crypto), the customize-drills selector, the onboarding quiz,
   professional hooks (ticker/greeting/nudges/miss-review).
5. For every trading concept, verify definitions against multiple reputable sources
   via web search before writing lesson content or detection logic. Where a concept
   is discretionary/contested (especially ICT/SMC), say so honestly — no guru-worship
   language, ever.

Status legend: `[ ]` not started · `[~]` in progress · `[x]` done and verified+pushed.

---

## PHASE 1: Chart Engine Upgrade — DONE
- [x] Bigger/clearer candles: barSpacing 9 (was default ~6), replaced fitContent()
      with scrollToRealTime() so more candles doesn't shrink bar width; chart
      height 60vh (58vh <400px), up from 50vh/46vh.
- [x] Extend each drill's candle array to at least 60 candles before the decision
      point — generate_drills.py now slices MIN_CONTEXT_BARS=60 from the full
      continuous series (can reach back before the session boundary); all 8
      pack/timeframe files regenerated (avg ~60 candles/drill, 1 edge-case
      shortfall out of 480 total drills where <60 bars of history existed).
- [x] Volume profile: horizontal histogram on the right of the price pane (24
      buckets from visible candles), Value Area (70%) shaded gold, POC line +
      VAH/VAL dotted lines, labeled. Works off the has_volume/activity field for
      forex too.
- [x] Chart-settings gear (top-left of chart): toggles volume profile (default
      OFF), VWAP (default ON), volume pane (default ON, collapses pane height to
      0 rather than just hiding the series). Persisted to localStorage +
      Supabase (stats.chart_settings jsonb, migration:
      supabase/phase1-chart-settings-schema.sql).
- [x] Verified at 390px (profile on/off) and 1280px desktop; daily/practice/speed
      run/challenge all regression-checked with the new chart code, zero console
      errors.

## PHASE 2: Decision Modes — beyond real/fake — DONE
- [x] Mode framework + "Drill style" selector (Classic/Long-Short-Wait/Order
      Trainer pills) on the practice customize panel; Market/Session/Timeframe
      groups stay visible for Classic + Order Trainer, hidden for LSW (its own
      dedicated stocks-only deck).
- [x] CLASSIC: existing real breakout/fakeout, unchanged.
- [x] LONG / SHORT / WAIT mode: generate_drills.py's find_lsw_scenarios_in_pack()
      detects 3 scenario sub-types (VWAP pullback, prior-period test, mid-range
      chop) sharing a 0.75x-reference-range resolution rule; WAIT is correct when
      price fails to move that much either direction within the window. New
      drills-lsw.json (60 stocks/5m drills, 21 long/21 short/18 wait — ~30% wait
      as required). 15s decision timer, own P&L (WAIT correct=+$20/-$15, else
      scaled to 0.75x range), own stats (lswStats), Ticks on session completion.
- [x] Order Execution Trainer mode: renderOrderTrainerShell() draws 3 pointer-events
      draggable lines (entry/stop/target) over the classic breakout chart, synced
      to the price scale every playout tick via priceToCoordinate/coordinateToPrice;
      order-ticket panel with direction (LONG/SHORT) and order-type
      (MARKET/LIMIT/STOP/STOP-LIMIT, each with a plain-language tooltip) pills.
      runOrderTrainerFill() simulates honest fill mechanics per type (limits can
      miss entirely, stop-limits can fail to fill if price gaps past the limit)
      and scores filled trades on R-multiple (reward/risk); validateOtOrder()
      rejects illogical brackets (e.g. a long's stop above its entry) before
      submission. Reuses the classic breakout dataset via resolvePracticePool()
      so it respects the Market/Session/Timeframe pickers.
- [x] Each mode tracks its own stats (lswStats, orderTrainerStats), MAX-merged
      into Supabase on sign-in/sync (migrations: phase2-decision-modes-schema.sql,
      phase2-order-trainer-schema.sql). Daily drill stays CLASSIC only.
- [x] Verified live in-browser: LSW full 10-drill session incl. a WAIT-correct
      scenario; Order Trainer market fill+loss, limit no-fill, short+target-hit
      win (R-multiple math checked by hand), invalid-bracket validation error,
      direction/order-type selection persisting correctly across rounds, 375px
      mobile layout. Caught and fixed two real bugs found only through this live
      testing: (1) LSW's timer/timeout fell through to the generic 10s duration
      and skipped the WHY card on timeout instead of dispatching to
      advanceOrEndLsw(); (2) the practice-button label and the Order Trainer
      direction pills' "active" class were hardcoded at render time instead of
      reading appState.drillStyle/otDirection, so switching styles or completing
      a round didn't visually update them. Also added the Ticks award LSW's
      session-end screen was missing (classic practice awards 25; LSW now does
      too), for parity with the rest of the app's power-ups economy.

## PHASE 3: Strategy Packs — including ICT/SMC — DONE
- [x] DETECTION.md created documenting all 12 packs' detection rules in plain,
      auditable terms, grounded in web research (3 parallel research passes —
      classical TA, ICT/SMC with honesty caveats, and a final verification —
      sources listed at the bottom of DETECTION.md).
- [x] ORB (Opening Range Breakout): first-3-bars (15min) range, reuses the
      Classic breakout detector's compute_outcome() for the close-beyond-range
      resolution. drills-orb.json, 60 drills.
- [x] VWAP Pullback: trend-then-touch-VWAP setup, hold/fail via a new shared
      resolve_hold_fail() helper. drills-vwap-pullback.json, 60 drills.
- [x] ICT / Smart Money Concepts pack (research via 1 dedicated web-research
      pass with explicit instructions to find skeptical/independent sources,
      not just ICT-affiliated ones):
  - [x] Liquidity Sweep / Stop Hunt: swing-pivot wick-pierce-then-close-back
        detection, judged sweep vs breakout. drills-liquidity-sweep.json, 42.
  - [x] Fair Value Gap (FVG): standard 3-candle gap definition, fill/no-fill
        via a direct wick-touch forward scan. drills-fvg.json, 60 drills.
  - [x] Order Block: last-opposing-candle-before-displacement, retest hold/fail.
        drills-order-blocks.json, 60 drills.
  - [x] Market Structure: BOS vs CHoCH via swing-high/low sequence tracking,
        scanned over the full regular session (fragmented open/midday/power_hour
        windows didn't give trends enough room to establish — a bug caught by
        the first generation run producing only 16 total scenarios; fixed by
        switching to a single 9:30-16:00 window, jumped to 60). drills-market-structure.json.
  - [x] SMT Divergence: QQQ vs SPY swing-point comparison; drill renders SPY as
        a second line series on the chart's left price scale (own auto-scaled
        axis, for visual divergence comparison) alongside QQQ's candles.
        drills-smt-divergence.json, 18 drills (this pack is inherently data-
        thin — only ~21 qualifying divergence instances existed across 60 days
        of QQQ vs SPY 5-min bars).
  - [x] Kill Zones: London (2-5am ET) / New York (7-10am ET) / Neither,
        3-way timestamp classification quiz — built from forex EUR/USD data
        specifically, since the stocks pack's regular-hours-only data barely
        overlaps these windows at all. drills-kill-zones.json, 60 drills.
  - [x] Strategy picker screen states plainly, above the ICT section, that SMC
        is a discretionary framework not settled science, that it overlaps
        classical TA under new names, and that no independent study confirms a
        standalone edge — no guru-worship language, no track-record claims.
        Same honesty framing repeated in DETECTION.md's ICT section intro.
- [x] Classical packs: Supply & Demand (base-then-departure zone, retest
      hold/fail), Trend Pullback (EMA9/20 bounce, trend + touch + hold-below-
      EMA20 required), Mean Reversion (fade trigger at 2x ATR from VWAP, hold
      = reverts to 1x ATR, fail = extends to 3x ATR), Range Trading (12-bar
      tight-range detection, boundary touch, hold = bounces / fail = breaks).
      All at drills-supply-demand.json / drills-trend-pullback.json /
      drills-mean-reversion.json / drills-range-trading.json, 60 drills each.
- [x] Strategy picker screen (🎯 Strategy Packs, reachable from the start
      screen) lists all 12 packs grouped Classical / ICT, each launching a
      10-drill session through the existing decision-mode framework (new
      generic "strategy_pack" mode in play/index.html, sharing loadDrill/
      startPlayout/finishPlayout/showCoachCard machinery with Classic/LSW —
      every record gets a range_high/range_low fallback in Python so the
      shared chart-zone UI never breaks on packs without a natural zone
      concept). Locked/unlocked state deferred to Phase 5 as planned — every
      pack is currently unlocked since the free/Pro gate doesn't exist yet.
- [x] Own stats (strategyPackStats), synced to cloud in aggregate (not broken
      out per individual pack — matches how "practice" mode has one set of
      stats across all its market/session/timeframe combinations), migration:
      phase3-strategy-packs-schema.sql.
- [x] Verified live in-browser: ORB (full 10-drill session incl. P&L/Ticks/
      session-end), SMT (dual-line overlay renders correctly), Kill Zones
      (3-button variant, correct timestamp judged against real ET), Market
      Structure (2-button bos/choch), Fair Value Gap at 375px mobile width;
      Daily Drill / Practice / Speed Run regression-checked afterward (no
      console errors). Caught and fixed two real bugs during this testing:
      (1) generate_drills.py was calling download_data() once per pack instead
      of once per symbol (10x redundant network calls, which was also tripping
      intermittent yfinance rate-limit flakiness — fixed with a run-scoped
      cache); (2) the volume pane silently collapses to 0 height and stops
      responding to setHeight() once a second (left) price scale exists on the
      chart, which only SMT Divergence's compare-line uses — worked around by
      leaving the pane at whatever height initChart() gave it for that one
      pack rather than fighting the charting library, a known minor scope
      limit worth revisiting later rather than a blocker.

## PHASE 4: The Academy — full curriculum tree
- [ ] Build /academy/ — Duolingo-style vertical unit path, mobile-first, replacing
      the flat /learn/ page (old lesson content absorbed into units, not deleted)
- [ ] U1 Foundations
- [ ] U2 Candles
- [ ] U3 Volume (ties to Phase 1's volume profile)
- [ ] U4 Support/Resistance & Levels
- [ ] U5 Breakouts & Fakeouts (links the core game)
- [ ] U6 VWAP & Trend
- [ ] U7 Risk Management (absorbs /risk/ content + position-size calculator)
- [ ] U8 Order Types & Execution (quiz + Phase 2's order-execution trainer as drill)
- [ ] U9 Sessions & Time (premarket/open/lunch/power hour, FX sessions, kill zones)
- [ ] U10 Smart Money Concepts (Phase 3 ICT content, honesty framing intact)
- [ ] U11 Trading Psychology (interactive scored scenarios)
- [ ] U12 Prop Firm Path (links /funded/)
- [ ] Progress UI: unit bubbles, progress rings, locked/greyed, current unit
      pulsing; badges tie into existing tiers; 3-6 lessons + 5-question quiz +
      linked drill set per unit; unlocks next unit; XP + Ticks rewards; synced

## PHASE 5: Freemium Structure
- [ ] Free tier locked in as genuinely great: daily drill forever, 3 practice
      sessions/day (any unlocked mode), Academy U1-U7, classic + long/short/wait
      modes, leaderboard, miss review (last 20)
- [ ] Pro tier definition ($9/mo, waitlist only, no payment processing): unlimited
      practice, Academy U8-U12, all strategy packs (free = Breakout core + ORB),
      unlimited order-execution trainer (free = 3/day), full miss-review history +
      per-pattern edge analytics, 2x Ticks, AI Trade Coach (coming-first-to-Pro),
      founding-price lock
- [ ] Locked items show a gold PRO chip; tapping opens a bottom-sheet paywall
      preview (feature list + waitlist email capture to existing Supabase table) —
      never a hard interruption, never mid-drill
- [ ] Subtle "Pro" nav tab
- [ ] Free limits reset midnight ET with a friendly counter ("2 of 3 sessions left
      today")

## PHASE 6: Polish + Integrity Pass
- [ ] Every lesson/drill copy proofread at a beginner reading level; zero
      unexplained jargon on free-tier surfaces
- [ ] /about/ methodology page: how drills are generated, what "correct" means per
      mode, sample-size honesty, standing disclaimer surfaced on Academy + strategy
      pages
- [ ] Full user-journey verification (new user onboarding→U1→drill→streak; free
      user hits session limit→paywall sheet→waitlist; Pro-locked strategy
      tap→preview sheet)
- [ ] Full mobile sweep at 390px: Academy, order trainer (touch line-dragging),
      volume profile, all new modes. Zero console errors.
- [ ] Update this file's checkboxes; final commit + push

---

## Notes for resuming sessions
- Repo root: this file. Game lives in `play/index.html` (huge single-file SPA).
  Data pipeline: `generate_drills.py` → `drills/*.json` (per market pack + timeframe).
  Shared: `theme.css`, `auth.js` (Supabase), `social-links.js`.
- Supabase migrations live in `supabase/*.sql` — each must be run manually by the
  user in the SQL Editor (I only ever hold the anon/publishable key, never
  service_role or the DB password — cannot run migrations myself).
- Existing SQL migrations already applied as of this plan's creation: Stage B
  (accounts/leaderboard), Stage C (waitlist), Stage D (speed run), Phase 2.5 Stage 1
  (challenges), Major-Upgrade Stage 2 (adaptive timer), Stage 5 (onboarding
  profile), Stage 6 (hooks/total-drills RPC).
- Recurring local-dev gotcha: the Python dev server / browser can serve stale
  cached JS/HTML during testing. `serve.py` now sends `Cache-Control: no-store`,
  but an already-open long-lived browser tab may still need a hard reload or a
  cache-busted query string to pick up fresh files mid-session.
