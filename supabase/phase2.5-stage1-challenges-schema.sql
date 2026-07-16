-- Trade Lee — Phase 2.5 Stage 1 schema: Challenge a Friend.
-- Run this once in Supabase: SQL Editor -> New query -> paste -> Run.

-- ============================================================
-- TABLE: challenges (one row per "challenge a friend" link)
-- ============================================================
create table if not exists public.challenges (
  id uuid primary key default gen_random_uuid(),
  creator_user_id uuid references auth.users(id) on delete set null,
  creator_name text not null,
  mode text not null check (mode in ('practice', 'speedrun')),
  drill_ids text[] not null,
  pnl numeric,              -- practice mode score (session P&L)
  time_ms int,               -- speed run mode score (total time)
  accuracy int not null,     -- 0-100, both modes
  correct_count int not null,
  total_drills int not null,
  created_at timestamptz not null default now(),
  expires_at timestamptz not null default (now() + interval '30 days'),
  constraint creator_name_shape check (char_length(creator_name) between 1 and 24)
);

alter table public.challenges enable row level security;

-- Anyone (signed in or anonymous) can create a challenge link.
create policy "Anyone can create a challenge" on public.challenges
  for insert with check (true);

-- Anyone can open a challenge link by its (unguessable) id -- this is how a
-- friend's browser loads the intro screen and the exact drill sequence.
-- No listing/index query is ever run client-side, only lookups by id.
create policy "Anyone can read a challenge by id" on public.challenges
  for select using (true);

-- ANTI-CHEAT NOTE: same tradeoff as stats/daily_results -- a motivated user
-- could submit a fabricated score via the REST API directly. Acceptable at
-- this scale (no real-money stakes); see stage-b-schema.sql for the same
-- note on the stats table.
