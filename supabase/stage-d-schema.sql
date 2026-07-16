-- Trade Lee — Stage D schema: Speed Run best-score columns.
-- Run this once in Supabase: SQL Editor → New query → paste → Run.

alter table public.stats
  add column if not exists best_speedrun_time_ms int,
  add column if not exists best_speedrun_accuracy int not null default 0;
