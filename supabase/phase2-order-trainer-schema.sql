-- Trade Lee — Master Plan Phase 2 schema: Order Execution Trainer stats.
-- Run this once in Supabase: SQL Editor -> New query -> paste -> Run.

alter table public.stats
  add column if not exists ot_total_orders int not null default 0,
  add column if not exists ot_total_filled int not null default 0,
  add column if not exists ot_total_wins int not null default 0;
