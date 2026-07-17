-- Trade Lee — Major Upgrade Stage 6 schema: professional hooks (stat ticker).
-- Run this once in Supabase: SQL Editor -> New query -> paste -> Run.

-- Aggregate-only, safe for anon to call: total drills answered across every
-- player, for the landing page's "Traders have answered {total} drills"
-- stat. Never exposes any individual user's numbers.
create or replace function public.get_total_drills_answered()
returns bigint
language sql
security definer
set search_path = public
stable
as $$
  select coalesce(sum(total_drills), 0) from public.stats;
$$;

grant execute on function public.get_total_drills_answered() to anon, authenticated;
