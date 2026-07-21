/*
 * Trade Lee — shared nav account chip.
 * Injects a "Sign in" button (signed-out) or a name chip that opens the
 * account menu (signed-in) into the site header + mobile menu on every
 * content page. Load AFTER auth.js:
 *   <script src="/auth.js"></script>
 *   <script src="/nav-account.js"></script>
 *
 * The game screen (play/index.html) has its own richer in-game chip and no
 * .nav-links-desktop marketing nav, so this safely no-ops there.
 */
(function () {
  function injectStyles() {
    if (document.getElementById("tlNavAccountStyles")) return;
    const s = document.createElement("style");
    s.id = "tlNavAccountStyles";
    s.textContent = `
      .tl-nav-account {
        margin-left: 6px; padding: 8px 16px; border-radius: 999px;
        font-family: var(--font-body); font-weight: 700; font-size: 0.85rem;
        cursor: pointer; border: 1px solid var(--border-strong);
        background: var(--surface-2); color: var(--text);
        transition: transform 0.15s cubic-bezier(.34,1.56,.64,1), background 0.15s, border-color 0.15s;
        white-space: nowrap;
      }
      .tl-nav-account:hover { border-color: var(--gold); }
      .tl-nav-account:active { transform: scale(0.94); }
      .tl-nav-account.signed-out { background: var(--gold); color: #0b0e14; border-color: var(--gold); }
      .tl-nav-account.signed-in::before { content: "◆ "; color: var(--gold); }
      .tl-mobile-account {
        display: block; margin-top: 10px; font-weight: 700; color: var(--gold);
      }
    `;
    document.head.appendChild(s);
  }

  function build() {
    if (typeof tlInitNavAccountChip !== "function") return; // auth.js not loaded
    injectStyles();

    // Desktop: append into the marketing nav if present and not already done.
    const nav = document.querySelector(".nav-links-desktop");
    if (nav && !document.getElementById("tlNavAccountChip")) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.id = "tlNavAccountChip";
      btn.className = "tl-nav-account hidden";
      nav.appendChild(btn);
      // tlInitNavAccountChip handles render + live auth updates; layer the
      // signed-in/out styling on top via the same lifecycle.
      const restyle = () => {
        const el = document.getElementById("tlNavAccountChip");
        if (!el) return;
        const signedIn = (typeof tlIsSignedIn === "function" && tlIsSignedIn() && typeof tlProfile !== "undefined" && tlProfile);
        el.classList.toggle("signed-in", !!signedIn);
        el.classList.toggle("signed-out", !signedIn);
      };
      tlInitNavAccountChip("tlNavAccountChip");
      if (window.tlSessionReady) window.tlSessionReady.then(restyle);
      if (typeof tlOnAuthChange === "function") tlOnAuthChange(() => setTimeout(restyle, 0));
      setTimeout(restyle, 400);
    }

    // Mobile menu: append a sign-in / account entry.
    const mobile = document.querySelector(".mobile-menu-overlay");
    if (mobile && !document.getElementById("tlMobileAccount")) {
      const a = document.createElement("a");
      a.id = "tlMobileAccount";
      a.className = "tl-mobile-account";
      a.href = "#";
      mobile.appendChild(a);
      const renderMobile = () => {
        const el = document.getElementById("tlMobileAccount");
        if (!el) return;
        const signedIn = (typeof tlIsSignedIn === "function" && tlIsSignedIn() && typeof tlProfile !== "undefined" && tlProfile);
        if (signedIn) {
          el.textContent = `◆ ${tlProfile.display_name} — Profile`;
          el.href = "/profile/";
          el.onclick = null;
        } else {
          el.textContent = "Sign in";
          el.href = "#";
          el.onclick = (e) => { e.preventDefault(); if (typeof tlOpenAuthModal === "function") tlOpenAuthModal(); };
        }
      };
      if (window.tlSessionReady) window.tlSessionReady.then(renderMobile);
      if (typeof tlOnAuthChange === "function") tlOnAuthChange(() => setTimeout(renderMobile, 0));
      setTimeout(renderMobile, 400);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", build);
  } else {
    build();
  }
})();
