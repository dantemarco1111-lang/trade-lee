-- Trade Lee — Stage B schema: accounts + global leaderboard.
-- Run this once in Supabase: SQL Editor → New query → paste → Run.

-- ============================================================
-- TABLE: users (one row per signed-in player, links to Supabase auth)
-- ============================================================
create table if not exists public.users (
  id uuid primary key references auth.users(id) on delete cascade,
  display_name text unique not null,
  created_at timestamptz not null default now(),
  constraint display_name_shape check (
    char_length(display_name) between 1 and 20
    and display_name ~ '^[A-Za-z0-9_]+$'
  )
);

alter table public.users enable row level security;

-- Anyone (including anonymous visitors) can read display names — required
-- so the leaderboard can show who's who without requiring sign-in to view.
create policy "Public read access to users" on public.users
  for select using (true);

-- A user may only ever create/update THEIR OWN row (id must match their auth uid).
-- The `unique` constraint on display_name is what makes names first-come-first-served:
-- a second player claiming a taken name gets a unique-violation error client-side.
create policy "Users can insert their own row" on public.users
  for insert with check (auth.uid() = id);

create policy "Users can update their own row" on public.users
  for update using (auth.uid() = id) with check (auth.uid() = id);


-- ============================================================
-- TABLE: stats (aggregate stats per user — what the leaderboard ranks on)
-- ============================================================
create table if not exists public.stats (
  user_id uuid primary key references public.users(id) on delete cascade,
  best_streak int not null default 0,
  total_drills int not null default 0,
  correct_drills int not null default 0,
  ticks int not null default 0,
  updated_at timestamptz not null default now()
);

alter table public.stats enable row level security;

-- Public read is required for the leaderboard (best_streak + accuracy are shown
-- for every ranked player, not just the signed-in viewer).
create policy "Public read access to stats" on public.stats
  for select using (true);

create policy "Users can insert their own stats" on public.stats
  for insert with check (auth.uid() = user_id);

create policy "Users can update their own stats" on public.stats
  for update using (auth.uid() = user_id) with check (auth.uid() = user_id);

-- ANTI-CHEAT NOTE: RLS only guarantees a user can exclusively write to their OWN
-- row — it does NOT verify the numbers they write are honest. A motivated user
-- could call the REST API directly and set best_streak to anything. At this
-- scale (a free drill game, no real-money stakes) that's an accepted tradeoff
-- rather than building a server-authoritative anti-cheat pipeline. If this ever
-- matters more, move stat writes behind a Postgres function (SECURITY DEFINER)
-- that re-derives streak/accuracy from daily_results server-side instead of
-- trusting client-submitted aggregates.


-- ============================================================
-- TABLE: daily_results (one row per user per day — powers streaks + percentile)
-- ============================================================
create table if not exists public.daily_results (
  user_id uuid not null references public.users(id) on delete cascade,
  date date not null,
  correct boolean not null,
  created_at timestamptz not null default now(),
  primary key (user_id, date)
);

alter table public.daily_results enable row level security;

-- Users can only see their OWN daily history (used to recompute streaks on a
-- new device). The daily percentile stat is exposed separately below via a
-- function that returns only an aggregate number, not raw per-user rows.
create policy "Users can read their own daily results" on public.daily_results
  for select using (auth.uid() = user_id);

create policy "Users can insert their own daily result" on public.daily_results
  for insert with check (auth.uid() = user_id);

create policy "Users can update their own daily result" on public.daily_results
  for update using (auth.uid() = user_id) with check (auth.uid() = user_id);

-- ANTI-CHEAT NOTE: the (user_id, date) primary key stops a user from logging
-- more than one result per day, but nothing stops them from writing `correct =
-- true` regardless of what actually happened client-side — again, accepted at
-- this scale since the "drill" has no monetary stakes.


-- ============================================================
-- FUNCTION: get_daily_percentile — aggregate-only, safe for anon to call.
-- Returns the % of all logged results for a given date that were correct,
-- WITHOUT exposing any individual user's row. Used for the "you beat X%"
-- messaging (frontend decides the exact wording based on the viewer's own
-- correct/incorrect outcome).
-- ============================================================
create or replace function public.get_daily_percentile(target_date date)
returns numeric
language sql
security definer
set search_path = public
stable
as $$
  select case when count(*) = 0 then null
    else round(100.0 * sum(case when correct then 1 else 0 end) / count(*), 0)
  end
  from public.daily_results
  where date = target_date;
$$;

grant execute on function public.get_daily_percentile(date) to anon, authenticated;
