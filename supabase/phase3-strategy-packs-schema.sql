-- Trade Lee — Master Plan Phase 3 schema: Strategy Pack stats.
-- Run this once in Supabase: SQL Editor -> New query -> paste -> Run.

alter table public.stats
  add column if not exists sp_total_answered int not null default 0,
  add column if not exists sp_total_correct int not null default 0;
