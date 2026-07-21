const Stripe = require("stripe");
const { createClient } = require("@supabase/supabase-js");

const stripe = new Stripe(process.env.STRIPE_SECRET_KEY);
const supabase = createClient(process.env.SUPABASE_URL, process.env.SUPABASE_SERVICE_ROLE_KEY);

// Server-side allowlist — never trust a price ID sent from the client directly.
// Env vars take priority so switching to Stripe live mode is pure Vercel
// config (set STRIPE_PRICE_MONTHLY / STRIPE_PRICE_ANNUAL to the live-mode
// price IDs alongside the sk_live_ key); the hardcoded fallbacks are the
// test-mode prices.
const ALLOWED_PRICES = {
  monthly: process.env.STRIPE_PRICE_MONTHLY || "price_1Tv6utFv1BZUHWupMt5C2MYp",
  annual: process.env.STRIPE_PRICE_ANNUAL || "price_1Tv6uyFv1BZUHWupRteSIzo6",
};

const SITE_URL = process.env.SITE_URL || "https://tradelee.xyz";

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

  const { plan, userId, email } = body || {};
  const priceId = ALLOWED_PRICES[plan];
  if (!priceId || !userId || !email) {
    res.status(400).json({ error: "Missing or invalid plan, userId, or email" });
    return;
  }

  try {
    // Reuse the existing Stripe customer if this user already has one on file,
    // so a returning subscriber doesn't fragment into duplicate customers.
    let customerId;
    const { data: existing } = await supabase
      .from("subscriptions")
      .select("stripe_customer_id")
      .eq("user_id", userId)
      .maybeSingle();
    if (existing && existing.stripe_customer_id) {
      customerId = existing.stripe_customer_id;
    }

    const session = await stripe.checkout.sessions.create({
      mode: "subscription",
      line_items: [{ price: priceId, quantity: 1 }],
      client_reference_id: userId,
      ...(customerId ? { customer: customerId } : { customer_email: email }),
      subscription_data: { metadata: { supabase_user_id: userId } },
      allow_promotion_codes: true,
      success_url: `${SITE_URL}/premium/?checkout=success&session_id={CHECKOUT_SESSION_ID}`,
      cancel_url: `${SITE_URL}/premium/?checkout=cancel`,
    });

    res.status(200).json({ url: session.url });
  } catch (err) {
    console.error("create-checkout-session error:", err);
    res.status(500).json({ error: "Could not start checkout" });
  }
};
