// Shared by /api/stripe-webhook.js (the primary path, event-driven) and
// /api/verify-checkout-session.js (the fallback path, polled by the client
// when the webhook hasn't landed yet) — both need to write the exact same
// shape to Supabase so neither path can leave the row in a half-updated
// state depending on which one happened to run first.
// NOT itself a route: Vercel excludes /api/_lib/** (underscore prefix) from
// becoming an endpoint.
const PRICE_PLAN = {
  "price_1Tv6utFv1BZUHWupMt5C2MYp": "monthly",
  "price_1Tv6uyFv1BZUHWupRteSIzo6": "annual",
};
// Live-mode price IDs come from env (see create-checkout-session.js) — map
// them to the same plan names so the sync works identically in either mode.
if (process.env.STRIPE_PRICE_MONTHLY) PRICE_PLAN[process.env.STRIPE_PRICE_MONTHLY] = "monthly";
if (process.env.STRIPE_PRICE_ANNUAL) PRICE_PLAN[process.env.STRIPE_PRICE_ANNUAL] = "annual";

async function upsertFromSubscription(supabase, subscription) {
  const userId = subscription.metadata && subscription.metadata.supabase_user_id;
  if (!userId) {
    console.error("subscription-sync: subscription missing supabase_user_id metadata", subscription.id);
    return null;
  }
  const priceId = subscription.items.data[0] && subscription.items.data[0].price && subscription.items.data[0].price.id;
  const row = {
    user_id: userId,
    stripe_customer_id: subscription.customer,
    stripe_subscription_id: subscription.id,
    status: subscription.status,
    plan: PRICE_PLAN[priceId] || null,
    current_period_end: new Date(subscription.current_period_end * 1000).toISOString(),
    cancel_at_period_end: !!subscription.cancel_at_period_end,
    updated_at: new Date().toISOString(),
  };
  const { error } = await supabase.from("subscriptions").upsert(row);
  if (error) {
    console.error("subscription-sync: upsert failed", error);
    return { row: null, error };
  }
  return { row, error: null };
}

module.exports = { upsertFromSubscription, PRICE_PLAN };
