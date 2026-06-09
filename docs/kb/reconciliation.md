# Bank & ledger reconciliation

*(Reconciliation is on the higher plans.)* Two screens: **Bank Reconciliation** (for a
bank/cash ledger) and **Ledger Reconciliation** (for any other ledger, e.g. a vendor
account). Both work the same way, in three steps.

## Step 1 — set up & import
1. Open **Bank Reconciliation** (or **Ledger Reconciliation**).
2. Pick the **ledger** to reconcile.
3. Set the **period** (From / To).
4. Select your **statement file** — CSV, Excel, PDF or OFX for bank; CSV/Excel for ledger.
   (PDF/image statements can be read by AI if you've added your own AI key.)
5. Click **Upload & Import**.

## Step 2 — review & match
You'll see three tabs:
- **Matched** — statement lines already paired with your vouchers (the app auto-matches by
  amount and date where it can).
- **Unmatched statement** — lines from the file with no voucher yet.
- **Unmatched book** — your vouchers with no statement line yet.

For each unmatched statement line you can:
- **Match** it to a book voucher (drag/click). One statement line can settle **several**
  vouchers (1-to-many) — e.g. a lump-sum bank debit covering three invoices.
- **Create Voucher** inline — pick the other ledger and amount, and it posts a
  Payment/Receipt and matches it.
- **Ignore** — mark it reconciled without posting (you may be asked for a comment, for the
  audit trail).

## Step 3 — finalise
The summary shows **statement balance, book balance, and the difference**. When the
difference is right, click **Finalise** to lock the reconciliation — matched vouchers are
marked reconciled.

## Good to know
- A **reconciled voucher is protected** from editing. If you must change it, undo the match
  first.
- Auto-match looks at amount + date (within a couple of days) and can suggest the usual
  counter-ledger based on your history.
