# AccGenie 1.0.5 — Test Plan

**Build under test:** `build\dist\AccGenie-Setup-1.0.5.exe` (build pending —
v1.0.4 installer at `build\dist\AccGenie-Setup-1.0.4.exe` covers everything
up to commit `7a63c20`; the Excel-baked-config work from 2026-05-15 is not
yet in an installer).

**Carry these to the test machine:**

1. `AccGenie-Setup-1.0.5.exe` (or 1.0.4 if 1.0.5 isn't built yet)
2. This file (`test_plan_1.0.5.md`)
3. A sample bank statement PDF and a sample sales invoice PDF for the AI tests
4. (Optional) Your existing `license.json` if you want to keep a paid plan
   active across the test machine

**Conventions:**

- ☐ = run this test. Tick when verified.
- *Setup* lists what state the system must be in before you start the steps.
- *Expected* lists everything that has to be true for the test to pass.
- Anywhere the plan says "the License page" / "the Settings page" etc.,
  reach it via the left sidebar.

**Time estimate:** sections A–G ~1–1.5 hours if everything passes first
time; budget 2.5 hours for first pass on a fresh machine.

---

## A. Install / upgrade (15 min)

### A1. Fresh install on a clean machine ☐

*Setup:* a Windows 10/11 machine that has never run AccGenie. No
`%APPDATA%\AccGenie` folder exists.

*Steps:*
1. Double-click `AccGenie-Setup-1.0.5.exe`.
2. Accept defaults; let it install to `%LOCALAPPDATA%\AccGenie`.
3. Launch from the Start menu shortcut.

*Expected:*
- Installer finishes without admin prompts.
- App launches; Company Selector dialog appears.
- `%APPDATA%\AccGenie\` is created (empty except for any auto-seeded
  files).
- No crash, no missing-DLL error. (If "VCRUNTIME140.dll missing",
  install Microsoft Visual C++ Redistributable first.)

### A2. Upgrade install over 1.0.4 ☐

*Setup:* a machine with 1.0.4 already installed, at least one company DB
in `%APPDATA%\AccGenie\companies\`, and an activated license.

*Steps:*
1. Run `AccGenie-Setup-1.0.5.exe`. Choose "Uninstall first, then reinstall"
   when prompted (the installer does this automatically per `installer.iss`).
2. Launch the upgraded app.

*Expected:*
- Existing companies still listed in the Company Selector.
- License plan still shows the previous plan (not reset to DEMO) — the
  cached `license.json` survives the install.
- Recent vouchers are still visible in Day Book.
- No DB-schema errors. (Schema is idempotent — `CREATE TABLE IF NOT EXISTS`
  — but verify nothing barfs in the console.)

### A3. Clean uninstall ☐

*Steps:*
1. Use Windows "Add/Remove Programs" → Uninstall AccGenie.
2. Confirm `%LOCALAPPDATA%\AccGenie\` is gone.
3. **Verify** `%APPDATA%\AccGenie\` (companies, license, credits) is
   **preserved** — this is intentional so a reinstall keeps user data.

---

## B. License & seat management (20 min)

This is the **highest-risk area** for 1.0.5 because the Phase 1 seat
redesign + per-machine binding is recent.

### B1. DEMO trial cap at 50 vouchers ☐

*Setup:* fresh install, no license entered.

*Steps:*
1. Open any company; create one if needed.
2. Plan badge should read **DEMO** on the License page.
3. Post 49 vouchers (any type — Receipt / Payment, single-line).
4. Post the 50th voucher.
5. Try to post the 51st.

*Expected:*
- Vouchers 1–50 post normally.
- Voucher 51 is **blocked** with a "Demo limit of 50 transactions
  reached" message.
- License page shows `Used: 50 / 50` (100%).

> Note: this verifies the Excel-baked DEMO `txn_limit` (50) is in effect.
> If the cap fires at 10, the bake didn't run — re-run
> `python build\bake_config.py` and rebuild the installer.

### B2. Activate a real key (online) ☐

*Setup:* B1 just hit the cap (or use a fresh DEMO). Have a real STANDARD
or PRO license key handy. Online.

*Steps:*
1. License page → enter the key → Activate.
2. Wait for the green confirmation.

*Expected:*
- Plan badge changes to STANDARD/PRO.
- `Used: N / 20,000` (or 50,000) — the previous DEMO count carries over.
- `Seats: 1 / 2` (STANDARD) or `1 / 5` (PRO).
- Newly unlocked features appear in the sidebar (Reports, etc.).

### B3. Seat enforcement — install on a 2nd machine with a 1-seat key ☐

*Setup:* a 1-seat (FREE) or 2-seat (STANDARD) key already activated on
machine A, plus a 2nd Windows machine B with a fresh install.

*Steps:*
1. On machine B, enter the same key.
2. (For STANDARD, seat 2/2 should activate OK; for FREE, seat should
   already be taken.)
3. On machine A, also try to re-validate via License page → Refresh.

*Expected:*
- FREE: machine B activation is **rejected** with "All seats are in use"
  or similar.
- STANDARD: machine B activates (1 → 2/2). Machine A still works.
- Activating on a 3rd machine for STANDARD is rejected (2/2 full).

### B4. "Release this machine's seat" ☐

*Setup:* B3 — a key activated on at least one machine.

*Steps:*
1. License page → "Release this machine's seat" button → confirm.
2. Wait for success message.
3. Refresh the License page.

*Expected:*
- License page drops to DEMO (txn_used preserved, plan = DEMO).
- The same key can now be activated on a different machine.
- On the server side, `Seats: N-1 / max` for that key.

### B5. Offline grace period ☐

*Setup:* a paid plan activated within the last 7 days.

*Steps:*
1. Disconnect the test machine from the internet.
2. Restart AccGenie.
3. Try to post a voucher.

*Expected:*
- App boots normally.
- Posting works; the cached license is honored for the 7-day grace.
- The License page shows "Server unreachable — using cached license."
- After 8 days offline, voucher posting falls back to DEMO rules.
  (Don't actually wait 8 days — skip this last step or fake the clock.)

---

## C. Period locking (15 min)

### C1. Lock a date range and try to post inside it ☐

*Setup:* a company with at least one voucher in FY 2025-26.

*Steps:*
1. Settings → Period Locks → "Add Lock".
2. Set range 2025-04-01 to 2025-09-30, comment "Q1+Q2 closed".
3. Try to post a new Receipt dated 2025-08-15.

*Expected:*
- New Receipt is **rejected** with a PeriodLockedError message that
  mentions the lock range.
- The Day Book filter for that range still **shows** existing vouchers
  (read access isn't blocked).

### C2. Edit a voucher to fall inside a locked range ☐

*Setup:* C1 lock still in place. An existing voucher dated 2025-11-15
(outside the lock).

*Steps:*
1. Open the 2025-11-15 voucher for edit.
2. Change the date to 2025-08-15 (inside the lock).
3. Save.

*Expected:*
- Save is **rejected** with PeriodLockedError. The voucher's date doesn't
  change.
- The same edit with a date of 2025-12-01 (outside the lock) succeeds.

### C3. Cancel a voucher inside a locked range ☐

*Setup:* C1 lock in place. An existing voucher dated 2025-06-01 (inside
the lock).

*Steps:*
1. Open the voucher, click Cancel.

*Expected:*
- Cancel is **rejected** with PeriodLockedError.

### C4. Remove the lock ☐

*Steps:*
1. Settings → Period Locks → delete the lock from C1.
2. Re-try C1 step 3 (post a Receipt in 2025-08-15).

*Expected:*
- Posting now succeeds.
- The audit log records both the lock-add and lock-remove actions.

---

## D. Settings page + persistent prefs (10 min)

### D1. Dr/Cr label style persists across restart ☐

*Setup:* fresh install.

*Steps:*
1. Settings → Dr/Cr label style → switch from **Natural** to **Traditional**.
2. Verify the voucher form's column headers now read "Dr/Cr" (traditional).
3. Close the app completely.
4. Re-launch.

*Expected:*
- After restart, the form still shows traditional labels (not natural).
  This verifies `user_prefs.json` persistence (Phase 4 fix — previously
  it was a global and reset on restart).

### D2. Other Settings cards round-trip ☐

For each setting, toggle, close+reopen the app, and verify it stuck:

- ☐ `after_post_toast` (on/off)
- ☐ `default_voucher_date` (Today vs Last used)
- ☐ `bank_reco_comment_on_ignore` (on/off)
- ☐ `backup_reminder_days` (change from default to e.g. 14)

*Expected:* every setting survives restart. `user_prefs.json` in
`%APPDATA%\AccGenie\` should show the new values.

---

## E. Reports gating (per-report) — NEW in 1.0.5 (15 min)

This is the section that verifies the Excel-baked per-report gating
introduced today. In 1.0.4, "reports" was one feature gating all 7
report pages; in 1.0.5 each report has its own feature.

### E1. FREE plan — no reports visible ☐

*Setup:* a FREE license active (or DEMO that's not yet exhausted, but
DEMO has all reports enabled — for this test edit `pricing.xlsx` so FREE
has Y on `trial_balance` only, re-run baker, rebuild installer — OR test
this section against FREE with all report features blank in the Excel).

*Steps:*
1. Look at the sidebar under REPORTS.

*Expected:*
- All 7 report entries are either **missing** or show as **locked**
  placeholders ("Trial Balance — STANDARD plan required").

### E2. Selectively unlock one report ☐

*Setup:* edit `config\pricing.xlsx` PlanFeatures sheet → set
`trial_balance` FREE column = `Y`, save. Run
`python build\bake_config.py`. Rebuild + reinstall.

*Steps:*
1. Re-launch on FREE plan.
2. Sidebar → REPORTS section.

*Expected:*
- **Trial Balance** is unlocked and opens normally.
- The other 6 report entries are still locked.

> If this fails, the per-report gating in `ui\main_window.py` didn't pick
> up the bake — check that `_baked_config.py` has `'trial_balance'` in
> `PLAN_FEATURES['FREE']`.

### E3. STANDARD plan — all 7 reports unlocked ☐

*Setup:* STANDARD license.

*Steps:*
1. Open each of: Trial Balance, P & L, Balance Sheet, Cash Book, Bank
   Book, Ledger Account, Rcpts & Pmts.

*Expected:* each opens without lock prompts. Data renders.

---

## F. AI features & routing (20 min)

Phase 2a/2b — `byok` vs `ag_key` per feature. Today's
`config\ai_features.xlsx` Features sheet:

| feature_id            | class  |
|-----------------------|--------|
| document_recognition  | byok   |
| bank_statement_ai     | ag_key |
| ledger_statement_ai   | ag_key |
| sales_ai_fill         | ag_key |
| purchase_ai_fill      | ag_key |
| ledger_suggest        | ag_key |
| verbal_entry          | ag_key |

### F1. byok feature locked without a customer key ☐

*Setup:* PRO+ license active, NO Anthropic key in
`config\ai_routing.json` (or Settings → AI Routing).

*Steps:*
1. Try the Document Reader (left sidebar → AI Document Reader).
2. Upload any PDF.

*Expected:*
- Document Reader page either shows a "Customer Anthropic key required"
  banner or refuses to start parsing.
- An obvious link/button "Add your key" leads to the AI Routing dialog.

### F2. ag_key feature works without a customer key ☐

*Setup:* PRO+ license, **no** customer Anthropic key, wallet has at
least 5,00 paise.

*Steps:*
1. Open Bank Reconciliation page.
2. Click "Read with AI" on a sample bank statement.

*Expected:*
- Parse runs to completion via AccGenie's pooled key.
- Wallet balance decreases (check the License page or
  `%APPDATA%\AccGenie\credits.json`).
- A row appears in `AIUsageLog` on the server side (admin check; skip if
  you don't have admin access).

### F3. byok feature works with a customer key ☐

*Setup:* PRO+ license, paste a valid Anthropic key into Settings → AI
Routing → "Your Anthropic key".

*Steps:*
1. Re-try F1's document reader.

*Expected:*
- Parsing completes successfully.
- Wallet balance does **not** decrease (calls go direct to Anthropic
  with the customer key).

### F4. Sales AI-fill orientation regression ☐

*Setup:* PRO+, wallet funded.

*Steps:*
1. Open a new Sales voucher.
2. Type a free-form description ("3 dozen mugs at 250 each, GST 18").
3. Click the AI-fill button.

*Expected:*
- Lines populate in the **correct orientation** (item-by-item rows).
- Each row has correct Dr/Cr side. (This was a Phase B test-feedback fix
  in commit `ca85699`.)

### F5. txn_used counter no longer clobbered by License-page refresh ☐

*Setup:* any plan, voucher count visible on License page.

*Steps:*
1. Note `txn_used` on the License page (e.g. 47).
2. Without closing, open a new Receipt in another window — post it.
3. Go back to the License page → Refresh.

*Expected:*
- Counter now shows **48** (not back to 47). This was the `txn_used`
  clobber bug fixed in `ca85699`.

---

## G. Regression checks — existing features still work (15 min)

These shouldn't be the focus but verify the bake/rewire didn't break
anything.

### G1. Voucher posting (basic) ☐

- ☐ Post a single-line Receipt (Cash → some Income).
- ☐ Post a Payment with GST split (intra-state — CGST + SGST appear).
- ☐ Post an inter-state Sales (IGST appears).
- ☐ Post a Journal where Dr ≠ Cr — should be rejected.
- ☐ Post a Contra (Cash → Bank).

### G2. Day Book renders ☐

- ☐ Day Book lists today's vouchers.
- ☐ Click a row → it opens for view; F2 enters edit mode.
- ☐ Filter by date range works.

### G3. Ledger Balances ☐

- ☐ Ledger Balances page shows all ledgers by default (1.0.3 change).
- ☐ F2 / F3 navigation between ledgers works.
- ☐ Click a balance → drills into the ledger account view.

### G4. Bank Reconciliation ☐

- ☐ Import a CSV / Excel bank statement.
- ☐ Import a `.xls` (legacy Excel) statement — verifies xlrd 1.2.0
      worked (was broken before the QoL fix in `afe772d`).
- ☐ Auto-match a few lines; verify opening/closing balance shown.
- ☐ Mark a line "Cleared" → it appears in the Cleared column.

### G5. SmartDateEdit shortcuts ☐

In any voucher form's date field, verify these inputs work:
- ☐ `12` → today's month/year, day 12
- ☐ `12/5` → day 12, May, this year
- ☐ `12/5/26` → 12 May 2026
- ☐ `12 may` → 12 May this year
- ☐ `today` / `t` / `.` → today
- ☐ `y` → yesterday
- ☐ `tom` → tomorrow
- ☐ `+`/`-` keys → next/prev day
- ☐ `[`/`]` → prev/next month
- ☐ `F4` → opens calendar picker

### G6. Backup & restore ☐

- ☐ Settings → Backup → "Backup now" → writes a `.zip` to chosen path.
- ☐ Restore from that `.zip` on a different empty company → all data
  reappears.

---

## H. NOT in this build — DO NOT test (skip)

These are tracked but not yet implemented in 1.0.5. Skipping saves you
time; testing them will only confuse the results.

- ❌ **`print` feature gating.** The `print` feature row is in
  `pricing.xlsx` PlanFeatures sheet but no UI code currently checks it.
  Print buttons on reports will work for everyone regardless of the Y
  mark.
- ❌ **`email_report` feature gating.** Same — placeholder only, no UI
  wiring.
- ❌ **AI page-cost calculation.** The Countries sheet has
  `ai_text_page_cost` / `ai_scanned_page_cost` /
  `ai_per_transaction_cost` columns, but the `/ai/proxy` endpoint
  currently meters by Anthropic tokens, not pages. The values you see
  in the Excel are intent only — nothing reads them yet (task #13).
- ❌ **Multi-currency display.** The Countries sheet has currency_code
  and currency_symbol, but the upgrade UI only reads INR pricing today.

---

## I. Reporting results

For each section A–G, record one of:

| Section | Result | Notes |
|---------|--------|-------|
| A. Install/upgrade   | ☐ pass ☐ fail | |
| B. License & seats   | ☐ pass ☐ fail | |
| C. Period locks      | ☐ pass ☐ fail | |
| D. Settings prefs    | ☐ pass ☐ fail | |
| E. Reports gating    | ☐ pass ☐ fail | |
| F. AI routing        | ☐ pass ☐ fail | |
| G. Regressions       | ☐ pass ☐ fail | |

For any failures, capture:

1. The exact step that failed.
2. The actual vs expected behavior.
3. A screenshot or the console traceback (run `AccGenie.exe` from
   `cmd.exe` to see console output if needed).
4. The version on the badge in About / License page.
5. The contents of `%APPDATA%\AccGenie\license.json` (redact the key)
   and `user_prefs.json`.

Mail those to yourself; they're enough for me to debug remotely.
