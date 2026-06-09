# GST on sales & purchases (and GST returns)

*(GST features are on the higher plans, India.)*

## How GST is split — the key rule
When you post a Sales or Purchase and choose a GST rate, Accounts HQ splits the tax based on
**your company's state code vs. the party's state code**:
- **Same state (intra-state):** tax splits into **CGST + SGST/UTGST** (half each), as
  separate ledger lines.
- **Different state (inter-state):** the full tax goes to **IGST** on one line.

So the split is only correct if **every customer/vendor ledger has the right 2-digit state
code**. If a party has no state code, the app assumes intra-state (your own state) — which can
silently mis-flag an inter-state invoice. **Fix: set the state code on every party ledger.**

## GST rates
Pick from the standard slabs: **0, 5, 12, 18, 28%**. The tax amount = base × rate.

## HSN / SAC
You can set an **HSN/SAC code** on item/sales ledgers. It feeds the **HSN Summary** report,
which groups sales by HSN code and rate for your return.

## GST reports / returns
On the higher plans you get GST report screens to prepare your filing:
- **GSTR-3B** — monthly summary
- **GSTR-1** — outward supplies
- **HSN Summary**
- **GSTR-2B reconciliation** — match your purchases against the portal's 2B
- **GST Returns** summary

Each computes the CGST/SGST/IGST figures from your posted vouchers and exports for the GST
portal. Accounts HQ **prepares** the numbers — you (or your CA) file them on the portal.

## Note
Accounts HQ records and computes GST from the rates and state codes you set. It is **not a
filing engine** and does not give tax advice — confirm rates and treatment with your CA.
