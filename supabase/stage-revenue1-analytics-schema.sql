-- Trade Lee — Revenue Infrastructure: first-party analytics events + aggregate
-- reporting RPCs. Run this once in Supabase: SQL Editor -> New query -> paste -> Run.

-- ============================================================
-- TABLE: events (page views, drill completions, firm-link clicks, ...)
-- ============================================================
-- No PII: session_id is a random UUID generated client-side and stored in
-- localStorage, never tied to an email/account. Insert-only — there is no
-- select policy, so raw events (including session_id + page + timing) are
-- never readable through the public anon-key API, only via the aggregate
-- RPCs below (SECURITY DEFINER) or the Supabase dashboard / service role.
create table if not exists public.events (
  id bigint generated always as identity primary key,
  page text not null,
  event text not null,
  session_id uuid not null,
  meta jsonb,
  created_at timestamptz not null default now()
);
create index if not exists events_created_at_idx on public.events (created_at);
create index if not exists events_event_idx on public.events (event);

alter table public.events enable row level security;

create policy "Anyone can log an event" on public.events
  for insert with check (true);

-- ============================================================
-- RPC: get_internal_stats() — aggregate-only counts for /stats-internal/.
-- SECURITY DEFINER so it can read events/waitlist (which anon can't SELECT
-- directly), but it only ever returns pre-aggregated numbers — never a raw
-- row, session_id, or email. This is the practical ceiling on privacy for a
-- project that only holds the anon/publishable key: anyone who knows this
-- function's name can call it and see the same totals shown on the
-- dashboard, but they can never see individual events or who generated them.
-- ============================================================
create or replace function public.get_internal_stats()
returns json
language plpgsql
security definer
set search_path = public
as $$
declare
  result json;
begin
  select json_build_object(
    'visitors_today', (
      select count(distinct session_id) from public.events
      where event = 'pageview' and created_at > date_trunc('day', now() at time zone 'America/New_York')
    ),
    'visitors_7d', (
      select count(distinct session_id) from public.events
      where event = 'pageview' and created_at > now() - interval '7 days'
    ),
    'visitors_30d', (
      select count(distinct session_id) from public.events
      where event = 'pageview' and created_at > now() - interval '30 days'
    ),
    'pageviews_total', (select count(*) from public.events where event = 'pageview'),
    'pageviews_7d', (
      select count(*) from public.events where event = 'pageview' and created_at > now() - interval '7 days'
    ),
    'drills_played_total', (select count(*) from public.events where event = 'drill_complete'),
    'drills_played_7d', (
      select count(*) from public.events where event = 'drill_complete' and created_at > now() - interval '7 days'
    ),
    'funded_pageviews_total', (
      select count(*) from public.events where event = 'pageview' and page = '/funded/'
    ),
    'funded_pageviews_7d', (
      select count(*) from public.events where event = 'pageview' and page = '/funded/' and created_at > now() - interval '7 days'
    ),
    'firm_clicks_total', (select count(*) from public.events where event = 'firm_click'),
    'firm_clicks_7d', (
      select count(*) from public.events where event = 'firm_click' and created_at > now() - interval '7 days'
    ),
    'firm_clicks_by_firm', (
      select coalesce(json_agg(row_to_json(t)), '[]'::json) from (
        select meta->>'firm' as firm, count(*) as clicks
        from public.events where event = 'firm_click'
        group by 1 order by 2 desc
      ) t
    ),
    'waitlist_signups_total', (select count(*) from public.waitlist),
    'waitlist_signups_7d', (
      select count(*) from public.waitlist where created_at > now() - interval '7 days'
    ),
    'pageviews_last_14d_by_day', (
      select coalesce(json_agg(row_to_json(t)), '[]'::json) from (
        select to_char(date_trunc('day', created_at), 'YYYY-MM-DD') as day, count(*) as pageviews
        from public.events
        where event = 'pageview' and created_at > now() - interval '14 days'
        group by 1 order by 1
      ) t
    )
  ) into result;
  return result;
end;
$$;

grant execute on function public.get_internal_stats() to anon, authenticated;

-- ============================================================
-- RPC: get_waitlist_count() — small standalone count for the live /premium/
-- counter, separate from the fuller internal-stats dump above.
-- ============================================================
create or replace function public.get_waitlist_count()
returns int
language sql
stable
security definer
set search_path = public
as $$
  select count(*)::int from public.waitlist;
$$;

grant execute on function public.get_waitlist_count() to anon, authenticated;
