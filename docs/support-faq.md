# AccGenie — Support FAQ

A growing list of real customer questions and answers, curated for reuse on
the public website, in support replies, and as in-app help.

Conventions:
- One question per `##` heading.
- Add new entries at the bottom; never rewrite history.
- Each entry ends with metadata: `_Asked: YYYY-MM-DD · Tags: …_`

---

## How do I migrate a company from Tally 9.1?

AccGenie has a built-in 4-step migration wizard. **Important caveat first:**
it imports the **chart of accounts + opening balances**, NOT past
transactions. That's the standard year-end migration pattern — close books
in Tally, those closing balances become AccGenie's opening balances, and
AccGenie runs fresh from your cut-over date. Bringing many years of vouchers
across is a separate, much larger project.

### Caveat re: Tally 9.1 specifically

The XML parser is written against **Tally Prime / Tally ERP 9** (newer
flavours). Tally 9.1 (circa 2007) is older and its XML *may* differ slightly
in tag layout. Approach:

1. **First try the Tally XML path.** If it parses cleanly, you're done.
2. **If it fails,** fall back to **Excel** — Tally 9.1 can dump masters to
   Excel/CSV directly, and AccGenie's Excel parser is more forgiving
   (header-name sniffing, accepts many synonyms).

### Step 1 — Export from Tally 9.1

**Option A — XML (try first):**
- *Gateway of Tally* → *Display* → *List of Accounts*
- Press `Alt+E` (Export)
- Choose **XML** as the format and save the file.

**Option B — Excel (fallback if XML fails):**
- *Gateway of Tally* → *Display* → *Account Books* → *Group Summary* (or
  *Ledger*)
- `Alt+E` → choose Excel / CSV. Include at minimum: ledger name, group,
  opening balance, Dr/Cr type. Optional but useful: GSTIN, PAN, State, bank
  a/c, IFSC.

### Step 2 — Launch AccGenie and start the wizard

Two entry points:

| When | How |
|---|---|
| **Fresh install / new company** | At the company-selector dialog, click **"Create & Migrate"** instead of "Create" — wizard auto-opens after the company is created. |
| **Already inside the app** | Sidebar → **DATA section → Migration** page → **Run wizard**. *Target company must have zero vouchers* — the wizard refuses otherwise. |

### Step 3 — Walk the 4-step wizard

1. **Source format** — pick `Tally XML` (or `Excel chart of accounts` for
   the fallback).
2. **File** — drag-drop or browse to the exported file.
3. **Dry-run preview** — counts and warnings (e.g. *"12 groups, 145
   ledgers, 3 unrecognised parents"*). Review carefully before applying.
4. **Apply** — commits to the company DB. Logged to `migration_runs`.

### Step 4 — Verify

- Daybook should be empty (correct — no vouchers imported).
- Trial Balance should match Tally's closing trial balance as of your
  cut-over date.
- Spot-check a few ledgers: a debtor, a creditor, the cash account, GST
  input/output accounts.

### If it fails

Common Tally 9.1 issues, ranked by likelihood:

1. **XML uses different tag names than Tally Prime.** Send us the error from
   step 3 — small format deltas are quick to adapt in
   `core/migration/tally_xml.py`.
2. **Group hierarchy mismatch.** Tally 9.1 had slightly different default
   groups (e.g. *Sundry Debtors* nesting under a different parent). The
   wizard warns; you can either rename in Tally or let the importer
   auto-create.
3. **GSTIN fields missing in 9.1.** Tally 9.1 predates GST (which went live
   July 2017), so the exports won't carry GSTINs. Fill them in via the
   Excel route, or add them manually in AccGenie after import.

_Asked: 2026-05-11 · Tags: migration, tally, tally-9.1, onboarding_
