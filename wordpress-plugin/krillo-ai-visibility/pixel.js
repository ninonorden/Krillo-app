/* Krillo AI Visibility: counts visits and WooCommerce orders that come from AI
   assistants. No personal data: only the assistant name, and for an order its
   number and total. Settings come from window.krilloPixel (set by the plugin). */
(function () {
  var cfg = window.krilloPixel || {};
  if (!cfg.k || !cfg.u) { return; }
  var B = {
    "chatgpt.com": "ChatGPT", "chat.openai.com": "ChatGPT",
    "gemini.google.com": "Gemini", "bard.google.com": "Gemini",
    "perplexity.ai": "Perplexity", "www.perplexity.ai": "Perplexity",
    "copilot.microsoft.com": "Copilot"
  };
  function send(d) {
    d.k = cfg.k;
    try {
      if (navigator.sendBeacon) { navigator.sendBeacon(cfg.u, JSON.stringify(d)); }
      else { fetch(cfg.u, { method: "POST", keepalive: true, body: JSON.stringify(d) }); }
    } catch (e) {}
  }
  function source() {
    try {
      var u = new URLSearchParams(location.search).get("utm_source") || "";
      for (var h in B) { if (u.indexOf(h) > -1) { return B[h]; } }
    } catch (e) {}
    try {
      var r = new URL(document.referrer).hostname;
      return B[r] || B[r.replace(/^www\./, "")] || null;
    } catch (e) { return null; }
  }
  var b = null;
  try { b = sessionStorage.getItem("krillo_ai"); } catch (e) {}
  if (!b) {
    b = source();
    if (b) { try { sessionStorage.setItem("krillo_ai", b); } catch (e) {} send({ t: "sessie", b: b }); }
  }
  if (!b) { return; }
  var o = window.krilloOrder;
  if (o && o.id) { send({ t: "order", b: b, v: o.total, c: o.currency || "EUR", o: o.id }); }
})();
