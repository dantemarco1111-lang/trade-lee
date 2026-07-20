const Stripe = require("stripe");
const { createClient } = require("@supabase/supabase-js");
const { upsertFromSubscription } = require("./_lib/subscription-sync");

const stripe = new Stripe(process.env.STRIPE_SECRET_KEY);
const supabase = createClient(process.env.SUPABASE_URL, process.env.SUPABASE_SERVICE_ROLE_KEY);

function buffer(readable) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    readable.on("data", (chunk) => chunks.push(typeof chunk === "string" ? Buffer.from(chunk) : chunk));
    readable.on("end", () => resolve(Buffer.concat(chunks)));
    readable.on("error", reject);
  });
}

async function handler(req, res) {
  if (req.method !== "POST") {
    res.status(405).end("Method not allowed");
    return;
  }

  const buf = await buffer(req);
  const signature = req.headers["stripe-signature"];

  let event;
  try {
    event = stripe.webhooks.constructEvent(buf, signature, process.env.STRIPE_WEBHOOK_SECRET);
  } catch (err) {
    console.error("stripe-webhook: signature verification failed:", err.message);
    res.status(400).send(`Webhook Error: ${err.message}`);
    return;
  }

  try {
    switch (event.type) {
      case "checkout.session.completed": {
        const session = event.data.object;
        if (session.mode === "subscription" && session.subscription) {
          const subscription = await stripe.subscriptions.retrieve(session.subscription);
          // client_reference_id survives on the session even if metadata is missing on the sub itself.
          if (!subscription.metadata || !subscription.metadata.supabase_user_id) {
            subscription.metadata = { ...(subscription.metadata || {}), supabase_user_id: session.client_reference_id };
          }
          await upsertFromSubscription(supabase, subscription);
        }
        break;
      }
      case "customer.subscription.updated":
      case "customer.subscription.deleted": {
        await upsertFromSubscription(supabase, event.data.object);
        break;
      }
      default:
        break;
    }
    res.status(200).json({ received: true });
  } catch (err) {
    console.error("stripe-webhook: handler error:", err);
    res.status(500).json({ error: "Webhook handler failed" });
  }
}

// Stripe needs the exact raw request bytes to verify the signature — any
// JSON re-parse/re-serialize (even reordering keys) breaks HMAC verification.
// Disabling Vercel's automatic body parsing is required so we can buffer the
// untouched bytes ourselves before handing them to stripe.webhooks.constructEvent.
// MUST be attached after `handler` is assigned to module.exports, not before —
// reassigning module.exports (as opposed to mutating it in place) replaces the
// object entirely, silently dropping any properties set on it beforehand.
module.exports = handler;
module.exports.config = {
  api: { bodyParser: false },
};
