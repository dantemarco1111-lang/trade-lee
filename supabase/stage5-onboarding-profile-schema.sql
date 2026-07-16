-- Trade Lee — Major Upgrade Stage 5 schema: onboarding personalization profile.
-- Run this once in Supabase: SQL Editor -> New query -> paste -> Run.

alter table public.stats
  add column if not exists onboarding_profile jsonb;
