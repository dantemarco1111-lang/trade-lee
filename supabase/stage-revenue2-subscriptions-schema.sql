-- Trade Lee — Stage Revenue 2: Pro subscriptions (Stripe).
-- Run this once in Supabase: SQL Editor → New query → paste → Run.
--
-- This table is written ONLY by the Stripe webhook (server-side, using the
-- service_role key, which bypasses RLS entirely) — never by the client. The
-- client (anon key + user's own auth JWT) can only ever READ its own row.
-- This mirrors the insert-only pattern used for events/waitlist: the browser
-- is never trusted to self-report its own subscription status.

create table if not exists public.subscriptions (
  user_id uuid primary key references auth.users(id) on delete cascade,
  stripe_customer_id text unique,
  stripe_subscription_id text unique,
  status text not null default 'none',
  plan text,
  current_period_end timestamptz,
  cancel_at_period_end boolean not null default false,
  updated_at timestamptz not null default now()
);

alter table public.subscriptions enable row level security;

create policy "Users can read their own subscription" on public.subscriptions
  for select using (auth.uid() = user_id);

-- No insert/update/delete policy for anon/authenticated — only service_role
-- (used exclusively by the /api/stripe-webhook serverless function) can write.

create index if not exists subscriptions_stripe_customer_id_idx
  on public.subscriptions (stripe_customer_id);
