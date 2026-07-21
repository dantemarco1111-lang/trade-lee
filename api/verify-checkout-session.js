const Stripe = require("stripe");
const { createClient } = require("@supabase/supabase-js");
const { upsertFromSubscription } = require("./_lib/subscription-sync");

const stripe = new Stripe(process.env.STRIPE_SECRET_KEY);
const supabase = createClient(process.env.SUPABASE_URL, process.env.SUPABASE_SERVICE_ROLE_KEY);

// Reliability fallback for the checkout success page: the webhook is the
// primary path that syncs a completed Checkout Session into Supabase, but it
// runs asynchronously and can lag or (rarely) fail delivery entirely. A
// signed-in purchaser landing on /premium/?checkout=success&session_id=...
// shouldn't be stuck waiting on that — this endpoint reads the session
// straight from Stripe (the source of truth) and performs the exact same
// upsert the webhook would have, so it self-heals Supabase even if the
// webhook never arrives.
module.exports = async (req, res) => {
  if (req.method !== "POST") {
    res.status(405).json({ error: "Method not allowed" });
    return;
  }

  let body;
  try {
    body = typeof req.body === "string" ? JSON.parse(req.body) : req.body;
  } catch {
    res.status(400).json({ error: "Invalid JSON body" });
    return;
  }

  const { sessionId, userId } = body || {};
  if (!sessionId || !userId) {
    res.status(400).json({ error: "Missing sessionId or userId" });
    return;
  }

  try {
    const session = await stripe.checkout.sessions.retrieve(sessionId, { expand: ["subscription"] });

    // The session must actually belong to the user asking about it — otherwise
    // any signed-in user could pass an arbitrary session_id (they're visible
    // in success-redirect URLs) and force a sync/read of someone else's sub.
    if (session.client_reference_id !== userId) {
      res.status(403).json({ error: "Session does not belong to this user" });
      return;
    }

    if (session.mode !== "subscription" || !session.subscription) {
      res.status(200).json({ status: "none" });
      return;
    }

    const subscription = typeof session.subscription === "string"
      ? await stripe.subscriptions.retrieve(session.subscription)
      : session.subscription;
    if (!subscription.metadata || !subscription.metadata.supabase_user_id) {
      subscription.metadata = { ...(subscription.metadata || {}), supabase_user_id: userId };
    }

    const { row } = await upsertFromSubscription(supabase, subscription);
    res.status(200).json({
      status: subscription.status,
      plan: row ? row.plan : null,
      current_period_end: row ? row.current_period_end : null,
      cancel_at_period_end: row ? row.cancel_at_period_end : false,
    });
  } catch (err) {
    console.error("verify-checkout-session error:", err);
    res.status(500).json({ error: "Could not verify checkout session" });
  }
};
