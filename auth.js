/*
 * Trade Lee — shared Supabase auth + cloud sync.
 * Include order on any page that needs accounts:
 *   <script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2"></script>
 *   <script src="/supabase-config.js"></script>
 *   <script src="/auth.js"></script>
 *
 * Anonymous play always keeps working: every function here fails soft
 * (returns null / empty / false) if Supabase is unreachable or not configured,
 * so a backend hiccup can never break the game.
 */

let sbClient = null;
window.tlLastAuthError = null; // visible in DevTools console for debugging — auth errors are never silently swallowed
try {
  if (window.supabase && typeof SUPABASE_URL !== "undefined" && SUPABASE_URL) {
    sbClient = window.supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY, {
      auth: {
        persistSession: true,
        autoRefreshToken: true,
        detectSessionInUrl: true,
        // "implicit" (not "pkce") deliberately: PKCE requires completing the
        // flow in the exact same browser that requested it, via a locally
        // stored code_verifier. A magic-link email is inherently opened from
        // a different context (mail app / different browser) more often than
        // not, which would silently fail under PKCE. Implicit puts the token
        // directly in the URL, so it works regardless of which browser opens it.
        flowType: "implicit",
      },
    });
  }
} catch (e) {
  sbClient = null;
  window.tlLastAuthError = e;
  console.error("Trade Lee: Supabase client init failed:", e);
}

let tlSession = null;
let tlProfile = null; // { id, display_name } once claimed
let tlAuthChangeCallbacks = [];
let tlLastMagicLinkSentAt = 0;

function tlOnAuthChange(cb) {
  tlAuthChangeCallbacks.push(cb);
}

// Defensive backstop for the magic-link callback: the Supabase client auto-detects
// ?code=... (PKCE) or #access_token=... (implicit) in the URL on init, but if that
// silently fails (e.g. code_verifier missing because the link was opened in a
// different browser/app than the one that requested it), surface it instead of
// leaving the user in a confusing "looked signed in, now isn't" state.
const tlAuthCallbackParams = new URLSearchParams(window.location.search);
const tlHasAuthCallback = tlAuthCallbackParams.has("code") || /access_token=/.test(window.location.hash);

let tlUrlAlreadyCleaned = false;
if (sbClient) {
  sbClient.auth.onAuthStateChange(async (event, session) => {
    tlSession = session;
    if (!session) tlProfile = null;
    // Once the callback's code/tokens are consumed (success or failure), strip
    // them from the URL so a refresh never re-processes a stale/expired link.
    // By the time this fires, the Supabase client has already read whatever it
    // needed from the URL, so it's safe to just reset to a clean path.
    const wasFreshCallback = tlHasAuthCallback && !tlUrlAlreadyCleaned;
    if (wasFreshCallback) {
      tlUrlAlreadyCleaned = true;
      window.history.replaceState({}, "", window.location.origin + window.location.pathname);
    }
    // A magic link always completes via a full page reload, so any in-progress
    // "check your email" modal state is gone — pick the flow back up here
    // instead of leaving a freshly-signed-in user to figure out on their own
    // that they still need to claim a display name.
    if (wasFreshCallback && event === "SIGNED_IN" && session) {
      const profile = await tlFetchMyProfile();
      if (!profile && typeof tlOpenAuthModal === "function") {
        tlEnsureModalMounted();
        tlRenderAuthModalStep("claim-name");
        document.getElementById("authModalOverlay").classList.add("show");
      }
    }
    tlAuthChangeCallbacks.forEach(cb => { try { cb(event, session); } catch (e) {} });
  });
}

async function tlInitSession() {
  if (!sbClient) return null;
  try {
    const { data, error } = await sbClient.auth.getSession();
    if (error) throw error;
    tlSession = data.session;
    if (!tlSession && tlHasAuthCallback) {
      // We arrived with callback params but ended up with no session — the
      // exchange genuinely failed (expired/reused link, or wrong browser context).
      window.tlLastAuthError = new Error("Magic link callback present but no session was established — link may be expired, already used, or opened in a different browser than the one that requested it.");
      console.error("Trade Lee auth:", window.tlLastAuthError.message);
    }
    if (tlSession) tlProfile = await tlFetchMyProfile();
    return tlSession;
  } catch (e) {
    window.tlLastAuthError = e;
    console.error("Trade Lee auth: tlInitSession failed:", e);
    return null;
  }
}

function tlIsSignedIn() {
  return !!tlSession;
}

function tlSanitizeDisplayName(raw) {
  return (raw || "").trim().replace(/[^A-Za-z0-9_]/g, "").slice(0, 20);
}

async function tlFetchMyProfile() {
  if (!sbClient || !tlSession) return null;
  try {
    const { data, error } = await sbClient.from("users").select("*").eq("id", tlSession.user.id).maybeSingle();
    if (error) throw error;
    tlProfile = data;
    return data;
  } catch (e) {
    return null;
  }
}

// Rate-limited client-side: at most one magic-link request per 30s.
async function tlSendMagicLink(email) {
  if (!sbClient) throw new Error("offline");
  const now = Date.now();
  if (now - tlLastMagicLinkSentAt < 30000) {
    throw new Error("Please wait a few seconds before requesting another link.");
  }
  const clean = (email || "").trim();
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(clean)) {
    throw new Error("Enter a valid email address.");
  }
  const redirectTo = window.location.origin + window.location.pathname;
  const { error } = await sbClient.auth.signInWithOtp({ email: clean, options: { emailRedirectTo: redirectTo } });
  if (error) throw error;
  tlLastMagicLinkSentAt = now;
}

async function tlSignOut() {
  if (!sbClient) return;
  try { await sbClient.auth.signOut(); } catch (e) {}
  tlSession = null;
  tlProfile = null;
}

async function tlClaimDisplayName(name) {
  if (!sbClient || !tlSession) throw new Error("Not signed in.");
  const clean = tlSanitizeDisplayName(name);
  if (!clean) throw new Error("Use letters, numbers, or underscore — at least 1 character.");
  const { error } = await sbClient.from("users").insert({ id: tlSession.user.id, display_name: clean });
  if (error) {
    if (error.code === "23505") throw new Error("That name is taken — try another.");
    throw error;
  }
  tlProfile = { id: tlSession.user.id, display_name: clean };
  return clean;
}

// Merge local progress into the cloud on first login — always takes the MAX
// of local vs. cloud per field, so signing in never wipes existing progress
// on either side. Also pulls down full daily_results history so streaks can
// be recomputed accurately (see tlRecomputeStreaksFromHistory).
async function tlMergeLocalIntoCloud(appState) {
  if (!sbClient || !tlSession) return null;
  const uid = tlSession.user.id;
  try {
    const { data: existingStats } = await sbClient.from("stats").select("*").eq("user_id", uid).maybeSingle();

    const localSrTime = appState.speedRunBestTimeMs;
    const cloudSrTime = existingStats ? existingStats.best_speedrun_time_ms : null;
    let mergedSrTime;
    if (localSrTime == null) mergedSrTime = cloudSrTime;
    else if (cloudSrTime == null) mergedSrTime = localSrTime;
    else mergedSrTime = Math.min(localSrTime, cloudSrTime);

    // Lower practice timer = more adapted/skilled, so merge takes the lower
    // (more advanced) of the two rather than max/min-by-value-only guessing.
    const localTimer = appState.practiceTimerSeconds;
    const cloudTimer = existingStats ? existingStats.practice_timer_seconds : null;
    let mergedTimer;
    if (localTimer == null) mergedTimer = cloudTimer;
    else if (cloudTimer == null) mergedTimer = localTimer;
    else mergedTimer = Math.min(localTimer, cloudTimer);

    // Onboarding profile is a one-time personalization choice, not a stat —
    // the current device's answer wins if present, otherwise keep the cloud's.
    const mergedOnboarding = appState.onboardingProfile || (existingStats ? existingStats.onboarding_profile : null) || null;
    const mergedChartSettings = appState.chartSettings || (existingStats ? existingStats.chart_settings : null) || null;

    // Trader Rating isn't a strict accumulator like ticks/total_drills — the
    // side with MORE rated drills has the more informed number, so keep that
    // side's rating outright rather than max()-ing two Elo values together.
    const localRated = appState.ratedDrillsCount || 0;
    const cloudRated = existingStats ? existingStats.rated_drills_count || 0 : 0;
    const mergedTraderRating = localRated >= cloudRated
      ? (appState.traderRating || 1000)
      : (existingStats ? existingStats.trader_rating : 1000) || 1000;

    const merged = {
      user_id: uid,
      best_streak: Math.max(appState.bestStreakEver || 0, existingStats ? existingStats.best_streak : 0),
      total_drills: Math.max(appState.totalDrillsAnswered || 0, existingStats ? existingStats.total_drills : 0),
      correct_drills: Math.max(appState.totalCorrect || 0, existingStats ? existingStats.correct_drills : 0),
      ticks: Math.max(appState.ticks || 0, existingStats ? existingStats.ticks : 0),
      best_speedrun_time_ms: mergedSrTime,
      best_speedrun_accuracy: Math.max(appState.speedRunBestAccuracy || 0, existingStats ? existingStats.best_speedrun_accuracy : 0),
      practice_timer_seconds: mergedTimer,
      onboarding_profile: mergedOnboarding,
      chart_settings: mergedChartSettings,
      lsw_total_answered: Math.max(appState.lswStats ? appState.lswStats.totalAnswered : 0, existingStats ? existingStats.lsw_total_answered : 0),
      lsw_total_correct: Math.max(appState.lswStats ? appState.lswStats.totalCorrect : 0, existingStats ? existingStats.lsw_total_correct : 0),
      ot_total_orders: Math.max(appState.orderTrainerStats ? appState.orderTrainerStats.totalOrders : 0, existingStats ? existingStats.ot_total_orders : 0),
      ot_total_filled: Math.max(appState.orderTrainerStats ? appState.orderTrainerStats.filled : 0, existingStats ? existingStats.ot_total_filled : 0),
      ot_total_wins: Math.max(appState.orderTrainerStats ? appState.orderTrainerStats.wins : 0, existingStats ? existingStats.ot_total_wins : 0),
      sp_total_answered: Math.max(appState.strategyPackStats ? appState.strategyPackStats.totalAnswered : 0, existingStats ? existingStats.sp_total_answered : 0),
      sp_total_correct: Math.max(appState.strategyPackStats ? appState.strategyPackStats.totalCorrect : 0, existingStats ? existingStats.sp_total_correct : 0),
      daily_play_streak: Math.max(appState.dailyPlayStreak || 0, existingStats ? existingStats.daily_play_streak || 0 : 0),
      daily_win_streak: Math.max(appState.dailyWinStreak || 0, existingStats ? existingStats.daily_win_streak || 0 : 0),
      trader_rating: mergedTraderRating,
      rated_drills_count: Math.max(localRated, cloudRated),
      archetype: appState.archetype || (existingStats ? existingStats.archetype : null) || null,
    };
    await sbClient.from("stats").upsert(merged);

    const { data: history } = await sbClient
      .from("daily_results").select("*").eq("user_id", uid).order("date", { ascending: false });

    return { merged, history: history || [] };
  } catch (e) {
    return null;
  }
}

// Recompute dailyPlayStreak / dailyWinStreak from full history (sorted desc by
// date) — this is what makes signing in on a second device restore an
// accurate streak instead of just zeros.
function tlRecomputeStreaksFromHistory(history) {
  if (!history || !history.length) {
    return { dailyPlayStreak: 0, dailyWinStreak: 0, lastDailyDate: null, lastDailyResult: null };
  }
  const sorted = history.slice().sort((a, b) => (a.date < b.date ? 1 : -1));
  let playStreak = 0;
  let winStreak = 0;
  let winStreakBroken = false;
  let cursor = new Date(sorted[0].date + "T00:00:00Z");
  for (let i = 0; i < sorted.length; i++) {
    const row = sorted[i];
    const cursorStr = cursor.toISOString().slice(0, 10);
    if (row.date !== cursorStr) break;
    playStreak++;
    if (!winStreakBroken) {
      if (row.correct) winStreak++;
      else winStreakBroken = true;
    }
    cursor.setUTCDate(cursor.getUTCDate() - 1);
  }
  return {
    dailyPlayStreak: playStreak,
    dailyWinStreak: winStreak,
    lastDailyDate: sorted[0].date,
    lastDailyResult: sorted[0].correct ? "win" : "loss",
  };
}

async function tlSyncDailyResult(isCorrect, appState, dateStr) {
  if (!sbClient || !tlSession) return;
  try {
    await sbClient.from("daily_results").upsert({ user_id: tlSession.user.id, date: dateStr, correct: isCorrect });
    await tlSyncStats(appState);
  } catch (e) { /* offline or RLS hiccup — local state already has the truth */ }
}

async function tlSyncStats(appState) {
  if (!sbClient || !tlSession) return;
  try {
    await sbClient.from("stats").upsert({
      user_id: tlSession.user.id,
      best_streak: appState.bestStreakEver || 0,
      total_drills: appState.totalDrillsAnswered || 0,
      correct_drills: appState.totalCorrect || 0,
      ticks: appState.ticks || 0,
      best_speedrun_time_ms: appState.speedRunBestTimeMs ?? null,
      best_speedrun_accuracy: appState.speedRunBestAccuracy || 0,
      practice_timer_seconds: appState.practiceTimerSeconds || 30,
      onboarding_profile: appState.onboardingProfile || null,
      chart_settings: appState.chartSettings || null,
      lsw_total_answered: appState.lswStats ? appState.lswStats.totalAnswered : 0,
      lsw_total_correct: appState.lswStats ? appState.lswStats.totalCorrect : 0,
      ot_total_orders: appState.orderTrainerStats ? appState.orderTrainerStats.totalOrders : 0,
      ot_total_filled: appState.orderTrainerStats ? appState.orderTrainerStats.filled : 0,
      ot_total_wins: appState.orderTrainerStats ? appState.orderTrainerStats.wins : 0,
      sp_total_answered: appState.strategyPackStats ? appState.strategyPackStats.totalAnswered : 0,
      sp_total_correct: appState.strategyPackStats ? appState.strategyPackStats.totalCorrect : 0,
      daily_play_streak: appState.dailyPlayStreak || 0,
      daily_win_streak: appState.dailyWinStreak || 0,
      trader_rating: appState.traderRating || 1000,
      rated_drills_count: appState.ratedDrillsCount || 0,
      archetype: appState.archetype || null,
    });
  } catch (e) {}
}

// Public, anonymous-friendly — powers the "Longest active streak" line on the
// Yesterday's Reveal card. `stats`/`users` are both already publicly
// SELECT-able (see stage-b-schema.sql), so this is a plain join query, same
// pattern as tlFetchLeaderboard — no RPC required.
async function tlFetchTopDailyStreak() {
  if (!sbClient) return null;
  try {
    const { data, error } = await sbClient
      .from("stats")
      .select("daily_play_streak, users(display_name)")
      .gt("daily_play_streak", 0)
      .order("daily_play_streak", { ascending: false })
      .limit(1);
    if (error) throw error;
    const row = (data || [])[0];
    if (!row || !row.users || !row.users.display_name) return null;
    return { name: row.users.display_name, streak: row.daily_play_streak };
  } catch (e) {
    return null;
  }
}

/* ============================= WEEKLY LEAGUES (Stage 4) ============================= */
// Lazily buckets the signed-in caller into this week's league on first call
// of a new week (or first-ever call); no-ops if already a member. See
// stage-retention4-leagues-schema.sql for the server-side tier/group logic.
async function tlEnsureLeagueMembership() {
  if (!sbClient || !tlSession) return null;
  try {
    const { data, error } = await sbClient.rpc("ensure_league_membership");
    if (error) throw error;
    return (data || [])[0] || null; // { tier, week_id, league_id, group_number }
  } catch (e) {
    return null;
  }
}
// Fire-and-forget, same pattern as every other cloud sync in this file —
// local Ticks are always the source of truth, this is purely additive.
async function tlAddWeeklyTicks(amount) {
  if (!sbClient || !tlSession || !amount) return;
  try {
    await sbClient.rpc("add_weekly_ticks", { p_amount: amount });
  } catch (e) {}
}
// Full ranked roster of a group, for the league page's live table.
async function tlFetchLeagueGroup(leagueId) {
  if (!sbClient || !leagueId) return null;
  try {
    const { data, error } = await sbClient
      .from("league_members")
      .select("user_id, weekly_ticks, joined_at, week_id, users(display_name)")
      .eq("league_id", leagueId)
      .order("weekly_ticks", { ascending: false });
    if (error) throw error;
    return (data || []).filter(r => r.users && r.users.display_name);
  } catch (e) {
    return null;
  }
}
// The caller's own membership row for the CURRENT week (tier/group/score),
// used to drive the league page once ensure_league_membership() has run.
async function tlFetchMyCurrentLeagueMembership() {
  if (!sbClient || !tlSession) return null;
  try {
    const { data, error } = await sbClient
      .from("league_members")
      .select("week_id, league_id, tier, weekly_ticks, joined_at")
      .eq("user_id", tlSession.user.id)
      .order("week_id", { ascending: false })
      .limit(1);
    if (error) throw error;
    return (data || [])[0] || null;
  } catch (e) {
    return null;
  }
}
// The caller's PREVIOUS week's row + rank within that group's final
// standings — powers the week-rollover "You finished #3 — promoted" screen.
async function tlFetchPreviousWeekResult(prevWeekId) {
  if (!sbClient || !tlSession) return null;
  try {
    const { data: mine, error: e1 } = await sbClient
      .from("league_members")
      .select("week_id, league_id, tier, weekly_ticks")
      .eq("user_id", tlSession.user.id)
      .eq("week_id", prevWeekId)
      .maybeSingle();
    if (e1) throw e1;
    if (!mine) return null;
    const { count, error: e2 } = await sbClient
      .from("league_members")
      .select("user_id", { count: "exact", head: true })
      .eq("league_id", mine.league_id)
      .gt("weekly_ticks", mine.weekly_ticks);
    if (e2) throw e2;
    return { ...mine, rank: (count || 0) + 1 };
  } catch (e) {
    return null;
  }
}

// Total distinct weeks the caller has ever had a league_members row —
// powers the "new player" demotion-shield icon (weeks 1-2 are protected).
async function tlFetchMyLeagueWeeksCount() {
  if (!sbClient || !tlSession) return 0;
  try {
    const { data, error } = await sbClient
      .from("league_members")
      .select("week_id")
      .eq("user_id", tlSession.user.id);
    if (error) throw error;
    return (data || []).length;
  } catch (e) {
    return 0;
  }
}

async function tlFetchDailyPercentile(dateStr) {
  if (!sbClient) return null;
  try {
    const { data, error } = await sbClient.rpc("get_daily_percentile", { target_date: dateStr });
    if (error) throw error;
    return data;
  } catch (e) {
    return null;
  }
}

async function tlFetchTotalDrillsAnswered() {
  if (!sbClient) return null;
  try {
    const { data, error } = await sbClient.rpc("get_total_drills_answered");
    if (error) throw error;
    return data;
  } catch (e) {
    return null;
  }
}

// Count only, no rows returned — how many players have ever logged a stats
// row. Used for the landing page's "join N traders" line; never fabricated.
async function tlFetchTotalTraderCount() {
  if (!sbClient) return null;
  try {
    const { count, error } = await sbClient.from("stats").select("*", { count: "exact", head: true });
    if (error) throw error;
    return count;
  } catch (e) {
    return null;
  }
}

// Works whether the visitor is signed in or anonymous — attaches user_id when available.
async function tlJoinWaitlist(email) {
  if (!sbClient) throw new Error("offline");
  const clean = (email || "").trim();
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(clean)) {
    throw new Error("Enter a valid email address.");
  }
  const { error } = await sbClient.from("waitlist").insert({
    email: clean,
    user_id: tlSession ? tlSession.user.id : null,
  });
  if (error) throw error;
  if (typeof tlTrack === "function") tlTrack("waitlist_signup");
}

// Creates a "challenge a friend" link. Works whether the creator is signed
// in or anonymous (anonymous creators just supply a display name to show).
async function tlCreateChallenge({ mode, drillIds, creatorName, pnl, timeMs, accuracy, correctCount, totalDrills }) {
  if (!sbClient) throw new Error("offline");
  const clean = (creatorName || "").trim().slice(0, 24);
  if (!clean) throw new Error("Enter a name so your friend knows who to beat.");
  const { data, error } = await sbClient
    .from("challenges")
    .insert({
      creator_user_id: tlSession ? tlSession.user.id : null,
      creator_name: clean,
      mode,
      drill_ids: drillIds,
      pnl: pnl === undefined ? null : pnl,
      time_ms: timeMs === undefined ? null : timeMs,
      accuracy,
      correct_count: correctCount,
      total_drills: totalDrills,
    })
    .select()
    .single();
  if (error) throw error;
  return data;
}

// Returns the challenge row, or null if unreachable/not found. Expiry is
// checked client-side against expires_at so a stale link degrades to a
// friendly "expired" message instead of a broken replay.
async function tlFetchChallenge(id) {
  if (!sbClient) return null;
  try {
    const { data, error } = await sbClient.from("challenges").select("*").eq("id", id).maybeSingle();
    if (error) throw error;
    return data;
  } catch (e) {
    return null;
  }
}

async function tlFetchLeaderboard() {
  if (!sbClient) return null; // null = "couldn't reach it" (vs [] = "reached it, nobody qualifies yet")
  try {
    const { data, error } = await sbClient
      .from("stats")
      .select("best_streak, correct_drills, total_drills, trader_rating, rated_drills_count, archetype, users(display_name)")
      .gte("total_drills", 10)
      .order("best_streak", { ascending: false })
      .limit(50);
    if (error) throw error;
    return (data || [])
      .filter(r => r.users && r.users.display_name)
      .sort((a, b) => {
        if (b.best_streak !== a.best_streak) return b.best_streak - a.best_streak;
        const accA = a.total_drills ? a.correct_drills / a.total_drills : 0;
        const accB = b.total_drills ? b.correct_drills / b.total_drills : 0;
        return accB - accA;
      });
  } catch (e) {
    return null;
  }
}

/* ============================= AUTH MODAL (shared UI) ============================= */
function tlEnsureModalMounted() {
  if (document.getElementById("authModalOverlay")) return;
  const overlay = document.createElement("div");
  overlay.className = "auth-modal-overlay";
  overlay.id = "authModalOverlay";
  overlay.innerHTML = `
    <div class="auth-modal-card">
      <button class="auth-modal-close" id="authModalCloseBtn" aria-label="Close">✕</button>
      <div id="authModalBody"></div>
    </div>
  `;
  document.body.appendChild(overlay);
  overlay.addEventListener("click", (e) => { if (e.target === overlay) tlCloseAuthModal(); });
  document.getElementById("authModalCloseBtn").onclick = tlCloseAuthModal;
}

function tlOpenAuthModal() {
  tlEnsureModalMounted();
  tlRenderAuthModalStep("email");
  document.getElementById("authModalOverlay").classList.add("show");
}
function tlCloseAuthModal() {
  const el = document.getElementById("authModalOverlay");
  if (el) el.classList.remove("show");
}

function tlRenderAuthModalStep(step, ctx) {
  ctx = ctx || {};
  const body = document.getElementById("authModalBody");
  if (!body) return;

  if (!sbClient) {
    body.innerHTML = `
      <h3>Sign-in unavailable</h3>
      <p>We can't reach the accounts service right now. Your progress is still saved on this device — try again later.</p>
    `;
    return;
  }

  if (step === "email") {
    body.innerHTML = `
      <h3>Sign in to save your streak</h3>
      <p>We'll email you a one-time link — no password needed.</p>
      <input type="email" id="authEmailInput" placeholder="you@email.com" autocomplete="email">
      <div class="auth-modal-error hidden" id="authModalErr"></div>
      <button class="btn btn-primary" id="authSendBtn">Send magic link</button>
      <p class="legal-consent-line">By continuing you agree to the <a href="/terms/">Terms</a> &amp; <a href="/privacy/">Privacy Policy</a>.</p>
    `;
    document.getElementById("authSendBtn").onclick = async () => {
      const input = document.getElementById("authEmailInput");
      const btn = document.getElementById("authSendBtn");
      const errEl = document.getElementById("authModalErr");
      errEl.classList.add("hidden");
      btn.disabled = true;
      btn.textContent = "Sending…";
      try {
        await tlSendMagicLink(input.value);
        tlRenderAuthModalStep("sent", { email: input.value.trim() });
      } catch (e) {
        errEl.textContent = (e.message && e.message !== "{}") ? e.message : "Something went wrong on our end — please try again in a moment.";
        errEl.classList.remove("hidden");
        btn.disabled = false;
        btn.textContent = "Send magic link";
      }
    };
  } else if (step === "sent") {
    body.innerHTML = `
      <h3>Check your email</h3>
      <p class="auth-modal-success">Sent a sign-in link to ${ctx.email}.</p>
      <p>Click it on this device to finish signing in. You can close this window.</p>
    `;
  } else if (step === "claim-name") {
    body.innerHTML = `
      <h3>Pick a display name</h3>
      <p>Shown on the leaderboard. Letters, numbers, underscore — up to 20 characters.</p>
      <input type="text" id="authNameInput" placeholder="your_name" maxlength="20">
      <div class="auth-modal-error hidden" id="authModalErr"></div>
      <button class="btn btn-primary" id="authClaimBtn">Save name</button>
    `;
    document.getElementById("authClaimBtn").onclick = async () => {
      const input = document.getElementById("authNameInput");
      const btn = document.getElementById("authClaimBtn");
      const errEl = document.getElementById("authModalErr");
      errEl.classList.add("hidden");
      btn.disabled = true;
      btn.textContent = "Saving…";
      try {
        await tlClaimDisplayName(input.value);
        tlRenderAuthModalStep("welcome", { name: tlProfile.display_name });
        if (ctx.onClaimed) ctx.onClaimed(tlProfile.display_name);
      } catch (e) {
        errEl.textContent = (e.message && e.message !== "{}") ? e.message : "Something went wrong on our end — please try again in a moment.";
        errEl.classList.remove("hidden");
        btn.disabled = false;
        btn.textContent = "Save name";
      }
    };
  } else if (step === "welcome") {
    body.innerHTML = `
      <h3>You're in, ${ctx.name} 🎉</h3>
      <p class="auth-modal-success">Your progress is now synced to the cloud.</p>
      <button class="btn btn-primary" id="authDoneBtn">Nice</button>
    `;
    document.getElementById("authDoneBtn").onclick = tlCloseAuthModal;
  }
}
