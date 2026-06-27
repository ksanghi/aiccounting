# Books HQ Web Port — STATUS / HANDOFF
_Last updated: 2026-06-24_

## What this is
`webapp.py` is a **faithful web port (copy) of the desktop AHQ / Books HQ** — a
FastAPI app that replicates the Qt desktop UI. It **reuses `core/*` engines**
(`VoucherEngine`, `ReportsEngine`, `AccountTree`, the reconcilers,
`BillWiseEngine`, `Migrator`, `license_manager`) — **zero accounting logic
rewritten**. The job is: add the features the desktop has that the web copy is
missing, **the way the desktop has them**. Do NOT add anything the desktop lacks
(no new product, no scope creep).

## How to run
- Web dev server: `python webapp.py` → http://127.0.0.1:8800/ (company: Sunrise Traders)
- On-premise native window: `python desktop_wrapper.py` (pywebview, port 8801) — same code
- Desktop original (to compare against): `python main.py`

## Parity tool (the discipline)
`_element_diff.py` — walks the desktop `MainWindow`'s registered pages (Qt widget
tree) vs each web page's rendered DOM (Playwright) and prints missing controls.
Run with the server up: `python _element_diff.py` → prints gaps + writes
`_element_gaps.json`.
- **BLIND SPOT:** it only compares MainWindow **registered pages**. Complex
  non-page widgets — the **Post Voucher form**, the **reconciliation REVIEW**
  screens — are NOT registered pages, so the tool reports "no gaps" for them even
  when there are. **Verify those by hand** against `ui/voucher_form.py`,
  `ui/bank_reconciliation_page.py`, `ui/ledger_reconciliation_page.py`.

## DONE (parity, verified)
- Phases 1-3: field-filtering, voucher edit/cancel, Preferences (Dr/Cr labels),
  real Excel export, Bank + Ledger reconciliation, GST summary, bill-wise,
  license, backup, period locks, keyboard shortcuts (Ctrl+Q / 1-9 / S,
  Alt+Left / C), dark mode.
- Element-parity pass: Day Book (KPI strip + Delete + totals), Trial Balance
  (full 9 cols + balanced footer), Backup **Restore**, Aging (Customer/Supplier),
  Cash-Flow open-items table, Feedback (Bug/Feature), TDS **Register**, Ledger
  **New/Edit ledger**, GST **Net** column, Bill-wise group dropdown, User Manual
  content, Balance Sheet **Grouped/Flat** toggle.
- **Date-format preference** — wired app-wide via `core/date_format.py` (same
  `user_prefs` as the desktop). On the Preferences screen. Native `<input
  type=date>` pickers stay OS-locale (HTML limitation).
- **Post Voucher form** (was a tool blind spot — found by hand): added date
  ‹ › steppers (Alt+, / Alt+.), **Clear** button, **Calc** button, live Dr/Cr
  **balance bar**.
- **Multi-party voucher**: in-form "+ Multi-party voucher" button shown on
  **Payment / Receipt only** (matches desktop `vtype in (PAYMENT,RECEIPT)`),
  opens `/post-multi` (one bank ↔ N parties; `build_payment_multi` /
  `build_receipt_multi`). NOT a separate menu item.
- **Debit / Credit Note GST**: FIXED — now uses `build_debit_note` /
  `build_credit_note` with the GST split (was posting flat, no tax).

## PENDING / BLOCKED (not built — each needs something external or is a feature)
- AI Documents Inbox / Verbal / Auto-Post / AI-fill on Sales-Purchase → Anthropic API key/credits
- AI Credits / wallet top-up → license server + Razorpay
- Migration wizard → a fresh zero-voucher company (web is single-company; parsers exist)
- License actions (Change key / Re-validate / Release seat / Upgrade) → license server
- Bill-wise allocation on Payment/Receipt (settle vs specific open bills) → PRO feature, not built
- Sales/Purchase amount label → "Base Amount (Rs.)" when GST on → cosmetic, not done
- Cash-Flow "Expect-by / Projected Cash" columns → needs the expectations feature

## Remaining `_element_diff` flags — ALL non-real
- **False-positives** (tool can't reach/see): Day Book ₹ values; Balance Sheet
  "Side" (it's in the Flat view); Bank/Ledger Reconciliation (controls on the
  `/…/review` route); Period Locks Start/End/Status (a secondary desktop widget).
- **Blocked**: AI Inbox, AI Credits, Migration, License actions.
- **Deliberate** (would be dead controls / desktop-only): Settings date-format
  (now on /preferences) + 2 checkboxes; Backup "Backup-to-folder" + local history.

## Test artifacts to CLEAN UP (real test data left in Sunrise Traders)
- Cancel test vouchers: **PMT/2026-27/00008** (multi-party test), **DBN/2026-27/00001** (DN GST test)
- "Web Test Vendor" ledger **id 73** (from an early F2 test)

## Files
- Main: `webapp.py` (~2200 lines, 82 routes)
- Tools: `_element_diff.py`, `desktop_wrapper.py`, `_make_testplan.py`, `_make_gaps.py`
- Test plan: `../BooksHQ_Web_Test_Plan_v4.xlsx` — **DO NOT regenerate/overwrite**;
  the user edits it with findings. Read it; never clobber it.
- Gap analysis: `../BooksHQ_Web_Gap_Analysis_v2.xlsx`

## Working rules (learned this session — follow these)
1. The web is a **COPY of the desktop** — replicate, don't design or add new features.
2. **Never overwrite the user's test sheet** — read it; don't regenerate over it.
3. **No dead controls** — don't add buttons/fields that don't actually work.
4. The `_element_diff` tool is the parity check, but **verify complex screens by
   hand** (its registered-pages blind spot).
5. Less talk, more building. Don't re-explain or re-ask settled things.
