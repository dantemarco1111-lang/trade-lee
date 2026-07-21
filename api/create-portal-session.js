const Stripe = require("stripe");
const { createClient } = require("@supabase/supabase-js");

const stripe = new Stripe(process.env.STRIPE_SECRET_KEY);
const supabase = createClient(process.env.SUPABASE_URL, process.env.SUPABASE_SERVICE_ROLE_KEY);

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

  const { userId } = body || {};
  if (!userId) {
    res.status(400).json({ error: "Missing userId" });
    return;
  }

  try {
    const { data, error } = await supabase
      .from("subscriptions")
      .select("stripe_customer_id")
      .eq("user_id", userId)
      .maybeSingle();

    if (error || !data || !data.stripe_customer_id) {
      res.status(404).json({ error: "No billing account found for this user" });
      return;
    }

    const portalSession = await stripe.billingPortal.sessions.create({
      customer: data.stripe_customer_id,
      return_url: `${SITE_URL}/premium/`,
    });

    res.status(200).json({ url: portalSession.url });
  } catch (err) {
    console.error("create-portal-session error:", err);
    res.status(500).json({ error: "Could not open billing portal", _debug: { message: err.message, type: err.type, code: err.code, param: err.param } });
  }
};
