-- Trade Lee — Retention Stage 3: Trader Rating (Elo-style).
-- Run this once in Supabase: SQL Editor → New query → paste → Run.
--
-- Adds columns so a player's Trader Rating (previously local-only) is
-- visible cross-device and can power the new "Rating" column on the
-- global leaderboard. Rides on the existing `stats` row per user, same
-- pattern as stage-retention2-daily-streak-schema.sql.

alter table public.stats
  add column if not exists trader_rating int not null default 1000;

alter table public.stats
  add column if not exists rated_drills_count int not null default 0;

-- No new RLS policies needed: `stats` is already publicly readable (see
-- stage-b-schema.sql "Public read access to stats") and users can already
-- only write their own row.
--
-- ANTI-CHEAT NOTE: same tradeoff as every other client-submitted stat in
-- this schema — a motivated user could write an inflated trader_rating
-- directly via the REST API. Accepted at this scale.
