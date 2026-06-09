# TDS on payments

*(TDS features are on the higher plans, India.)*

## Setting up a vendor for TDS
TDS is driven by the **vendor's ledger settings**. Open the vendor ledger and set:
- **TDS applicable** = yes
- the **TDS section** (e.g. 194C contractors, 194I rent, 194J professional fees, 194H
  commission, etc.)
- the **TDS rate** for that section

Once set, when you make a Payment to that vendor, Accounts HQ deducts TDS automatically and
posts it to the **TDS Payable** ledger.

## Thresholds
Each section has a threshold below which TDS doesn't apply. The app applies TDS when the
amount crosses the section's threshold — so a payment just under the threshold won't deduct.
Keep this in mind if you expect a deduction and don't see one.

> Exact section rates and thresholds change with the Finance Act. Accounts HQ applies the
> rate set on the ledger — **confirm current rates/thresholds with your CA**. The app does
> not give tax advice.

## Reports
- **TDS Reports** and **TDS Register** show deductions by section and party, so you can
  reconcile what you deducted against what you paid/filed.

## Common question
**"I expected TDS but it didn't deduct."** Check three things: (1) the vendor ledger has TDS
applicable + a section + a rate; (2) the payment amount is **above** the section threshold;
(3) you're on a plan that includes TDS.
