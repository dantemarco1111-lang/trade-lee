-- Trade Lee — Retention Stage 5: Trader Archetype.
-- Run this once in Supabase: SQL Editor → New query → paste → Run.
--
-- Just one column — the archetype key (e.g. "sniper") computed client-side
-- once a player crosses 50 lifetime drills. Synced so it can show next to
-- a player's name on the leaderboard (toggle) and survive a device switch.

alter table public.stats
  add column if not exists archetype text;

-- No RLS changes needed: `stats` is already publicly readable and users
-- can already only write their own row (see stage-b-schema.sql).
