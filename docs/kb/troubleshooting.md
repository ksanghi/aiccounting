# Troubleshooting & common questions

## "It's asking for my licence key again after I updated."
Your data is safe — books live in `…\AppData\Local\Aiccounting\` and aren't touched by an
update. Re-open **License & Plan** and paste your key. If it keeps dropping, contact
`info@ai-consultants.in` with your key. *(Known issue under investigation.)*

## "My voucher won't post."
The most common reasons:
- **Dr ≠ Cr** — the debits and credits must balance. Check the live totals on the form.
- **Locked period** — the voucher date is inside a locked range (see Period Locks).
- A required ledger/amount is missing.

## "GST split as CGST/SGST but it was an inter-state sale (or vice-versa)."
GST is decided by **state codes**: same state → CGST+SGST, different state → IGST. Make sure
**your company state code** and the **party ledger's state code** are both correct. A party
with no state code is treated as intra-state. Fix the ledger's state code and re-post.

## "I expected TDS to be deducted but it wasn't."
Check: (1) the vendor ledger has **TDS applicable + section + rate**; (2) the payment is
**above** that section's threshold; (3) your plan includes TDS. See *TDS*.

## "I can't edit this voucher."
It's probably **reconciled** (matched in bank/ledger reconciliation) and therefore protected,
or its date is in a **locked period**. Undo the reconciliation match, or unlock the period,
then edit.

## "The AI Document Inbox shows an error."
Almost always the **AI key**: it's missing, wrong, expired, or out of credit. AI features are
"bring your own key" — set/replace it in **Settings → AI key**. AI features also need a Pro/
Premium plan.

## "A report looks out of date."
Reports read posted vouchers live — click **Refresh** after posting or fixing an entry.

## "Where is my data / how do I move to another PC?"
Each company is one file: `…\AppData\Local\Aiccounting\data\companies\<company>.db`. Back it
up (Backup & Restore), copy the backup to the new PC, install Accounts HQ there, and restore/
open it. Your data never leaves your machine unless you move it.

## "Can Accounts HQ file my GST/TDS returns?"
No. It **prepares** the figures and exports them for the portal; you or your CA file. It
records and computes — it isn't a filing/compliance engine and doesn't give tax advice.

## Still stuck?
Email **info@ai-consultants.in** with what you were doing and any error text.
