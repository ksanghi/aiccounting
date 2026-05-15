# AccGenie / RWAGenie Roadmap

Forward-looking work items captured outside the source tree. Each entry has
a short rationale so future-me (or you, after a gap) can pick it up cold.

Status legend:
- 🔴 not started
- 🟡 in progress
- 🟢 done (move to changelog / commit history when this list gets long)

---

## 1. GST & TDS — provide our own filing flow 🔴

**Why now:** licensees have started asking what GST/TDS support actually
means in AccGenie. Today the engine *captures* GST splits (CGST/SGST/IGST
via state codes) and TDS deductions (via TDS sections + thresholds) on
each voucher, and the GST Summary / TDS Reports pages can produce
period summaries. We do **not** generate filing-ready outputs.

**Scope of work:**

- **Research what others offer** before scoping our own. Compare against:
  - Tally Prime (GSTR-1, GSTR-3B JSON export, e-invoice push)
  - Zoho Books (filing dashboard, ITC matching)
  - Cleartax / Razorpay invoicing / Vyapar
- **Decide build vs partner.** GST e-invoice IRP integration is a hard
  problem — IRN generation, QR code, signed JSON — usually it's worth
  using a GSP (GST Suvidha Provider) like Cleartax, IRIS, or Cygnet.
  Build a thin adapter, not the GSTN auth flow from scratch.
- **Deliverables (likely PRO+ tier):**
  - GSTR-1 export (JSON for offline tool / direct push via GSP)
  - GSTR-3B summary
  - 2A / 2B reconciliation (matching purchase ITC)
  - TDS Form 26Q / 24Q generation (text format for FUV)
  - TDS Certificate (Form 16A) PDF
- **GST e-invoicing:** required for B2B turnover > ₹5 cr. Defer until a
  paying customer needs it; integrate via a GSP at that point.

**Open questions for the user:**

- Which segment is highest priority — proprietorships (TDS mostly N/A,
  GST often composition scheme) or small Pvt Ltds (full filing)?
- Are we willing to white-label a GSP, or do we want our own IRP
  registration (massive compliance overhead, not recommended)?

---

## 2. Number / currency separators per territory 🔴

**Why now:** the desktop hard-codes Indian-style separators
(`₹ 1,23,456.78` — 2-3-3 grouping). Selling outside India needs Western
grouping (`$ 123,456.78`), AED, etc. The `config/pricing.xlsx` Countries
sheet already has `currency_code` + `currency_symbol` per country, so
half the model exists.

**Scope of work:**

- Add `decimal_separator` and `thousands_separator` and `grouping`
  (`[3,2]` for India, `[3]` for US/EU) columns to the Countries sheet.
- A `core/locale_fmt.py` helper: `format_amount(value, country_code)`
  reads the country row from the baked config and applies the right
  grouping.
- Replace every `f"₹{x:,.2f}"` / `f"Rs.{x:,.2f}"` site (there are dozens)
  with the helper. Use grep — likely 60-80 call sites.
- Date formats too while we're at it: `dd-MMM-yyyy` (India) vs
  `MM/dd/yyyy` (US) vs `dd/MM/yyyy` (UK / commonwealth).

**Effort:** half-day in the helper + half-day grep-and-replace. Low
risk if we keep the helper signature compatible.

---

## 3. Vertical plug-in architecture — RWA is the first 🔴

**Context (this is the big one):** AccGenie was always the *backend*
engine. The product the customer actually buys is a **business
front** — RWAGenie is the first, but the architecture must allow
**any other business front to plug in later** (schools, clinics,
retail shops, NGO trust accounts, cooperative banks…). One active
vertical per company.

### Architectural contract (define this before writing any RWA code)

The accounting engine (`core/`, `ui/voucher_form.py`, the eight
voucher types, GST/TDS, reports) stays generic — never imports
anything vertical-specific. Verticals are plug-ins that sit *on top*
of the engine and contribute:

| What a vertical contributes | Where |
|---|---|
| Domain models (e.g. `flats`, `students`, `patients`) | Per-vertical SQLite tables in the same company DB, namespaced (e.g. `rwa_flats`, `school_students`). |
| Sidebar sections + pages | A `register(main_window, db, company_id, tree, engine)` entry point the vertical implements. |
| Ledger / voucher templates | Vertical seeds (e.g. RWA seeds Sundry Debtor ledgers per flat at setup). |
| Scheduled / background jobs | Auto-billing for RWA, fee-due cron for schools. |
| Custom reports | Plug into the existing reports framework. |
| License feature gates | Feature IDs prefixed (`rwa_*`, `school_*`) — the existing `lmgr.has_feature()` already supports arbitrary IDs, so no engine change is needed. |

### One vertical per company (not per install)

- Same installer ships AccGenie engine + all available verticals.
- `companies` table gets a new `vertical` column (values:
  `"accounting"`, `"rwa"`, `"school"`, …; `NULL` = generic
  accounting only).
- Company-setup dialog asks "What kind of business?" — answer
  locks the vertical for that company. Cannot change later without
  data migration (verticals don't share their domain tables).
- Different companies in the same install **may** run different
  verticals. (A consultant using AccGenie for their CA practice
  can have an RWA company and a clinic company side by side.)
- The active vertical's `register()` runs after the engine boots,
  bolting its pages onto the sidebar before `MainWindow` shows.

### Code layout to set up now (so RWA doesn't tangle the engine)

```
core/                ← engine, unchanged
ui/                  ← generic accounting UI, unchanged
verticals/
  __init__.py        ← registry + Vertical base class
  rwa/
    __init__.py      ← register(main_window, ...) entry point
    models.py        ← rwa_flats, rwa_owners, rwa_visits, ...
    pages/           ← member_directory, notice_board, ...
    services/        ← auto_billing, late_fee_rules, ...
  school/            ← future
  clinic/            ← future
```

The `verticals.registry` is a dict literal — adding a new vertical
is: drop the package in, append one line to the registry, ship.

### Pricing model implications

Each vertical likely needs its own price table (RWA Free/Std/Pro/
Premium ≠ AccGenie Free/Std/Pro/Premium). Two reasonable options
when this gets built:

- **A. Per-vertical tier sheet** in `config/pricing.xlsx`: add
  `Tiers_RWA`, `Tiers_School`, etc. Each company picks a vertical
  → picks a tier from that vertical's sheet. Cleanest if verticals
  diverge a lot.
- **B. `product` column on Tiers**: one tier list, each row tagged
  with which product it belongs to. Simpler if verticals share
  most pricing logic.

Decide when ready to build. Both work with the existing baker.

---

## 3a. RWAGenie — the first vertical 🔴

### Pricing (per the operator's spec)

| Tier | Price (INR/year) | Flats limit |
|---|---|---|
| Free | ₹0 | up to 300 |
| Standard | ₹2,999 | up to 1,000 |
| Pro | ₹5,999 | up to 2,500 |
| Premium | ₹14,999 | unlimited |

**Note:** these are RWAGenie prices and **don't replace** the AccGenie
pricing in `config/pricing.xlsx`. AccGenie's tier prices stay as they
are (1999/4999/9999). The two products will likely ship as a bundled
RWAGenie installer that includes AccGenie as the engine, billed under
RWAGenie's SKUs. Decide later how to model this in the baked tier
table (option A: keep both, with a `product` column; option B:
separate `pricing_rwa.xlsx` baked alongside).

The `flats_limit` per tier is captured here for now; when the build
starts, add `flats_limit` as a column on the Tiers sheet (parallel to
the existing `txn_limit`).

### Feature list (cleaned, deduplicated)

The operator's input sheet (`File exchange/RWA features.xlsx`) mixed
two formats — a tier matrix on the left and a category/priority list
on the right. Combined and tier-mapped:

**Core (Free+, every tier):**
- Flat-wise ledger
- Receipt tracking
- Member directory
- Notice board
- Complaint tracking
- Broadcast messaging
- Polls
- Visitor pass management
- Basic reports (collection summary, dues outstanding)

**Standard (₹2,999/y) — adds:**
- Auto-billing (monthly maintenance invoice generation)
- Late-fee rules
- Facilities booking (clubhouse / hall / parking)
- Asset register (building assets, AMC tracking)
- Advanced reports

**Pro (₹5,999/y) — adds:**
- Invoice WhatsApp reminders
- Document storage (society bye-laws, AGM minutes, audit reports)
- Vendor management (regular suppliers, AMC vendors, AGM voting)

**Premium (₹14,999/y) — adds:**
- (operator left this blank; suggestions for placeholder:
  custom reports, multi-society management for managing committees,
  audit-ready exports, API access)

**Differentiator (priority Low):**
- WhatsApp export

### How this maps to features.xlsx today

I've added all 16+ items above as new rows in
`config/pricing.xlsx` PlanFeatures under a new **RWA** category, with
the same DEMO/FREE/STANDARD/PRO/PREMIUM column structure AccGenie
already uses. That gives the gating framework — `lmgr.has_feature("rwa_auto_billing")`
checks will work the moment the feature code exists.

### Implementation order (when the build starts)

This is multi-week. Suggested phasing:

1. **Flat-wise ledger** — wire the existing AccGenie ledger system to
   a per-flat naming convention. New table `flats` (flat_no, owner_name,
   block, area_sqft, ownership_type). Each flat auto-creates a Sundry
   Debtor ledger.
2. **Member directory + notice board** — basic CRUD pages, no payment.
   This is the visible-to-residents shell.
3. **Auto-billing** — schedule monthly maintenance invoice posting.
   Templates per flat (or per area_sqft × rate). Triggers via
   `core/voucher_engine` build_sales().
4. **Facilities booking + late fees + asset register** — STANDARD-tier
   features.
5. **WhatsApp** — needs a provider (Twilio India, WATI, Gupshup).
   Research costs + sandbox-vs-prod approval. Likely 2-3 weeks of
   compliance work alone.
6. **Document storage + vendor mgmt** — PRO-tier features.

**Risk:** WhatsApp Business API approval can take 1-2 months. Start
the application *before* the feature build is needed.

---

## Already on the list (not new today)

- 🔴 Wire AI page costs into actual billing — `config/pricing.xlsx`
  Countries sheet has `ai_text_page_cost` / `ai_scanned_page_cost` /
  `ai_per_transaction_cost` columns, but no code reads them. Today's
  `/ai/proxy` meters by Anthropic tokens. Decide: drop the page-cost
  columns OR rewire metering. (Task #13 in the running task list.)
- 🔴 Pricing page + checkout flow — desktop's Upgrade button currently
  uses mailto: to `info@ai-consultants.in` (placeholder). The server
  has the Razorpay create-order + webhook endpoints built but unwired
  (env vars empty). Need: Razorpay account, accgenie.in DNS, SMTP
  credentials, deploy. See
  `memory/project_payment_gateway_pending.md`.
- 🔴 License port-abuse cooldown — seat-release endpoint can be abused
  for license sharing. Add a per-key cooldown (e.g. one release per
  24h) + ops alert at release rate threshold.
- 🔴 Subscription / auto-renewal — currently each license is a one-year
  prepaid sale. Razorpay Subscriptions exist; explicit decision needed
  on whether the friction is worth it.

---

## Done recently (last 30 days, for context)

- 🟢 v1.0.7 (2026-05-15) — Tally migration: Dr/Cr sign convention
  fix; Ledger Balances perf (N+1 → 1 query); BS Income−Expense
  rollup; Save dialog one-click; forgiving migrator.
- 🟢 v1.0.6 (2026-05-15) — Excel-baked operator config (xlsx →
  Python); Razorpay scaffolding on the server; per-report gating;
  has_feature stale-cache fix.
- 🟢 v1.0.5 (2026-05-15) — first Excel-baked installer; DEMO trial
  capped at 50 vouchers.
- 🟢 v1.0.4 multi-phase rework (2026-05-13) — license seats, period
  locks, settings prefs, AI routing.
