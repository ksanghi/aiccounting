# Migrate from Tally / Busy / Excel

*(Migration is on the higher plans.)* Bring an existing business onto Accounts HQ via the
**Migration** screen (or **Create & Migrate from another system…** in the company selector).

## What comes over
Migration imports your **chart of accounts (groups + ledgers) and their opening balances** —
the snapshot you start from. It does **not** import historical transactions; those stay in
your old system for reference. Accounts HQ is your book **going forward** from the opening
balances.

## Sources
- **Tally** — export from Tally and import the file
- **Busy**
- **Excel / CSV** — using the template (map your columns to ledger name, group, opening
  balance, etc.)
- **Zoho Books / QuickBooks** where offered

## Steps
1. Open the **Migration** wizard.
2. **Pick the source** and upload the file (or connect, for cloud sources).
3. **Map the columns** (for Excel) so the app knows which column is the ledger name, group,
   opening balance, etc.
4. **Preview** what will be imported — groups, ledgers, opening balances.
5. **Confirm** — the app seeds the ledgers and sets opening balances.

## Good to know
- Migration is meant for a **fresh/empty company** (before you've posted vouchers).
- After importing, check your **Trial Balance** — the opening balances should match your old
  system's closing position.
- The **Migration** screen keeps a history of past runs (source, file, counts, any errors).
