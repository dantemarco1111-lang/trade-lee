# Trade Lee — Handoff

Single source of truth for any future session or collaborator picking this up cold. Read this first, then `MASTERPLAN.md` for the original build history.

## What this is

Trade Lee is a free browser game that trains traders to read charts — given a real historical chart at the moment of a breakout, you call it "real" or "fake" in 10 seconds, using actual market data (not hand-drawn or randomly generated). It's the practice layer for people considering a funded prop-firm evaluation: build reps and an honest track record before spending real money on an eval.

## Stack

- **Hosting:** Vercel. Static site, no build step, no `vercel.json` — Vercel auto-detects and serves the HTML/CSS/JS directly, plus auto-detects the `api/` folder as Node.js serverless functions (needs `package.json` present, which now exists for the `stripe` and `@supabase/supabase-js` server-side dependencies).
- **Database/auth:** Supabase (Postgres + passwordless magic-link auth). The static site only ever holds the anon/publishable key. The `api/*.js` serverless functions are the one exception — they run server-side on Vercel and use the `service_role` key (via env var, never committed) to write to tables the anon key can't touch, like `subscriptions`.
- **Billing:** Stripe (Checkout Sessions + Billing Portal + webhook). Currently pointed at a **sandbox/test-mode** Stripe account — no real charges can occur until the account is switched to live keys.
- **Charts:** [lightweight-charts](https://github.com/tradingview/lightweight-charts) (TradingView's open-source library), loaded only on `play/index.html` — not on marketing pages.
- **Drill data generator:** `generate_drills.py` (Python, uses `yfinance` to pull real 5-minute intraday candles across stocks/futures/forex/crypto packs, detects patterns mechanically per rules in `DETECTION.md`, outputs `drills/*.json`). Companion scripts: `regen_classic_packs.py` (non-destructive re-run for the 8 classic market-pack files), `stock_terminal.py`.
- **No framework.** Every page is a single self-contained HTML file with inline `<style>` and `<script>`. `play/index.html` is the largest — a big single-file SPA covering every game mode.

## Deploys

**Push to `main` = live.** Vercel is connected to the GitHub repo (`dantemarco1111-lang/trade-lee`) and auto-deploys every push to `main`. There is no staging environment and no manual deploy step — committing and pushing IS the deploy.

## Where everything lives

| What | File | Notes |
|---|---|---|
| Affiliate firm list | `funded/index.html`, `const FIRM_LINKS` | Every firm defaults to `status: "pending"` — only `status: "live"` renders. Flip to `"live"` + real URL once an affiliate application is approved. |
| Social links | `social-links.js` (repo root) | Single source of truth, loaded on every page via `[data-social]` attributes. Set a value to `null` to auto-hide that icon. |
| Beta pricing flag | `play/index.html`, `const BETA_FREE = true` (~line 1230) | Controls whether Pro features are unlocked for everyone. Flip to `false` when Pro actually launches and gating should kick in. |
| Design tokens | `theme.css` (repo root) | Contrast ladder (`--text-data/--text/--text-dim`, `--border/--border-strong`), motion system (`--ease`, `--duration-micro/standard/emphasis`), spacing/radius/shadow scales. Loaded on every page — change once, applies everywhere. |
| Original build plan | `MASTERPLAN.md` | Covers the initial 6-phase build (chart engine → decision modes → strategy packs → Academy → freemium → polish). Fully complete as of this doc. Everything since (retention mechanics, UI polish passes, revenue infrastructure, legal pages) happened in later sessions and isn't tracked in that file — check `git log` for that history instead. |
| Drill generation | `generate_drills.py`, `regen_classic_packs.py` | Run `python generate_drills.py` to regenerate all drill decks from fresh market data. Detection rules documented in `DETECTION.md`. |
| Pattern-detection rules | `DETECTION.md` | Plain-language + exact thresholds for every strategy pack. Linked publicly from `/about/`. |
| Supabase migrations | `supabase/*.sql` | Must be run manually in the Supabase SQL Editor, in the order they were added (filenames are roughly chronological: `stage-b`, `stage-c`, `stage-d`, `phase1`, `phase2`, `phase3`, `stage2-adaptive-timer`, `stage5-onboarding-profile`, `stage6-hooks`, `stage-retention2` through `stage-retention5`, `stage-revenue1-analytics`, `stage-revenue2-subscriptions`). All but `stage-revenue2-subscriptions` have been applied as of this doc — see "Outstanding manual steps" below. |
| Stripe billing | `api/create-checkout-session.js`, `api/stripe-webhook.js`, `api/create-portal-session.js` | Serverless functions, not client code. Product/price IDs are hardcoded server-side in an allowlist (never trust a price ID from the client). Webhook verifies the Stripe signature against the raw request body (`bodyParser: false` — do not remove, it will silently break signature verification). |

### Supabase tables

`users`, `stats`, `daily_results`, `challenges`, `leagues`, `league_members`, `waitlist`, `events`, `subscriptions`. Raw `events`/`waitlist` rows are insert-only (no public SELECT policy) — the `/stats-internal/` dashboard reads only pre-aggregated data through `SECURITY DEFINER` RPC functions (`get_internal_stats()`, `get_waitlist_count()`), since the anon key can't be trusted with row-level read access. `subscriptions` follows the same posture: owner-only SELECT via RLS, write access only via `service_role` (used exclusively by `api/stripe-webhook.js`) — the client never self-reports its own Pro status.

## Current business state (as of this doc)

- **Pricing:** Beta — every Pro feature is free for everyone (`BETA_FREE = true`, in `play/index.html`). A real Stripe subscription now exists alongside that ($9/mo or $90/yr founding pricing) — subscribing today doesn't unlock anything extra (everything's already free in beta), it locks in that price before beta ends. Product/prices live in a **sandbox** Stripe account; see "Outstanding manual steps."
- **Affiliate firms:** Applications not yet submitted/approved — all 8 firms in `FIRM_LINKS` are `status: "pending"`, so `/funded/` shows the readiness gate and disclosure but no live firm cards yet.
- **Waitlist:** Live and collecting real signups (Pro waitlist + general founding-member list), count shown on `/premium/` — now positioned as the free alternative to subscribing.
- **Analytics:** Live — first-party pageview/event tracking to Supabase, dashboard at `/stats-internal/` (not linked in nav, `noindex`).
- **Legal:** `/privacy/` and `/terms/` are live and linked from every page's footer (plus a compact link on the game's home screen, which has no traditional footer).

## Outstanding manual steps (Stripe billing)

These require dashboard access I don't have (service role key, Stripe secret key, Vercel project settings) — do these once to make real subscriptions work end to end:

1. Run `supabase/stage-revenue2-subscriptions-schema.sql` in the Supabase SQL Editor.
2. In Vercel → Project → Settings → Environment Variables, add: `STRIPE_SECRET_KEY` (from the Stripe dashboard's API keys page — test/sandbox key for now), `SUPABASE_URL` (`https://fzzpxoryolgzemdggkse.supabase.co`), `SUPABASE_SERVICE_ROLE_KEY` (Supabase → Settings → API → `service_role` key — never put this in a committed file), and `STRIPE_WEBHOOK_SECRET` (from step 3 below).
3. In the Stripe dashboard → Developers → Webhooks → Add endpoint, pointed at `https://tradelee.xyz/api/stripe-webhook`, subscribed to `checkout.session.completed`, `customer.subscription.updated`, `customer.subscription.deleted`. Copy its signing secret into `STRIPE_WEBHOOK_SECRET` above.
4. Redeploy (push any small commit, or use Vercel's redeploy button) so the new env vars take effect.
5. **Going live:** everything above is sandbox/test mode. When ready to accept real payments, switch the Stripe dashboard to live mode, create the same Product/Prices there (test and live mode don't share objects), update the price IDs in `api/create-checkout-session.js` and `api/stripe-webhook.js`, swap `STRIPE_SECRET_KEY`/`STRIPE_WEBHOOK_SECRET` for their live-mode equivalents, and re-create the webhook endpoint in live mode.

## Rules learned the hard way

- **Always commit + push before ending a session.** Push to `main` is the deploy — uncommitted or unpushed work isn't live no matter how correct it is locally.
- **Verify on the live URL, not just localhost**, before considering a change done — the local dev server (`serve.py`) can serve stale cached JS/HTML across a long-lived browser tab even with `Cache-Control: no-store` set, so a bug can look fixed locally and still be live in production (or vice versa).
- **Timezone handling gotcha:** all chart candle times and displayed timestamps must go through Eastern-time helpers (`toEasternChartTime()`, the `America/New_York`-based formatters in `play/index.html`) — market data is fundamentally ET-anchored (session opens/closes, kill zones, the Daily Drill's 9:30 AM ET unlock), and naive local-timezone rendering will silently show the wrong session boundaries for any user not in US Eastern time.
- **No fixed-height page wrappers.** Page-level containers use `min-height`, never `height`, and never `overflow-y: hidden` — a rigid height assumes a tall browser window, and real desktop windows (browser chrome eats into 1366×768/1280×600) will silently clip content below the fold with no way to scroll to it. Modals/sheets get `max-height: 90vh` + `overflow-y: auto` instead of assuming they'll fit. This bit the project once already (see `theme.css`'s "LAYOUT SAFETY RULE" comment at the top of the file) — don't reintroduce it.
- **Supabase access is anon-key-only in this environment.** Any new table needs an explicit RLS policy (insert-only where user data shouldn't be publicly readable) and, if aggregate stats need to be exposed, a `SECURITY DEFINER` RPC function rather than a public SELECT policy.
