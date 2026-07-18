-- Trade Lee — Retention Stage 2: "The 9:30 Drop" daily streak sync.
-- Run this once in Supabase: SQL Editor → New query → paste → Run.
--
-- Adds columns so a player's daily-drill streak (previously local-only in
-- localStorage) is visible cross-device and can power the "Longest active
-- streak" line on the Yesterday's Reveal card. No new table needed — this
-- rides on the existing `stats` row per user.

alter table public.stats
  add column if not exists daily_play_streak int not null default 0;

alter table public.stats
  add column if not exists daily_win_streak int not null default 0;

-- No new RLS policies needed: `stats` is already publicly readable (see
-- stage-b-schema.sql "Public read access to stats") and users can already
-- only write their own row. The client queries this column directly via
-- `.select("daily_play_streak, users(display_name)").order(...).limit(1)`
-- the same way the leaderboard already queries best_streak — no RPC required.
--
-- ANTI-CHEAT NOTE: same tradeoff as every other client-submitted stat in this
-- schema (see stage-b-schema.sql) — a motivated user could write an inflated
-- daily_play_streak directly via the REST API. Accepted at this scale.
