// Single source of truth for Trade Lee's social links — edit here, applies site-wide.
// Set a value to null/empty to have its icon auto-remove instead of linking nowhere.
const SOCIAL_LINKS = {
  tiktok: "https://tiktok.com/@tradelee",
  youtube: "https://youtube.com/@TradeLee-d1m",
  instagram: "https://instagram.com/tradelee.app",
};

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("[data-social]").forEach(el => {
    const url = SOCIAL_LINKS[el.dataset.social];
    if (url) {
      el.href = url;
      el.target = "_blank";
      el.rel = "noopener noreferrer";
    } else {
      el.remove();
    }
  });
});
