-- Trade Lee — Master Plan Phase 2 schema: Long/Short/Wait stats.
-- Run this once in Supabase: SQL Editor -> New query -> paste -> Run.

alter table public.stats
  add column if not exists lsw_total_answered int not null default 0,
  add column if not exists lsw_total_correct int not null default 0;
