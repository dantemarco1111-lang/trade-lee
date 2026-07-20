const Stripe = require("stripe");
const { createClient } = require("@supabase/supabase-js");

const stripe = new Stripe(process.env.STRIPE_SECRET_KEY);
const supabase = createClient(process.env.SUPABASE_URL, process.env.SUPABASE_SERVICE_ROLE_KEY);

const PRICE_PLAN = {
  "price_1Tv6utFv1BZUHWupMt5C2MYp": "monthly",
  "price_1Tv6uyFv1BZUHWupRteSIzo6": "annual",
};

// Stripe needs the exact raw request bytes to verify the signature — any
// JSON re-parse/re-serialize (even reordering keys) breaks HMAC verification.
// Disabling Vercel's automatic body parsing is required so we can buffer the
// untouched bytes ourselves before handing them to stripe.webhooks.constructEvent.
module.exports.config = {
  api: { bodyParser: false },
};

function buffer(readable) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    readable.on("data", (chunk) => chunks.push(typeof chunk === "string" ? Buffer.from(chunk) : chunk));
    readable.on("end", () => resolve(Buffer.concat(chunks)));
    readable.on("error", reject);
  });
}

async function upsertFromSubscription(subscription) {
  const userId = subscription.metadata && subscription.metadata.supabase_user_id;
  if (!userId) {
    console.error("stripe-webhook: subscription missing supabase_user_id metadata", subscription.id);
    return;
  }
  const priceId = subscription.items.data[0] && subscription.items.data[0].price && subscription.items.data[0].price.id;
  await supabase.from("subscriptions").upsert({
    user_id: userId,
    stripe_customer_id: subscription.customer,
    stripe_subscription_id: subscription.id,
    status: subscription.status,
    plan: PRICE_PLAN[priceId] || null,
    current_period_end: new Date(subscription.current_period_end * 1000).toISOString(),
    cancel_at_period_end: !!subscription.cancel_at_period_end,
    updated_at: new Date().toISOString(),
  });
}

module.exports = async (req, res) => {
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
          await upsertFromSubscription(subscription);
        }
        break;
      }
      case "customer.subscription.updated":
      case "customer.subscription.deleted": {
        await upsertFromSubscription(event.data.object);
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
};
