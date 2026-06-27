/* Single source of truth for the "See Accounts HQ in action" slides.
   Edit ONLY the array below — it drives BOTH the web carousel (ca-partners.html)
   AND the presentation deck (tools/build_screens_deck.py reads this file).
   Keys are quoted so the array is valid JSON the Python generator can parse.
   Each slide: { img, alt, title, body }. Plain Indian English. */
window.AHQ_SCREENS = [
  {"img": "img/action/04-ai-bill-reading.png",
   "alt": "The AI Documents Inbox reading a purchase bill",
   "title": "The AI reads the bills for you",
   "body": "Your article assistants lose hours typing in purchase bills. Accounts HQ reads them instead. Email a bill, scan it, or just drop a PDF or photo into the inbox — the AI reads the vendor, the bill number, the amount and the GST split, and prepares a ready-to-post entry, with a confidence score so you know how much to check. You glance, fix the odd field, and post. For the bills it is fully sure of, switch on auto-post and it makes the entry on its own — so one assistant now clears the work of three."},

  {"img": "img/action/01-dashboard.png",
   "alt": "The Accounts HQ dashboard",
   "title": "The whole client, the moment you open the books",
   "body": "Open any client's books and you see where they stand at once — cash and bank, money still to come in, money they owe, and the profit for the month set against the same month last year. The Needs-attention panel does the worrying for you: an overdrawn account, a receivable that has crossed ninety days, a month where spending ran ahead of income. No report to run, no filter to set — it is simply the first thing on the screen."},

  {"img": "img/action/05-voucher-entry.png",
   "alt": "The Post Voucher screen with quick add-ledger",
   "title": "Post a voucher in seconds",
   "body": "When an entry has to be made by hand, it stays quick and correct. Pick the voucher type, choose the ledgers, and Accounts HQ keeps the debit and credit balanced and works out the GST and TDS for you. Need a new party mid-entry? Add the ledger right there — GSTIN, PAN, HSN and TDS section in one small box — without leaving the voucher. Familiar to anyone who has used Tally, only quicker and harder to get wrong."},

  {"img": "img/action/06-bank-reconciliation.png",
   "alt": "Bank reconciliation screen",
   "title": "Bank matching in minutes, not an afternoon",
   "body": "Reconciliation is where every month-end gets stuck. Bring in the bank statement and Accounts HQ lines it up against the books for you — the matched entries on one side, the few that need a second look on the other. The afternoon of ticking off entries becomes a few minutes of confirming. And when the statement is a clean CSV or OFX file, it reads it right on your own computer — no AI, no cost at all."},

  {"img": "img/action/03-receivables.png",
   "alt": "Receivables aging report",
   "title": "Who owes you, and since how long",
   "body": "See exactly which party owes how much, and for how long — within 30 days, 31 to 60, 61 to 90, and beyond ninety. The oldest dues sit right on top, so the follow-up list writes itself. For a client chasing money across a hundred parties, this one screen is the difference between a clean ledger and an unpleasant surprise at year-end."},

  {"img": "img/action/07-gst-tds.png",
   "alt": "GST return — GSTR-1",
   "title": "GST returns ready because the books are",
   "body": "As the entries go in, the GST returns build themselves — GSTR-1, GSTR-3B and the HSN summary — with the CGST, SGST and IGST split worked out from each party's state. There is no separate exercise at filing time and no last-minute matching. By the time the due date comes, the figures are already sitting there."},

  {"img": "img/action/02-cash-flow.png",
   "alt": "Income and expense view",
   "title": "What the client can actually spend",
   "body": "Income and expenses laid out in plain figures — this month against last month, and against the same month last year. It answers the question every business owner asks you and that you usually have to dig out: not what the bank balance says, but what they can truly afford to spend this month."},

  {"img": "img/action/08-tally-import.png",
   "alt": "Tally data migration",
   "title": "Bring the client across from Tally — we do the moving",
   "body": "Shifting a client off Tally is the very thing that stops most firms from starting. We do it for you. Masters, ledgers and vouchers all come across, with nothing left behind — so taking on a new client becomes a simple hand-over, not a project you have to find the time for."}
];
