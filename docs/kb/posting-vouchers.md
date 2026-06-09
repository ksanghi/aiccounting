# Posting vouchers

Go to **Post Voucher** in the sidebar (also a quick action on Home).

## The 8 voucher types
- **Payment** — money going out (bank/cash credited, party/expense debited)
- **Receipt** — money coming in (bank/cash debited, party/income credited)
- **Contra** — moving money between your own cash/bank accounts
- **Journal** — free-form, any number of debit/credit lines
- **Sales** — a sale (can auto-split GST)
- **Purchase** — a purchase (can auto-split GST)
- **Debit Note** / **Credit Note** — returns / allowances

## Posting a simple voucher (Payment / Receipt / Contra / Sales / Purchase)
1. Pick the **voucher type**.
2. Set the **date** (it can "stick" to the last-used date — see Settings).
3. Choose the **bank/cash** ledger (paid from / received into).
4. Choose the **party/expense/income** ledger and enter the **amount**.
5. For Sales/Purchase, pick the **GST rate** (0/5/12/18/28%) — the app splits CGST+SGST or
   IGST automatically (see *GST*). TDS is applied if the vendor ledger is set up for it
   (see *TDS*).
6. Add a **narration** and **reference** (e.g. cheque no.) if you like.
7. The live totals show **Dr**, **Cr** and the difference.
8. Click **Post**. The voucher must balance (Dr = Cr) or it won't post.

## Journal vouchers
Use **Journal** for entries that don't fit the simple forms. Add rows freely — each row is
a ledger with a debit or credit amount. Dr must equal Cr to post.

## Multi-party payment / receipt
Paying or receiving across several parties in one go? Use the **multi-party** option: one
bank/cash line and several party lines; the app totals them for you.

## Creating a ledger on the fly
If the party/ledger doesn't exist yet, create it from the ledger picker without leaving the
form. Set its group, opening balance, and (for parties) GSTIN/state code, and (for vendors)
TDS section if applicable.

## Editing or deleting a voucher
- Go to **Day Book**, select the voucher, and click **Edit** (or double-click it). Make
  changes and **Update**.
- **Delete** marks the voucher cancelled (soft delete — it stays in the audit trail).
- A voucher that has been **reconciled** (matched in bank/ledger reconciliation) is
  protected — you'll be warned; unreconcile it first if you really need to change it.
- A voucher whose date falls in a **locked period** can't be edited or posted (see
  *Settings, plans & period locks*).

## Bill-wise (against-reference) allocation
On a Payment/Receipt you can tag **which invoices** it settles: open **Bill Allocations**,
pick the party's outstanding bills and allocate amounts (one payment can settle several
bills). Track the result in the **Bill-wise Outstanding** report. *(Bill-wise is a higher-plan
feature.)*
