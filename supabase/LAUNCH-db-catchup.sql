-- ============================================================================
-- Trade Lee — LAUNCH DB catch-up migration (2026-07)
-- ============================================================================
-- Bundles six migrations that were authored but never run on the production
-- Supabase project. Without them the stats cloud-sync upsert fails entirely
-- (missing columns), the global leaderboard's rating column errors, and the
-- whole weekly-leagues system is absent. All statements are idempotent
-- (if not exists / or replace / drop-then-create policy), so running this
-- once is safe and running it twice is harmless.
--
-- HOW TO RUN: Supabase dashboard -> SQL Editor -> New query -> paste ALL of
-- this -> Run. Then hard-refresh the site.
-- ============================================================================

-- ===== from phase2-order-trainer-schema.sql =====
-- Trade Lee — Master Plan Phase 2 schema: Order Execution Trainer stats.
-- Run this once in Supabase: SQL Editor -> New query -> paste -> Run.

alter table public.stats
  add column if not exists ot_total_orders int not null default 0,
  add column if not exists ot_total_filled int not null default 0,
  add column if not exists ot_total_wins int not null default 0;

-- ===== from phase3-strategy-packs-schema.sql =====
-- Trade Lee — Master Plan Phase 3 schema: Strategy Pack stats.
-- Run this once in Supabase: SQL Editor -> New query -> paste -> Run.

alter table public.stats
  add column if not exists sp_total_answered int not null default 0,
  add column if not exists sp_total_correct int not null default 0;

-- ===== from stage-retention2-daily-streak-schema.sql =====
-- Trade Lee — Retention Stage 2: "The 9:30 Drop" daily streak sync.
-- Run this once in Supabase: SQL Editor → New query → paste → Run.
--
-- Adds columns so a player's daily-drill streak (previously local-only in
-- localStorage) is visible cross-device and can power the "Longest active
-- streak" line on the Yesterday's Reveal card. No new table needed — this
-- rides on the existing `stats` row per user.

alter table public.stats
  add column if not exists daily_play_streak int not null default 0;

alter table public.stats
  add column if not exists daily_win_streak int not null default 0;

-- No new RLS policies needed: `stats` is already publicly readable (see
-- stage-b-schema.sql "Public read access to stats") and users can already
-- only write their own row. The client queries this column directly via
-- `.select("daily_play_streak, users(display_name)").order(...).limit(1)`
-- the same way the leaderboard already queries best_streak — no RPC required.
--
-- ANTI-CHEAT NOTE: same tradeoff as every other client-submitted stat in this
-- schema (see stage-b-schema.sql) — a motivated user could write an inflated
-- daily_play_streak directly via the REST API. Accepted at this scale.

-- ===== from stage-retention3-trader-rating-schema.sql =====
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

-- ===== from stage-retention5-archetype-schema.sql =====
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

-- ===== from stage-retention4-leagues-schema.sql (weekly leagues) =====
-- Trade Lee — Retention Stage 4: Weekly Leagues.
-- Run this once in Supabase: SQL Editor → New query → paste → Run.
--
-- Weekly cohorts of up to 20 signed-in players, bucketed by tier
-- (bronze → silver → gold → platinum → funded), scored on Ticks earned
-- that week. Top 5 promote, bottom 5 demote, new joiners get a 2-week
-- demotion shield. There is no scheduled server function in this project
-- (only the anon/publishable key is held client-side — see MASTERPLAN.md),
-- so "week rollover" and "bucketing" both happen lazily: the first
-- authenticated request of a new week triggers ensure_league_membership(),
-- which computes everything for that one player. There is deliberately no
-- global cron; each player's own visit is what advances their own row.

-- ============================================================
-- Current league week id — Monday 00:00 America/New_York boundary.
-- Postgres date_trunc('week', ...) already starts weeks on Monday (ISO).
-- ============================================================
create or replace function public.current_league_week_id()
returns text
language sql
stable
as $$
  select to_char(date_trunc('week', (now() at time zone 'America/New_York')), 'IYYY-"W"IW');
$$;

create or replace function public.league_week_id_offset(weeks_back int)
returns text
language sql
stable
as $$
  select to_char(date_trunc('week', (now() at time zone 'America/New_York')) - (weeks_back || ' weeks')::interval, 'IYYY-"W"IW');
$$;

-- ============================================================
-- TABLE: leagues — one row per (week_id, tier, group_number) cohort.
-- ============================================================
create table if not exists public.leagues (
  id uuid primary key default gen_random_uuid(),
  week_id text not null,
  tier text not null check (tier in ('bronze', 'silver', 'gold', 'platinum', 'funded')),
  group_number int not null,
  member_count int not null default 0,
  created_at timestamptz not null default now(),
  unique (week_id, tier, group_number)
);

alter table public.leagues enable row level security;

drop policy if exists "Public read access to leagues" on public.leagues;
create policy "Public read access to leagues" on public.leagues
  for select using (true);

-- No public insert/update policy — leagues rows are only ever created by
-- ensure_league_membership() below, which runs as SECURITY DEFINER.


-- ============================================================
-- TABLE: league_members — one row per user per week: their group + score.
-- ============================================================
create table if not exists public.league_members (
  week_id text not null,
  user_id uuid not null references public.users(id) on delete cascade,
  league_id uuid not null references public.leagues(id) on delete cascade,
  tier text not null,
  weekly_ticks int not null default 0,
  joined_at timestamptz not null default now(),
  primary key (week_id, user_id)
);

alter table public.league_members enable row level security;

-- Public read is required so every member of a group can see the whole
-- group's ranking (not just their own row) — same tradeoff as `stats`.
drop policy if exists "Public read access to league_members" on public.league_members;
create policy "Public read access to league_members" on public.league_members
  for select using (true);

-- No public insert/update policy — rows are only ever written by the two
-- SECURITY DEFINER functions below. This is deliberately stricter than
-- `stats`/`daily_results` elsewhere in this schema: weekly_ticks drives
-- actual promotion/demotion outcomes (a visible, comparative ranking),
-- so a raw client-writable column here would be a much more obvious and
-- tempting target than an isolated personal stat. Routing every write
-- through a function that only ever touches auth.uid()'s own row closes
-- off direct "set anyone's score" tampering, though see the anti-cheat
-- note on add_weekly_ticks() below for what this does NOT protect against.


-- ============================================================
-- FUNCTION: ensure_league_membership — call on every visit to the league
-- page (or any page, cheaply) for a signed-in user. No-ops if the caller
-- already has a row for the current week. Otherwise computes their tier
-- from last week's result (promote top 5 / demote bottom 5, protected by
-- a 2-week-from-joining demotion shield) and slots them into the first
-- tier group with room, creating a new group if every existing one is full.
-- ============================================================
create or replace function public.ensure_league_membership()
returns table(tier text, week_id text, league_id uuid, group_number int)
language plpgsql
security definer
set search_path = public
as $$
declare
  v_uid uuid := auth.uid();
  v_week text := current_league_week_id();
  v_prev_week text := league_week_id_offset(1);
  v_prev record;
  v_new_tier text;
  v_rank int;
  v_group_size int;
  v_weeks_played int;
  v_tiers text[] := array['bronze', 'silver', 'gold', 'platinum', 'funded'];
  v_tier_idx int;
  v_league_id uuid;
  v_group_number int;
begin
  if v_uid is null then
    raise exception 'not signed in';
  end if;

  -- already have a row for this week — nothing to do.
  if exists (select 1 from league_members where week_id = v_week and user_id = v_uid) then
    return query
      select lm.tier, lm.week_id, lm.league_id, lg.group_number
      from league_members lm join leagues lg on lg.id = lm.league_id
      where lm.week_id = v_week and lm.user_id = v_uid;
    return;
  end if;

  select lm.*, lg.group_number as g_num, lg.member_count as g_size
    into v_prev
    from league_members lm join leagues lg on lg.id = lm.league_id
    where lm.week_id = v_prev_week and lm.user_id = v_uid;

  select count(distinct week_id) into v_weeks_played from league_members where user_id = v_uid;

  if v_prev is null then
    v_new_tier := 'bronze';
  else
    select count(*) + 1 into v_rank
      from league_members
      where league_id = v_prev.league_id and weekly_ticks > v_prev.weekly_ticks;
    v_group_size := v_prev.g_size;
    v_tier_idx := array_position(v_tiers, v_prev.tier);

    if v_rank <= 5 and v_tier_idx < array_length(v_tiers, 1) then
      v_new_tier := v_tiers[v_tier_idx + 1]; -- promote
    elsif v_rank > greatest(v_group_size - 5, 5) and v_tier_idx > 1 and v_weeks_played >= 2 then
      v_new_tier := v_tiers[v_tier_idx - 1]; -- demote (shielded for first 2 weeks)
    else
      v_new_tier := v_prev.tier; -- stayed, or protected from demotion
    end if;
  end if;

  -- find a group in v_new_tier/v_week with room, else create one.
  select id, group_number into v_league_id, v_group_number
    from leagues
    where week_id = v_week and tier = v_new_tier and member_count < 20
    order by group_number asc
    limit 1
    for update skip locked;

  if v_league_id is null then
    select coalesce(max(group_number), 0) + 1 into v_group_number
      from leagues where week_id = v_week and tier = v_new_tier;
    insert into leagues (week_id, tier, group_number, member_count)
      values (v_week, v_new_tier, v_group_number, 0)
      returning id into v_league_id;
  end if;

  insert into league_members (week_id, user_id, league_id, tier, weekly_ticks)
    values (v_week, v_uid, v_league_id, v_new_tier, 0);
  update leagues set member_count = member_count + 1 where id = v_league_id;

  return query select v_new_tier, v_week, v_league_id, v_group_number;
end;
$$;

grant execute on function public.ensure_league_membership() to authenticated;


-- ============================================================
-- FUNCTION: add_weekly_ticks — increments the caller's own current-week
-- weekly_ticks. Called alongside the existing local awardTicks() so a
-- league score builds up over the week as the player plays normally.
--
-- ANTI-CHEAT NOTE: this clamps a single call to at most 500 (the largest
-- legitimate single-event award in the client — the 30-day streak
-- milestone bonus) purely to block the most trivial abuse (one call with
-- an absurd amount). It does NOT verify the amount against actual drill
-- submissions server-side — there is no submissions log this could check
-- against without a much larger rework of the Ticks pipeline into a
-- server-authoritative model. A motivated user could still call this
-- repeatedly to inflate a weekly score. Accepted at this scale, same
-- tradeoff as every other client-submitted stat in this schema — but
-- flagged here specifically because league rank is a *comparative*,
-- visible outcome (promotion/demotion) rather than a private personal
-- stat, so it's the single highest-value target in the whole schema.
-- ============================================================
create or replace function public.add_weekly_ticks(p_amount int)
returns void
language plpgsql
security definer
set search_path = public
as $$
declare
  v_uid uuid := auth.uid();
  v_week text := current_league_week_id();
  v_clamped int := greatest(0, least(p_amount, 500));
begin
  if v_uid is null then return; end if;
  update league_members set weekly_ticks = weekly_ticks + v_clamped
    where week_id = v_week and user_id = v_uid;
  -- silently no-ops if the caller has no row yet for this week — the
  -- client should call ensure_league_membership() first (it does).
end;
$$;

grant execute on function public.add_weekly_ticks(int) to authenticated;
