-- Trade Lee — Major Upgrade Stage 2 schema: adaptive practice timer.
-- Run this once in Supabase: SQL Editor -> New query -> paste -> Run.

alter table public.stats
  add column if not exists practice_timer_seconds int not null default 30;
