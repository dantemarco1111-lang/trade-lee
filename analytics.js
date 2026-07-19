/*
 * Trade Lee — lightweight first-party analytics (Revenue Infrastructure).
 * No PII: session id is a random UUID stored in localStorage, never tied to
 * an email or account. Fails soft — if Supabase isn't reachable or the
 * events table doesn't exist yet, tracking silently no-ops and never
 * breaks the page.
 *
 * Include after auth.js (needs the shared `sbClient`):
 *   <script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2"></script>
 *   <script src="/supabase-config.js"></script>
 *   <script src="/auth.js"></script>
 *   <script src="/analytics.js"></script>
 *
 * Fires a "pageview" automatically on load. Call window.tlTrack(event, meta)
 * elsewhere for anything else (drill_complete, firm_click, waitlist_signup).
 */
(function () {
  const SESSION_KEY = "tl_anon_session_id";

  function makeUuid() {
    if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, c => {
      const r = (Math.random() * 16) | 0;
      const v = c === "x" ? r : (r & 0x3) | 0x8;
      return v.toString(16);
    });
  }
  function getSessionId() {
    try {
      let id = localStorage.getItem(SESSION_KEY);
      if (!id) {
        id = makeUuid();
        localStorage.setItem(SESSION_KEY, id);
      }
      return id;
    } catch (e) {
      return makeUuid();
    }
  }

  window.tlTrack = function (event, meta) {
    try {
      if (typeof sbClient === "undefined" || !sbClient) return;
      sbClient.from("events").insert({
        page: location.pathname,
        event: event,
        session_id: getSessionId(),
        meta: meta || null,
      }).then(function () {}, function () {});
    } catch (e) {}
  };

  window.tlTrack("pageview");
})();
