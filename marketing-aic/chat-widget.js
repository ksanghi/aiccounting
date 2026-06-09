/* AI Consultants — support chat widget.
   Two layers: (1) instant, free canned answers for common questions (the FAQ
   list + the suggested chips); (2) anything else is sent to /api/chat, a
   KB-grounded AI assistant (server-side, rate-limited, self-improving cache). */
(function () {
  if (window.__aiccChat) return;
  window.__aiccChat = true;

  var FAQ = [
    { q: "What does AI Consultants make?",
      k: ["product", "products", "what do you", "offer", "apps", "software", "make", "build"],
      a: "We build desktop business software:<br>&bull; <b>Accounts HQ</b> &mdash; accounting for Indian businesses<br>&bull; <b>RWA HQ</b> &mdash; apartment / society management<br>&bull; <b>Books HQ</b> &mdash; simple books for US small business <i>(coming soon)</i><br>&bull; <b>HOA HQ</b> &mdash; the US version of RWA HQ<br>&bull; <b>tradeHQ</b> &mdash; broker &amp; investment consolidation<br><a href='/index.html'>See all products &rarr;</a>" },
    { q: "How much does it cost?",
      k: ["price", "pricing", "cost", "how much", "plan", "plans", "fee", "charge"],
      a: "Every product is <b>free to start</b> &mdash; no card needed. Paid plans, per year: Accounts HQ from <b>&#8377;1,999</b>, RWA HQ from <b>&#8377;2,999</b>. <a href='/pricing.html'>Full pricing &rarr;</a>" },
    { q: "Is there a free version?",
      k: ["free", "trial", "demo", "try", "no cost"],
      a: "Yes &mdash; a permanent free tier on every product. Download and start; upgrade only when you outgrow the limits." },
    { q: "Is my data safe?",
      k: ["data", "safe", "privacy", "private", "secure", "cloud", "security", "leave"],
      a: "Your books run on <b>your own computer</b> and work <b>offline</b> &mdash; your data never leaves your machine unless you ask it to. Not even we can see it." },
    { q: "Do you handle GST and TDS?",
      k: ["gst", "tds", "tax", "return", "hsn", "sac", "compliance"],
      a: "Yes (Accounts HQ): GST is split automatically &mdash; CGST / SGST / IGST from state codes &mdash; and TDS is applied section-wise. <a href='/accountshq.html'>More &rarr;</a>" },
    { q: "Can I move from Tally or Busy?",
      k: ["tally", "busy", "migrate", "migration", "switch", "import", "move", "existing"],
      a: "Yes &mdash; bring your existing Tally or Busy books over in minutes. <a href='/accountshq.html'>Accounts HQ &rarr;</a>" },
    { q: "Does it use AI?",
      k: ["artificial", "automatic", "scan", "snap", "receipt"],
      a: "Yes &mdash; the AI reads your bills, invoices and statements into draft entries for you to approve. Minimum typing." },
    { q: "What is RWA HQ?",
      k: ["rwa", "society", "apartment", "resident", "flat", "building", "maintenance", "visitor", "complaint"],
      a: "RWA HQ runs apartment / plot societies &mdash; maintenance billing, dues, complaints, visitor passes, notices, and a free resident app. <a href='/rwahq/'>RWA HQ &rarr;</a>" },
    { q: "What is Books HQ?",
      k: ["books hq", "bookshq", "1099", "sales tax", "freelancer"],
      a: "Books HQ is simple books for US small businesses &mdash; branded invoices, snap-a-receipt AI bookkeeping, sales tax &amp; 1099. <i>Coming soon.</i> <a href='/bookshq.html'>Reserve early-bird &rarr;</a>" },
    { q: "Which platforms? Is there a Mac app?",
      k: ["platform", "windows", "mac", "android", "ios", "phone", "download", "install", "mobile"],
      a: "The apps are <b>Windows desktop</b> &mdash; download the installer and run. (RWA HQ also has a free resident mobile app.)" },
    { q: "How do I contact you?",
      k: ["contact", "support", "email", "talk", "human", "phone", "reach"],
      a: "Email us anytime at <a href='mailto:info@ai-consultants.in'>info@ai-consultants.in</a> and we'll get back to you. <a href='/contact.html'>Contact &rarr;</a>" }
  ];

  var GREETING = "Hi! 👋 I'm the AI Consultants helper. Ask me anything about our products &mdash; pricing, GST, bank reconciliation, migrating from Tally &mdash; or tap a question below.";
  var AI_FAIL  = "Sorry, I couldn't reach the assistant just now. Please email <a href='mailto:info@ai-consultants.in'>info@ai-consultants.in</a> and we'll help.";

  // Returns the best canned FAQ match + its keyword score.
  function match(text) {
    text = " " + text.toLowerCase() + " ";
    var best = null, bestScore = 0;
    for (var i = 0; i < FAQ.length; i++) {
      var score = 0;
      for (var j = 0; j < FAQ[i].k.length; j++) {
        if (text.indexOf(FAQ[i].k[j]) !== -1) score++;
      }
      if (score > bestScore) { bestScore = score; best = FAQ[i]; }
    }
    return { item: best, score: bestScore };
  }

  function escapeHtml(s) { var d = document.createElement("div"); d.textContent = s || ""; return d.innerHTML; }
  function stripHtml(h) { var d = document.createElement("div"); d.innerHTML = h || ""; return (d.textContent || "").trim(); }
  function linkify(s) {
    var h = escapeHtml(s);
    h = h.replace(/(https?:\/\/[^\s<]+)/g, '<a href="$1" target="_blank" rel="noopener">$1</a>');
    h = h.replace(/([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})/g, '<a href="mailto:$1">$1</a>');
    return h.replace(/\n/g, "<br>");
  }

  var css =
    ".aicc-btn{position:fixed;right:22px;bottom:22px;z-index:9998;width:58px;height:58px;border-radius:50%;" +
    "background:#0EA5A5;border:none;cursor:pointer;box-shadow:0 10px 26px -8px rgba(14,165,165,.7);display:flex;" +
    "align-items:center;justify-content:center;transition:transform .12s ease}" +
    ".aicc-btn:hover{transform:translateY(-2px)}.aicc-btn svg{width:27px;height:27px;fill:#fff}" +
    ".aicc-panel{position:fixed;right:22px;bottom:92px;z-index:9999;width:344px;max-width:calc(100vw - 28px);" +
    "height:472px;max-height:calc(100vh - 130px);background:#fff;border-radius:16px;overflow:hidden;display:none;" +
    "flex-direction:column;box-shadow:0 24px 60px -16px rgba(15,23,42,.45);border:1px solid #E2E8F0;" +
    "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif}" +
    ".aicc-panel.open{display:flex}" +
    ".aicc-head{background:linear-gradient(135deg,#0B1220,#16203A);color:#fff;padding:15px 18px;display:flex;" +
    "align-items:center;justify-content:space-between}" +
    ".aicc-head b{font-size:15px}.aicc-head small{color:#94A3B8;font-size:11.5px;display:block;margin-top:1px}" +
    ".aicc-x{background:none;border:none;color:#94A3B8;font-size:22px;cursor:pointer;line-height:1}" +
    ".aicc-x:hover{color:#fff}" +
    ".aicc-msgs{flex:1;overflow-y:auto;padding:16px;background:#F8FAFC}" +
    ".aicc-b{max-width:86%;padding:10px 13px;border-radius:12px;font-size:13.5px;line-height:1.5;margin-bottom:10px;word-wrap:break-word}" +
    ".aicc-bot{background:#fff;border:1px solid #E2E8F0;color:#0F172A;border-bottom-left-radius:3px}" +
    ".aicc-user{background:#0EA5A5;color:#fff;margin-left:auto;border-bottom-right-radius:3px}" +
    ".aicc-b a{color:#0EA5A5;font-weight:600}.aicc-user a{color:#fff}" +
    ".aicc-typing{color:#94A3B8;letter-spacing:2px}" +
    ".aicc-chips{padding:0 16px 8px;display:flex;flex-wrap:wrap;gap:7px;background:#F8FAFC}" +
    ".aicc-chip{background:#fff;border:1px solid #CBD5E1;color:#0F172A;font-size:12px;padding:6px 11px;border-radius:999px;cursor:pointer}" +
    ".aicc-chip:hover{border-color:#0EA5A5;color:#0EA5A5}" +
    ".aicc-in{display:flex;border-top:1px solid #E2E8F0;background:#fff}" +
    ".aicc-in input{flex:1;border:none;padding:13px 15px;font-size:13.5px;outline:none;background:transparent}" +
    ".aicc-in button{background:none;border:none;color:#0EA5A5;font-weight:700;font-size:13.5px;padding:0 16px;cursor:pointer}" +
    ".aicc-foot{text-align:center;font-size:10.5px;color:#94A3B8;padding:6px;background:#fff}";

  function el(htmlStr) { var d = document.createElement("div"); d.innerHTML = htmlStr; return d.firstElementChild; }

  function init() {
    var style = document.createElement("style"); style.textContent = css; document.head.appendChild(style);

    var btn = el("<button class='aicc-btn' aria-label='Open help chat'><svg viewBox='0 0 24 24'><path d='M12 3C6.5 3 2 6.8 2 11.5c0 2.2 1 4.2 2.7 5.7L4 21l4.2-1.4c1.2.4 2.5.6 3.8.6 5.5 0 10-3.8 10-8.5S17.5 3 12 3z'/></svg></button>");
    var panel = el(
      "<div class='aicc-panel' role='dialog' aria-label='Help chat'>" +
        "<div class='aicc-head'><div><b>AI Consultants</b><small>Ask us anything</small></div>" +
        "<button class='aicc-x' aria-label='Close'>&times;</button></div>" +
        "<div class='aicc-msgs'></div>" +
        "<div class='aicc-chips'></div>" +
        "<div class='aicc-in'><input type='text' placeholder='Ask a question...' aria-label='Type a question'><button>Send</button></div>" +
        "<div class='aicc-foot'>AI assistant &middot; for anything else, info@ai-consultants.in</div>" +
      "</div>");

    if (document.querySelector(".dl-tile")) { btn.style.bottom = "94px"; panel.style.bottom = "164px"; }

    document.body.appendChild(btn); document.body.appendChild(panel);
    var msgs = panel.querySelector(".aicc-msgs");
    var chips = panel.querySelector(".aicc-chips");
    var input = panel.querySelector(".aicc-in input");
    var convo = [];     // {role:'user'|'bot', content:<plain text>}

    function bubble(cls, html) {
      var b = document.createElement("div");
      b.className = "aicc-b " + cls;
      b.innerHTML = html; msgs.appendChild(b); msgs.scrollTop = msgs.scrollHeight;
      return b;
    }
    function addUser(text) { bubble("aicc-user", escapeHtml(text)); }
    function addBot(htmlStr) { bubble("aicc-bot", htmlStr); convo.push({ role: "bot", content: stripHtml(htmlStr) }); }

    function askAI(text, hist) {
      var typing = bubble("aicc-bot aicc-typing", "&middot;&middot;&middot;");
      fetch("/api/chat", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, history: hist })
      }).then(function (r) { return r.json(); })
        .then(function (d) {
          typing.remove();
          addBot(linkify(d && d.answer ? d.answer : stripHtml(AI_FAIL)));
        })
        .catch(function () { typing.remove(); addBot(AI_FAIL); });
    }

    function answer(text) {
      addUser(text);
      var hist = convo.slice(-6);                 // prior turns (before this one)
      convo.push({ role: "user", content: text });
      var m = match(text);
      if (m.item && m.score >= 2) {               // confident canned match → free
        setTimeout(function () { addBot(m.item.a); }, 180);
      } else {
        askAI(text, hist);                        // long-tail → KB-grounded AI
      }
    }

    function renderChips() {
      chips.innerHTML = "";
      [0, 1, 3, 4, 7].forEach(function (i) {       // products, pricing, data-safe, GST, RWA
        var c = document.createElement("button");
        c.className = "aicc-chip"; c.textContent = FAQ[i].q;
        c.onclick = function () { addUser(FAQ[i].q); convo.push({ role: "user", content: FAQ[i].q }); setTimeout(function () { addBot(FAQ[i].a); }, 160); };
        chips.appendChild(c);
      });
    }

    var opened = false;
    function open() {
      panel.classList.add("open");
      if (!opened) { opened = true; addBot(GREETING); renderChips(); }
    }
    btn.onclick = function () { panel.classList.contains("open") ? panel.classList.remove("open") : open(); };
    panel.querySelector(".aicc-x").onclick = function () { panel.classList.remove("open"); };
    function send() { var v = input.value.trim(); if (v) { answer(v); input.value = ""; } }
    panel.querySelector(".aicc-in button").onclick = send;
    input.addEventListener("keydown", function (e) { if (e.key === "Enter") send(); });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
