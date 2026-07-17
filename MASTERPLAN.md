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

## PHASE 4: The Academy — full curriculum tree — DONE
- [x] Built /academy/index.html — a vertical unit path (12 numbered nodes,
      connecting line, locked/current-pulsing/completed states) as a
      single-file SPA matching the rest of the site's no-build-step
      convention. Old /learn/, /risk/, /funded/ pages were NOT deleted —
      their prose (and risk/'s position-size calculator, ported with its
      exact formula) was absorbed into Academy units; all 3 pages stay live
      and linked from the nav. Added /academy/ as the first "Learn" dropdown
      link (desktop + mobile) across all 9 site pages, plus a nav button
      inside the game itself.
- [x] U1 Foundations — new orientation content (real data, how the drill
      loop works, chart anatomy, scoring/Ticks).
- [x] U2 Candles — ported from learn/'s candlestick section.
- [x] U3 Volume — ported from learn/'s volume section.
- [x] U4 Support/Resistance & Levels — ported from learn/'s S/R section.
- [x] U5 Breakouts & Fakeouts — ported from learn/'s breakout section, links
      the Daily Drill.
- [x] U6 VWAP & Trend — ported from learn/'s VWAP section + a new VWAP
      Pullback lesson grounded in Phase 3's research; links that Strategy
      Pack directly (?strategyPack=vwap_pullback deep link).
- [x] U7 Risk Management — ported all of risk/'s content including the exact
      calcRisk() formula/UI, re-tested live (changing account size correctly
      recomputes max shares/dollar risk).
- [x] U8 Order Types & Execution — new content (market/limit/stop/stop-limit,
      bracket/OCO), links the Order Execution Trainer (?mode=ordertrainer).
- [x] U9 Sessions & Time — new content (US session structure, FX sessions)
      plus Kill Zones using the exact honesty framing from DETECTION.md;
      links the Kill Zones pack.
- [x] U10 Smart Money Concepts — draws directly on DETECTION.md's ICT
      section, opens with the same discretionary/not-settled-science framing
      before any mechanical explanation; links Liquidity Sweep.
- [x] U11 Trading Psychology — scored scenario-style quiz questions (revenge
      trading, FOMO, overconfidence after a streak, analysis paralysis)
      instead of plain factual recall, per the plan's "interactive scored
      scenarios" requirement.
- [x] U12 Prop Firm Path — ported from funded/'s reality-check + evaluation
      content, links /funded/.
- [x] Progress UI: unit nodes with locked (greyed, lock badge) / current
      (pulsing gold ring) / completed (green, checkmark badge) states, a
      connecting path line, and a lessons-read counter per unit. Each unit:
      2-4 lessons (kept lean rather than forcing 6 where the material didn't
      need it) + a 5-question quiz (pass = 3/5, matching a friendly beginner
      bar) + a linked drill deep-link. Passing a quiz unlocks the next unit,
      awards +30 Ticks, and is tracked in a shared `academyProgress` field in
      the same localStorage blob every other page already reads/writes (so
      Ticks earned in Academy show up everywhere else immediately, verified
      live: 80 Ticks carried across an Academy session).
- [x] Verified live in-browser: full Unit 1 lesson→quiz→pass→unlock loop,
      Risk Management's calculator recomputing on input change, the SMC
      honesty framing rendering correctly, mobile 375px readability
      (path view + calculator), hamburger/dropdown nav still working on both
      Academy and a spot-checked existing page (root index.html) after the
      9-file nav edit, and the game's own new Academy nav link resolving.

## PHASE 5: Freemium Structure — DONE
- [x] Free tier: daily drill forever (unaffected), 3 practice sessions/day
      shared across classic + Long/Short/Wait (separate 3/day for Order
      Trainer rounds, since it's a per-round mode not a 10-drill session),
      Academy U1-U7, only the ORB strategy pack, leaderboard (unaffected),
      miss review capped to the most recent 20 (up to 100 still stored
      locally so full history is ready whenever Pro actually launches).
- [x] Pro tier framing (still waitlist-only — no payment processing exists,
      so every visitor is effectively "free" right now): unlimited practice
      + Order Trainer, Academy U8-U12, all 12 Strategy Packs, full miss-review
      history, 2x Ticks, AI Trade Coach (coming-first-to-Pro, not built —
      nothing to gate yet), founding price. premium/index.html's feature
      list rewritten to state the real gated numbers instead of the earlier
      placeholder copy.
- [x] Locked items show a gold PRO chip (Strategy Pack cards, Academy unit
      nodes) — tapping opens a bottom-sheet paywall (slide-up, dismissible,
      feature-specific bullet list, waitlist email capture via the existing
      tlJoinWaitlist()/Supabase waitlist table) instead of blocking outright;
      hitting a daily-session cap shows the same sheet over whatever screen
      was already visible rather than interrupting a request response.
      Never appears mid-drill — every check happens at session-start, never
      inside an active drill.
- [x] "Premium" nav item already existed pre-Phase-5 (site-wide nav, gold
      PRO tag) — left as-is, it already satisfies "subtle Pro nav tab."
- [x] Free limits keyed to getEtDateString(0) (midnight ET reset, reusing
      the same helper the Daily Drill streak already relies on) with a
      friendly live counter under the Practice button ("3 of 3 free
      sessions left today" / "0 of 3 free rounds left today" for Order
      Trainer, refreshing live when the Drill Style pill changes).
- [x] Verified live in-browser: hitting the 3-session cap shows the
      practice paywall over the still-visible start screen; a separate
      Order Trainer cap triggers its own paywall and doesn't share credits
      with practice; tapping a non-ORB Strategy Pack or a Pro-only Academy
      unit shows the correct feature-specific paywall while ORB and U1-U7
      stay fully playable; miss-review button label correctly shows "20 of
      25" once more than 20 misses exist; Daily Drill and LSW mode both
      regression-checked as unaffected/still-gated-correctly; paywall sheet
      readable at 375px mobile width.

## PHASE 6: Polish + Integrity Pass — DONE
- [x] Copy pass on free-tier surfaces: fixed the one real jargon gap found
      (LSW's "Mid-range chop" fallback label → "Sitting mid-range, no clear
      edge"). The rest of the free-tier copy (Daily/Classic/LSW/ORB/Academy
      U1-U7) was already written plain-language-first during Phases 1-5, so
      this pass was a targeted audit rather than a rewrite — reviewed Order
      Trainer's tooltips, the ORB pack description, and range/coach-card
      labels; nothing else unexplained found on a free-tier surface.
- [x] Built /about/ — covers how drills are generated (real historical data,
      DETECTION.md's mechanical rules, conventions vs. laws-of-markets
      honesty), what "correct" means for every single mode/pack family,
      explicit sample-size honesty (real numbers: ~60 days x a handful of
      tickers = dozens-to-a-couple-hundred qualifying examples per pack, not
      thousands), the same SMC honesty note as the strategy pack/Academy
      unit, and the standing "educational, not financial advice" disclaimer.
      Linked from every page's nav (added to the "Learn" dropdown across all
      10 site pages), plus a direct "Read our full methodology" link on both
      the Strategy Pack picker's ICT banner and the Academy SMC unit's first
      lesson (the two surfaces the plan specifically calls out).
- [x] Full user-journey verification, done with truly cleared localStorage
      (not reused test state): onboarding quiz → experience/market
      personalization → "Your plan is ready" → quick tutorial → Daily Drill
      → answered → dailyPlayStreak correctly became 1. Free-tier limit →
      paywall → waitlist-form path and Pro-locked-strategy-tap → preview
      sheet were both verified during Phase 5's own testing and re-spot-
      checked here; zero console errors across the whole chain.
- [x] Mobile sweep at exactly 390px: start screen, volume profile toggled
      on (POC/value-area rendering correctly on the price pane), Academy
      path + lesson + calculator, Strategy Pack drill + picker, Order
      Trainer, paywall sheet. Order Trainer's line-dragging already uses
      the Pointer Events API (pointerdown/pointermove/pointerup), which is
      the correct cross-device standard covering both mouse and touch
      inputs identically — verified the underlying drag logic directly via
      dispatched PointerEvents earlier in Phase 2 since this sandbox's
      browser automation can't simulate a real touchscreen. Zero console
      errors on every surface checked.
- [x] This file's checkboxes updated; final commit + push.

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
