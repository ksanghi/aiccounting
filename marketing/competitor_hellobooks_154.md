# HelloBooks.ai vs Accounts HQ — 154-feature matrix

> Status: research snapshot. Not customer-facing. Source for future
> roadmap inspiration when AHQ builds a US version.
>
> Date: 2026-06-01
> Methodology: HelloBooks does not publish a discrete 1-of-154 list.
> Rows reconstructed from hellobooks.ai (main, /features, /pricing) +
> sub-brand sites (pay., reports., expenses., connect., procure.) +
> third-party listings (Capterra, SoftwareAdvice). Treat row count as
> indicative, not literal.

## Summary

- Total HelloBooks features enumerated: **154**
- AHQ PRO covers: **~52 / 154**
- AHQ PREMIUM covers: **~58 / 154** (PRO set + WhatsApp + API + verticals + user mgmt + audit_export)
- HelloBooks features AHQ does **NOT** have: **~96**
- AHQ features HelloBooks does **NOT** have: **11**

Adjusted view after stripping rows that are definitionally US-only or
cloud-rails-only (and therefore worthless to Indian customers):
**adjusted addressable gap ≈ 127 features; AHQ PREMIUM covers ~58 ≈ 46%.**

## Top 5 HelloBooks features AHQ should consider building

1. **AI Accounting Agent + CFO Agent** — natural-language chat over the entire ledger ("What did I spend on travel last quarter?"). HB's most-marketed feature. AHQ has voice→voucher but no chat over books.
2. **AP aging report** — trivial mirror of receivables_aging on the payables side.
3. **Recurring invoice + payment-link** — Razorpay integration already exists in licensing flow; lift it into invoicing.
4. **Cash Flow Statement (formal)** — receipts_payments is cash-basis but not the same as CFS.
5. **AI auto-categorise with forward learning** — AHQ has confidence scoring but no learn-forward.

## Top 11 AHQ features HelloBooks does NOT have

1. Indian GST engine (CGST/SGST/IGST split by state code, returns)
2. Indian TDS engine (section-aware rates)
3. Busy migration (HB does Tally/QB/Xero but not Busy)
4. 8-voucher Indian taxonomy (Contra, Debit Note, Credit Note as first-class types)
5. Multi-party voucher (one debit/credit, many counter-parties on the other side)
6. Dr/Cr label modes (natural / traditional / accounting) runtime-switchable
7. Voice/text "verbal entry" → voucher
8. Per-company SQLite offline-first (no cloud lock-in)
9. Tally Prime chart-of-accounts seeding (Indian convention)
10. WhatsApp notifications native (HB only as a delivery option)
11. RWA / society-management vertical embedded inside the accounting app

## Full matrix

| # | Category | Feature | HB Free | HB Pro | AHQ PRO | AHQ PREMIUM | Notes |
|---|---|---|---|---|---|---|---|
| 1 | Core Ledger | Chart of accounts (preloaded/AI-mapped) | ✓ | ✓ | ✓ | ✓ | AHQ ships Tally-style DEFAULT_GROUPS + DEFAULT_LEDGERS (Indian convention) |
| 2 | Core Ledger | General ledger | ✓ | ✓ | ✓ | ✓ | |
| 3 | Core Ledger | Journal entries (manual) | ✓ | ✓ | ✓ | ✓ | AHQ has JOURNAL voucher type |
| 4 | Core Ledger | Auto-reversing journal entries | ✓ | ✓ |  |  | AHQ has period lock but no auto-reverse |
| 5 | Core Ledger | Double-entry bookkeeping | ✓ | ✓ | ✓ | ✓ | |
| 6 | Core Ledger | Cash basis / accrual toggle per report | ✓ | ✓ |  |  | India is accrual-default; AHQ does not toggle |
| 7 | Core Ledger | Trial balance | ✓ | ✓ | ✓ | ✓ | AHQ STANDARD+ |
| 8 | Core Ledger | Daybook | ✓ | ✓ | ✓ | ✓ | AHQ Core; HB equivalent in journal log |
| 9 | Core Ledger | Sub-ledger drill-down | ✓ | ✓ | ✓ | ✓ | AHQ ledger_account report |
| 10 | Core Ledger | Multi-currency with live FX rates | ✓ | ✓ |  |  | AHQ INR-only today |
| 11 | Core Ledger | Auto FX gain/loss calc | ✓ | ✓ |  |  | |
| 12 | Core Ledger | Period close (guided checklist) | ✓ | ✓ | ✓ | ✓ | AHQ has period lock + book lock |
| 13 | Core Ledger | Period lock after close | ✓ | ✓ | ✓ | ✓ | |
| 14 | Core Ledger | Fiscal year management | ✓ | ✓ | ✓ | ✓ | |
| 15 | Core Ledger | Closing entries (auto) | ✓ | ✓ |  |  | AHQ does not auto-post closing |
| 16 | Core Ledger | Adjusting entries (accrual/deferral) | ✓ | ✓ | ✓ | ✓ | Via manual JOURNAL voucher |
| 17 | Core Ledger | Retained earnings auto-transfer | ✓ | ✓ |  |  | |
| 18 | Core Ledger | Audit trail (immutable log) | ✓ | ✓ | ✓ | ✓ | AHQ PREMIUM = audit_export |
| 19 | Core Ledger | Multi-entity / multi-company | ✓ | ✓ | ✓ | ✓ | AHQ = per-company SQLite DB |
| 20 | Core Ledger | Multi-entity consolidation | * | ✓ |  |  | HB Free limited; AHQ no consolidation |
| 21 | Core Ledger | Intercompany elimination | * | ✓ |  |  | |
| 22 | Bank | Bank feeds via Plaid (11,000+ banks) | ✓ | ✓ |  |  | US-only banks; no Indian equivalent in HB |
| 23 | Bank | Credit card feeds | ✓ | ✓ |  |  | |
| 24 | Bank | AI bank reconciliation (95%+ auto-match) | ✓ | ✓ | ✓ | ✓ | AHQ STANDARD = bank_reconciliation + bank_reco_split (manual+AI-assisted) |
| 25 | Bank | Bank reco split | ✓ | ✓ | ✓ | ✓ | AHQ STANDARD |
| 26 | Bank | Ledger reconciliation (vendor/customer) | ✓ | ✓ | ✓ | ✓ | AHQ STANDARD = ledger_reconciliation + ledger_reco_split |
| 27 | Bank | Free plan bank-feed limit (1 bank + 1 card) | * | ✓ |  |  | HB Free is limited here |
| 28 | Invoicing | Create/send invoices | ✓ | ✓ | ✓ | ✓ | AHQ SALES voucher |
| 29 | Invoicing | Unlimited invoices | ✓ | ✓ | ✓ | ✓ | |
| 30 | Invoicing | Invoice templates | ✓ | ✓ | ✓ | ✓ | |
| 31 | Invoicing | Custom branding / logo on invoice | ✓ | ✓ | ✓ | ✓ | |
| 32 | Invoicing | Recurring invoices | ✓ | ✓ |  |  | AHQ has auto_billing in PRO — partial overlap |
| 33 | Invoicing | Quotes / estimates | ✓ | ✓ |  |  | AHQ has no quote module |
| 34 | Invoicing | Sales orders | ✓ | ✓ |  |  | |
| 35 | Invoicing | Quote -> sales order -> invoice flow | ✓ | ✓ |  |  | |
| 36 | Invoicing | Invoice status tracking (sent/viewed/paid) | ✓ | ✓ |  |  | |
| 37 | Invoicing | Auto payment reminders / dunning | ✓ | ✓ |  |  | |
| 38 | Invoicing | Real-time view/pay notifications | ✓ | ✓ |  |  | |
| 39 | Invoicing | Email invoice delivery | ✓ | ✓ | ✓ | ✓ | AHQ email_report (STANDARD) |
| 40 | Invoicing | WhatsApp invoice delivery |  |  |  | ✓ | AHQ PREMIUM has whatsapp; HB does not advertise WA delivery |
| 41 | Invoicing | SMS invoice delivery | ✓ | ✓ |  |  | |
| 42 | Invoicing | Online payment link (Stripe) | ✓ | ✓ |  |  | US payment rails |
| 43 | Invoicing | Square invoicing | ✓ | ✓ |  |  | |
| 44 | Invoicing | Razorpay online payment link | ✓ | ✓ |  |  | HB lists Razorpay for non-US; AHQ has no embedded payment link |
| 45 | Invoicing | Recurring billing engine | ✓ | ✓ | ✓ | ✓ | AHQ auto_billing (PRO) |
| 46 | Invoicing | Custom line items / tax rates | ✓ | ✓ | ✓ | ✓ | |
| 47 | Invoicing | Payment terms | ✓ | ✓ | ✓ | ✓ | |
| 48 | Bills/AP | Bill capture from email forwarding | ✓ | ✓ | * | * | AHQ ai_document_reader (PRO) extracts from upload, not email-fwd yet |
| 49 | Bills/AP | Bill capture from scan/upload | ✓ | ✓ | ✓ | ✓ | AHQ PRO ai_document_reader |
| 50 | Bills/AP | Bill capture from mobile upload | ✓ | ✓ |  |  | AHQ is desktop-only |
| 51 | Bills/AP | OCR data extraction (vendor/date/amount/tax) | ✓ | ✓ | ✓ | ✓ | AHQ PRO |
| 52 | Bills/AP | AI invoice/bill auto-coding to CoA | ✓ | ✓ | ✓ | ✓ | AHQ PRO via ai_document_reader |
| 53 | Bills/AP | Bill-pay automation | ✓ | ✓ |  |  | US ACH rails |
| 54 | Bills/AP | Batch vendor payments | ✓ | ✓ |  |  | |
| 55 | Bills/AP | Cross-border vendor payouts (multi-currency) | * | ✓ |  |  | |
| 56 | Bills/AP | Recurring bills | ✓ | ✓ |  |  | |
| 57 | Bills/AP | Three-way matching (PO/bill/GRN) | * | ✓ |  |  | AHQ has no PO/GRN module |
| 58 | Bills/AP | Purchase orders | * | ✓ |  |  | AHQ PURCHASE voucher exists but no PO doc |
| 59 | Bills/AP | Vendor onboarding / W-9 capture | ✓ | ✓ |  |  | US-specific |
| 60 | Expenses | Expense capture (mobile photo of receipt) | ✓ | ✓ |  |  | AHQ desktop-only |
| 61 | Expenses | OCR receipt scanning | ✓ | ✓ | ✓ | ✓ | AHQ PRO |
| 62 | Expenses | Expense claim grouping | ✓ | ✓ |  |  | |
| 63 | Expenses | Multi-step expense approval workflow | ✓ | ✓ |  |  | AHQ has no employee-expense workflow |
| 64 | Expenses | Approver assignment | ✓ | ✓ |  |  | |
| 65 | Expenses | Expense payment batches | ✓ | ✓ |  |  | |
| 66 | Expenses | Out-of-policy AI flagging | * | ✓ |  |  | |
| 67 | Expenses | Spend vs budget tracking | * | ✓ |  |  | AHQ has no budget module |
| 68 | AI | AI Accounting Agent (NL chat over books) | * | ✓ |  |  | 500 AI credits/mo on Free; AHQ has verbal_entry (voice/text) PRO — narrower scope |
| 69 | AI | AI CFO Agent (NL analytics/reports) | * | ✓ |  |  | |
| 70 | AI | AI auto-categorization (95%+ accuracy) | ✓ | ✓ | ✓ | ✓ | AHQ ai_document_reader categorizes on import |
| 71 | AI | AI learns chart-of-accounts mapping | ✓ | ✓ |  |  | AHQ has confidence scoring but no learn-forward |
| 72 | AI | AI anomaly detection | ✓ | ✓ |  |  | |
| 73 | AI | Voice-to-text data entry |  |  | ✓ | ✓ | AHQ verbal_entry (PRO) — HB does not advertise |
| 74 | AI | AI confidence scoring on extracted vouchers |  |  | ✓ | ✓ | AHQ explicit confidence UI; HB embedded |
| 75 | AI | AI suggests journal entries | ✓ | ✓ |  |  | |
| 76 | AI | AI cash-flow forecasting | * | ✓ |  |  | |
| 77 | AI | AI trend detection | * | ✓ |  |  | |
| 78 | AI | AI credits limit (Free = 500/mo) | * | ✓ |  |  | HB Free metered |
| 79 | Reports | Profit & Loss (P&L) | ✓ | ✓ | ✓ | ✓ | AHQ STANDARD |
| 80 | Reports | Balance Sheet | ✓ | ✓ | ✓ | ✓ | AHQ STANDARD |
| 81 | Reports | Cash Flow Statement | ✓ | ✓ |  |  | AHQ has receipts_payments (cash-basis) but no formal CFS |
| 82 | Reports | AR aging | ✓ | ✓ | ✓ | ✓ | AHQ STANDARD = receivables_aging |
| 83 | Reports | AP aging | ✓ | ✓ |  |  | AHQ has receivables_aging but no payables_aging report |
| 84 | Reports | Sales tax summary | ✓ | ✓ | ✓ | ✓ | AHQ PRO = gst returns |
| 85 | Reports | Cash book | ✓ | ✓ | ✓ | ✓ | AHQ STANDARD |
| 86 | Reports | Bank book | ✓ | ✓ | ✓ | ✓ | AHQ STANDARD |
| 87 | Reports | Ledger account report | ✓ | ✓ | ✓ | ✓ | AHQ STANDARD |
| 88 | Reports | Receipts & payments | ✓ | ✓ | ✓ | ✓ | AHQ STANDARD |
| 89 | Reports | Real-time dashboard (income/expense/profit/cash) | ✓ | ✓ |  |  | AHQ has reports, no live dashboard tile |
| 90 | Reports | Custom report builder (via AI CFO Agent) | * | ✓ |  |  | |
| 91 | Reports | P&L by class / dimension | * | ✓ |  |  | AHQ has no class dimension |
| 92 | Reports | Customer analytics view | * | ✓ |  |  | |
| 93 | Reports | Variance report (month vs month) | ✓ | ✓ |  |  | |
| 94 | Reports | Audit-ready close-of-month reports | ✓ | ✓ | ✓ | ✓ | |
| 95 | Reports | Excel export | ✓ | ✓ | ✓ | ✓ | AHQ STANDARD = export_excel |
| 96 | Reports | PDF export | ✓ | ✓ | ✓ | ✓ | AHQ STANDARD = export_pdf |
| 97 | Reports | Print reports | ✓ | ✓ | ✓ | ✓ | AHQ STANDARD = print |
| 98 | Reports | Email reports | ✓ | ✓ | ✓ | ✓ | AHQ STANDARD = email_report |
| 99 | Reports | CPA-ready trial balance export | ✓ | ✓ | ✓ | ✓ | |
| 100 | Reports | Schedule C / Form 1120-S worksheet export | ✓ | ✓ |  |  | US-tax-form specific |
| 101 | Reports | Real-time financial reporting | ✓ | ✓ | ✓ | ✓ | |
| 102 | Tax (US) | 1099-NEC preparation | ✓ | ✓ |  |  | US-only |
| 103 | Tax (US) | 1099-MISC preparation | ✓ | ✓ |  |  | US-only |
| 104 | Tax (US) | 1096 summary | ✓ | ✓ |  |  | US-only |
| 105 | Tax (US) | 50-state sales tax tracking | ✓ | ✓ |  |  | US-only |
| 106 | Tax (US) | Nexus-aware sales tax rates | ✓ | ✓ |  |  | US-only |
| 107 | Tax (US) | Multi-state nexus monitoring + 30-day alert | ✓ | ✓ |  |  | US-only |
| 108 | Tax (US) | Sales tax registration checklist (auto-gen) | ✓ | ✓ |  |  | US-only |
| 109 | Tax (US) | IRS-aligned chart of accounts | ✓ | ✓ |  |  | US-only |
| 110 | Tax (India) | GST CGST/SGST/IGST split by state code |  |  | ✓ | ✓ | AHQ PRO = gst; HB has no Indian GST |
| 111 | Tax (India) | GST returns generation |  |  | ✓ | ✓ | AHQ PRO |
| 112 | Tax (India) | TDS section-aware rates |  |  | ✓ | ✓ | AHQ PRO = tds; HB has no Indian TDS engine |
| 113 | Voucher Taxonomy | Single "invoice" / "bill" entity | ✓ | ✓ |  |  | HB uses Western entity model |
| 114 | Voucher Taxonomy | 8 Indian voucher types (PAY/RCT/JV/CN/SAL/PUR/DN/CN) |  |  | ✓ | ✓ | AHQ Core; not in HB |
| 115 | Voucher Taxonomy | Contra voucher (bank-cash transfers) |  |  | ✓ | ✓ | AHQ Core |
| 116 | Voucher Taxonomy | Debit/credit note vouchers |  |  | ✓ | ✓ | AHQ Core (HB handles credit memos generically) |
| 117 | Voucher Taxonomy | Sticky voucher date | ✓ | ✓ | ✓ | ✓ | AHQ STANDARD; HB date defaults forward |
| 118 | Voucher Taxonomy | Multi-party voucher (one-to-many split) |  |  | ✓ | ✓ | AHQ STANDARD; HB only single-party |
| 119 | Voucher Taxonomy | Dr/Cr label modes (natural/traditional/accounting) |  |  | ✓ | ✓ | AHQ runtime-switchable; HB fixed |
| 120 | Migration | QuickBooks USA one-click migration | ✓ | ✓ |  |  | HB-only |
| 121 | Migration | Xero migration | ✓ | ✓ |  |  | |
| 122 | Migration | Tally migration | ✓ | ✓ | ✓ | ✓ | AHQ STANDARD = book_migration (Tally) |
| 123 | Migration | Busy migration |  |  | ✓ | ✓ | AHQ STANDARD = book_migration (Busy); HB doesn't list Busy |
| 124 | Migration | Customer/vendor contact import | ✓ | ✓ | ✓ | ✓ | AHQ via book_migration |
| 125 | Migration | Historical transaction migration | ✓ | ✓ | ✓ | ✓ | |
| 126 | Integrations | QuickBooks integration (sync) | ✓ | ✓ |  |  | |
| 127 | Integrations | Xero integration (sync) | ✓ | ✓ |  |  | |
| 128 | Integrations | Tally integration (sync) | ✓ | ✓ |  |  | AHQ has Tally import, not live sync |
| 129 | Integrations | NetSuite integration | ✓ | ✓ |  |  | (via HelloPay) |
| 130 | Integrations | Zoho integration | ✓ | ✓ |  |  | |
| 131 | Integrations | Odoo integration | ✓ | ✓ |  |  | |
| 132 | Integrations | HelloGrowth CRM bridge (lead -> invoice) | ✓ | ✓ |  |  | HB sibling product |
| 133 | Integrations | HelloProcure bridge (PO/RFQ) | ✓ | ✓ |  |  | |
| 134 | Integrations | HelloTime bridge (payroll journal) | ✓ | ✓ |  |  | HB sibling; AHQ has no payroll |
| 135 | Integrations | API access (public) | * | ✓ |  | ✓ | AHQ PREMIUM = api_access |
| 136 | Inventory | Inventory tracking (FIFO/LIFO/weighted avg) | * | ✓ |  |  | AHQ has no inventory module |
| 137 | Fixed Assets | Capex capitalisation | ✓ | ✓ |  |  | |
| 138 | Fixed Assets | Automated depreciation (SL/DB/units) | ✓ | ✓ |  |  | AHQ books depreciation only via JV |
| 139 | Tracking | Class tracking (4 categories x 100 options) | * | ✓ |  |  | |
| 140 | Tracking | Location / sub-location tracking | * | ✓ |  |  | |
| 141 | Tracking | Department tracking | * | ✓ |  |  | |
| 142 | Tracking | Project / job costing | * | ✓ |  |  | |
| 143 | Tracking | Project profitability report | * | ✓ |  |  | |
| 144 | Platform | Cloud-based (web) | ✓ | ✓ |  |  | AHQ is desktop-first, offline; opposite design |
| 145 | Platform | Desktop offline-first (per-company SQLite) |  |  | ✓ | ✓ | AHQ-only |
| 146 | Platform | iOS mobile app | ✓ | ✓ |  |  | |
| 147 | Platform | Android mobile app | ✓ | ✓ |  |  | |
| 148 | Platform | Multi-user (Free up to 3, Pro unlimited) | * | ✓ |  | ✓ | AHQ PREMIUM = user mgmt |
| 149 | Platform | User roles / permissions | ✓ | ✓ |  | ✓ | AHQ PREMIUM |
| 150 | Platform | SOC2 Type II data security | ✓ | ✓ |  |  | AHQ is local-DB, no cloud audit |
| 151 | Platform | Encrypted cloud storage | ✓ | ✓ |  |  | |
| 152 | Platform | Backup | ✓ | ✓ | ✓ | ✓ | AHQ Core |
| 153 | Platform | Cancel anytime / no contract | ✓ | ✓ | ✓ | ✓ | |
| 154 | Verticals | RWA / society management vertical |  |  |  | ✓ | AHQ PREMIUM = verticals (RWA HQ embedded); HB has industry pages but no embedded vertical app |

## Caveat

HelloBooks markets "154 features" but does not publish a discrete
enumerated list. The matrix above is reconstructed from their landing
page, /features, /pricing, blog, Capterra/SoftwareAdvice listings, and
the pay./reports./expenses./connect./procure. sub-brand pages they
claim "ship in the same workspace". Several rows (especially in the
130s/140s) are sub-brand features rolled into the 154 count by HB's
own marketing logic.
