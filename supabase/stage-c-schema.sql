-- Trade Lee — Stage C schema: Pro waitlist.
-- Run this once in Supabase: SQL Editor → New query → paste → Run.

-- ============================================================
-- TABLE: waitlist (email capture for Trade Lee Pro — no payment processing)
-- ============================================================
create table if not exists public.waitlist (
  id uuid primary key default gen_random_uuid(),
  email text not null,
  user_id uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  constraint waitlist_email_shape check (email ~ '^[^\s@]+@[^\s@]+\.[^\s@]+$')
);

alter table public.waitlist enable row level security;

-- Anyone — signed in or anonymous — can join the waitlist. No select policy
-- is defined, so the list is never readable through the public API (only
-- from the Supabase dashboard / service role), which keeps emails private.
create policy "Anyone can join the waitlist" on public.waitlist
  for insert with check (true);
