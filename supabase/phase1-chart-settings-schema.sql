-- Trade Lee — Master Plan Phase 1 schema: chart settings sync.
-- Run this once in Supabase: SQL Editor -> New query -> paste -> Run.

alter table public.stats
  add column if not exists chart_settings jsonb;
