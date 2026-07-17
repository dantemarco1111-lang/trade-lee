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

## PHASE 2: Decision Modes — beyond real/fake
- [ ] Mode framework so a drill can ask different questions; "Drill style" selector
      on the practice screen.
- [ ] CLASSIC: existing real breakout/fakeout, unchanged.
- [ ] LONG / SHORT / WAIT mode: pauses at decision moments beyond breakouts
      (pullbacks to VWAP, prior-day level tests, mid-range chop). WAIT is correct
      when price fails to move 0.75x the reference range in either direction within
      the window. Generator labels each scenario including genuine wait-scenarios
      (~30% of the deck).
- [ ] Order Execution Trainer mode: interactive order-ticket simulator — order type
      picker (MARKET/LIMIT/STOP/STOP-LIMIT with plain-language tooltips), drag lines
      on the chart for entry/stop/take-profit (bracket/OCO explained), honest
      fill/no-fill mechanics (limits can miss, stops can gap), scored on R-multiple
      + order-logic correctness.
- [ ] Each mode tracks its own stats, synced to cloud. Daily drill stays CLASSIC only.

## PHASE 3: Strategy Packs — including ICT/SMC
- [ ] DETECTION.md created documenting every pack's detection rule in plain,
      auditable terms.
- [ ] ORB (Opening Range Breakout) gets its own detection logic + drill deck.
- [ ] VWAP Pullback gets its own detection logic + drill deck.
- [ ] ICT / Smart Money Concepts pack (research each concept via web search first):
  - [ ] Liquidity Sweep / Stop Hunt drills ("liquidity grab or real break?")
  - [ ] Fair Value Gap (FVG) detection (3-candle gap) + fill/no-fill drill
  - [ ] Order Block detection (last opposing candle before displacement) + retest
        hold/fail drill
  - [ ] Market Structure: BOS vs CHoCH drill
  - [ ] SMT Divergence: side-by-side correlated-pair mini-charts drill
  - [ ] Kill Zones taught in the lesson (London 2-5am ET, NY 7-10am ET); ICT drills
        tagged with their kill zone
  - [ ] ICT lesson page explicitly states SMC is a discretionary framework, not
        settled science, overlapping classical S/R and liquidity ideas; shows the
        pack's actual historical follow-through stats from our own sample
- [ ] Classical packs: Supply & Demand (fresh zones/retests), Trend Pullback
      (EMA9/20 bounce in trend), Mean Reversion (fade >2x ATR from VWAP), Range
      Trading (buy low/sell high in balance days)
- [ ] Strategy picker UI on practice screen with locked/unlocked state (ties to
      Phase 4 curriculum gating + Phase 5 premium gating)

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
