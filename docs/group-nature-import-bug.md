# Accounts HQ — Bug Report: Account groups mis-tagged as ASSET (income/expense hidden from vouchers & misposted to Balance Sheet)

**Date:** 2026-06-26
**Reported from:** live book `data/companies/krishan_sanghi.db` (`company_id = 1`)
**Severity:** High — affects voucher entry *and* financial statement classification (P&L vs Balance Sheet). This is a reconciliation/correctness issue, not cosmetic.

> Note for the developer: the copy I inspected is the **packaged build** (compiled `Accounts HQ.exe`), so the code-level items below are **hypotheses inferred from the data + observed behavior**. Please confirm against the actual source. Everything under "Verified in data" was read directly from the SQLite book.

---

## 1. Symptom (user-facing)

A ledger (e.g. **"Partner's Remuneration"**) that visibly sits under an income group in the chart of accounts does **not** appear in the ledger picker when booking income via a **Sales voucher**.

## 2. Root cause (verified in data)

The ledger picker / voucher engine selects ledgers by their **group's `nature`** column, not by the group's name or tree position. Several groups were stored with the **wrong `nature`** — specifically `ASSET` where they should be `INCOME` (or `EXPENSE`). So a group *named* like income, *positioned* as income, but *tagged* `ASSET`, has all its ledgers excluded from income vouchers — and its balances roll into the **Balance Sheet** instead of the **P&L**.

### Schema involved
`account_groups(id, company_id, name, parent_id, nature, affects_gross_profit)`
`ledgers(... group_id, ...)` — ledger inherits classification from its group.
`nature` observed values: `ASSET | LIABILITY | INCOME | EXPENSE`.

### Concrete example that triggered the report
| ledger | was under group | group `nature` | result |
|---|---|---|---|
| Partner's Remuneration (id 96) | "Direct Income**s**" (id 27) | `ASSET` ❌ | hidden from Sales voucher; sat on Balance Sheet |

There was also a **near-duplicate group**: `22 "Direct Income"` (`INCOME`, correct) vs `27 "Direct Income`**`s`**`"` (`ASSET`, wrong) — two primary groups, almost identical names, different nature.

## 3. Root cause — CONFIRMED: the import/migration path defaults every group's `nature` to ASSET

This is **not** the new-company seed and **not** user error. Evidence from comparing two books on disk:

| | Fresh company (`test_company_123.db`) | Affected book (`krishan_sanghi.db`) |
|---|---|---|
| Group count | 25 (ids 1–25) | 39 (ids 1–39) |
| Groups id ≥ 26 | none | 14 extra (ids 26–39) |
| Income group naming | "Direct Income" / "Other Income" (INCOME ✅) | also has Tally-standard "Direct Income**s**", "Indirect Income**s**" |

A freshly-created company is **clean** (all natures correct). The affected book has the clean seed (1–25) **plus an appended block (ids 26–39)** with genuine Tally-standard names ("Direct Incomes", "Indirect Incomes", "Branch / Divisions", "Misc. Expenses (ASSET)", "Suspense A/c", "Bank OD A/c"). That block was introduced by a **migration/import** (likely AccGenie → Accounts HQ — note `AccGenie.exe`, the old `data/comps/` copy, and the `data/.migrated_from_exedir` marker).

**The defect:** every row in the imported block 26–39 was stored with `nature = 'ASSET'`, regardless of what the group actually is (verified against the pre-fix copy `data/comps/krishan_sanghi.db`). The importer **never sets `nature`; the column defaults to ASSET.** Groups that happen to be assets (Cash-in-hand, Stock-in-hand, Equity Holdings, Mutual Fund, LIC…) looked correct by coincidence; the income/liability/expense groups (27, 28, 31, 35, 39) were silently mis-tagged. It also created income groups that **duplicate** existing seed groups ("Direct Incomes" vs the seed's "Direct Income").

**Who is affected:** any user who **imports or migrates an existing chart of accounts**, not users who create a new company. This is a product bug in the import/migration code, reproducible for everyone using that path.

### Code-confirmed (verified against the `aiccounting` source)

**The defect — `core/migration/migrator.py:384-391`:**
```python
@staticmethod
def _guess_nature(payload, g) -> str:
    """Default nature when the parser doesn't supply one."""
    if g.parent_name:
        for other in payload.groups:
            if other.name == g.parent_name and other.nature:
                return other.nature
    return "ASSET"   # safest fallback   <-- WRONG for primary income/expense/liability groups
```
Called at `migrator.py:275` during group insert: `g.nature or self._guess_nature(payload, g)`. For an imported **primary** group (no `parent_name`) whose parser supplied no nature, this returns **ASSET** unconditionally. That is why every imported group landed on ASSET; the ones that genuinely are assets matched by coincidence.

**Why the parser yields an empty nature:**
- `core/migration/tally_xml.py:195` → `nature = _NATURE_MAP.get(primary.lower(), "")` returns `""` whenever Tally's `<PRIMARYGROUP>` value isn't one of the generic words in `_NATURE_MAP` ("asset/liability/income/revenue/expense…"). Tally primary-group names like "Direct Incomes"/"Indirect Incomes" are **not** in that map → `""`.
- `core/migration/excel_coa.py:203-206, 210-219` → `_norm_nature` yields `""` when the Excel CoA has no/blank/unrecognized Nature column.

Either way the empty nature flows into `migrator.py:275` and hits the ASSET fallback.

**Classification mechanism confirmed — `core/account_tree.py`:**
- `get_income_ledgers()` / `get_income_group_ids()` filter `WHERE g.nature = 'INCOME'`; `get_expense_*` filter `'EXPENSE'`. So a wrong `nature` silently removes the ledger from income/expense voucher pickers and reports — the exact symptom.

**Why new companies are clean — `core/account_tree.py:DEFAULT_GROUPS`:** the seed defines primary income groups with correct natures and uses **"Direct Income"** (singular). The import added Tally's **"Direct Income`s`"** alongside it — `UNIQUE(company_id, name)` didn't catch the duplicate because the strings differ.

### Concrete code fixes (file:line)
1. **`migrator.py:391`** — replace `return "ASSET"` with a name→nature map for the standard Tally primary groups (Direct/Indirect Incomes, Sales, Other Income → INCOME; Direct/Indirect Expenses, Purchase → EXPENSE; Capital, Loans, Current Liabilities, Bank OD → LIABILITY; else ASSET). Only fall back to ASSET for genuinely unknown names, and surface a warning when you do.
2. **`tally_xml.py:50-60, 195`** — extend `_NATURE_MAP` (or resolve via the Tally primary-group hierarchy) so standard primary-group names map to a nature instead of `""`.
3. **`excel_coa.py:203-219`** — when Nature is missing/blank, derive from the standard group name rather than leaving `""`.
4. **Dedupe on import** — normalize incoming standard names against existing seed groups (singular/plural) so "Direct Incomes" maps onto the seed's "Direct Income" instead of creating a twin.
5. **Defensive read path (optional)** — in `account_tree.py`, resolve a ledger's nature by walking to its root primary group instead of trusting the immediate group's stored `nature`.

### Supporting hypothesis (still worth fixing): manual sub-group creation
- Sub-groups should **inherit (and not override) their primary parent's nature** (Tally-style). Confirm the create-group UI/code does this and does not default to `ASSET`.

**Recommended fixes:**
0. **PRIMARY — fix the import/migration path:** set each imported group's `nature` explicitly from the source data, or derive it from the (Tally-standard) group name; **never let it default to `ASSET`**. Map the standard primary groups correctly (Direct Incomes / Indirect Incomes / Sales / Other Income → INCOME; Direct Expenses / Indirect Expenses / Purchase → EXPENSE; Loans / Bank OD / Current Liabilities / Capital → LIABILITY; etc.). Also **dedupe against existing seed groups** so the import doesn't create "Direct Incomes" next to the seed's "Direct Income".
1. **Sub-group creation:** force `nature = parent.nature` and disable editing it for non-primary groups (matches Tally semantics). Do not let the UI default sub-groups to `ASSET`.
2. **Primary group creation:** require an explicit `nature`; never silently default to `ASSET`.
3. **Defensive read path (recommended even after #1/#2):** when classifying a ledger for the voucher picker and for P&L/BS rollup, resolve nature by **walking `parent_id` to the root primary group** rather than trusting the immediate group's stored `nature`. This makes the engine robust to any future bad row.
4. **One-time data migration** for existing books (see §6) + a startup integrity check that logs/repairs `nature` mismatches against parent.
5. Optionally enforce **unique group name per `company_id`** (and/or case-insensitive) to prevent "Direct Income" vs "Direct Incomes" duplicates.

---

## 4. Data remediation already applied to `krishan_sanghi.db`

All changes were made on the **live** book with a consistent backup taken immediately before each step (SQLite online backup API, captures WAL). Backups are in the same folder:

- `krishan_sanghi_PREFIX27FIX_20260626_110924.db`
- `krishan_sanghi_MERGE27to22_20260626_111001.db`
- `krishan_sanghi_FIX28_20260626_111405.db`

| # | Action | SQL |
|---|---|---|
| 1 | Fix group 27 nature | `UPDATE account_groups SET nature='INCOME' WHERE id=27 AND company_id=1 AND name='Direct Incomes';` |
| 2 | Merge dup 27 → 22, then drop 27 | `UPDATE ledgers SET group_id=22 WHERE group_id=27 AND company_id=1;` then `DELETE FROM account_groups WHERE id=27 AND company_id=1;` |
| 3 | Fix group 28 nature | `UPDATE account_groups SET nature='INCOME' WHERE id=28 AND company_id=1 AND name='Indirect Incomes';` |
| 4 | Fix groups 35 & 39 nature (expense side) | `UPDATE account_groups SET nature='EXPENSE' WHERE id IN (35,39) AND company_id=1;` |
| 5 | Fix group 31 nature (Bank OD) | `UPDATE account_groups SET nature='LIABILITY' WHERE id=31 AND company_id=1 AND name='Bank OD A/c';` |

Additional backups for steps 4–5: `krishan_sanghi_FIX35_39_20260626_111652.db`, `krishan_sanghi_FIX31_20260627_080907.db`.

**Result:** "Direct Income" (22) now holds Salary, Mentoring/honourarium, Options Profits, Partner's Remuneration, Zerodha Intraday P&L. "Indirect Incomes" (28) now correctly `INCOME` with its 9 ledgers (Dividend Received, Interest on FD, Interest on I.T Refund, Interest on Saving Bank A/c, LTCG, STCG, Profit/Loss on Net Obligations, Profit/Loss on Trading Account, Short Term Equity Trading P&L).

> The app caches groups at startup — a **restart** is required for the running instance to see these changes.

---

## 5. Audit findings — ALL NOW RESOLVED in this book

As of 2026-06-27 the recursive nature-vs-root audit (§6) returns **zero mismatches** — every group agrees with its primary group's nature. The items below were found and fixed:

### 5A. Sub-groups whose `nature` ≠ parent's `nature` — FIXED
| group id | name | was | parent | now |
|---|---|---|---|---|
| 31 | Bank OD A/c | `ASSET` | Loans (Liability) | `LIABILITY` ✅ (Tally convention; no ledgers under it) |
| 35 | Business Expense | `ASSET` | Direct Expenses | `EXPENSE` ✅ |

### 5B. Deeper mismatch missed by a "vs immediate parent" check — FIXED
- **Group 39 "Utilities"** (`ASSET`) was a child of 35 "Business Expense" (`ASSET`). They agreed with *each other*, so a parent-comparison missed it, but both were wrong vs the true root (Direct Expenses = EXPENSE). **This is why §6 uses a recursive root walk, not an immediate-parent compare.**
- 39 held 2 real expense ledgers misclassified as assets — `Gas/IGL Expense` (59), `Property Tax` (105) — now `EXPENSE` ✅ (visible in expense vouchers; report under P&L).

### 5C. False positive — left alone (correct as-is)
- **29 "Misc. Expenses (ASSET)"** is `ASSET` **by design** (deferred/miscellaneous expenditure carried as an asset; the name even says so). It is a *primary* group, so the §6 root-walk audit does not flag it. Not a bug.

---

## 6. Suggested migration / audit SQL (safe to run per book; back up first)

**Audit — list every group whose nature disagrees with its primary (root) ancestor:**
```sql
WITH RECURSIVE root AS (
  SELECT id, name, nature, parent_id, id AS rid, nature AS root_nature
  FROM account_groups WHERE parent_id IS NULL
  UNION ALL
  SELECT g.id, g.name, g.nature, g.parent_id, r.rid, r.root_nature
  FROM account_groups g JOIN root r ON g.parent_id = r.id
)
SELECT id, name, nature, root_nature
FROM root
WHERE nature <> root_nature
ORDER BY id;
```

**Repair (review the audit output first — exclude intentional cases like Misc. Expenses):**
```sql
-- Example, targeted; do NOT blanket-update without reviewing the audit.
UPDATE account_groups SET nature='EXPENSE' WHERE id IN (35,39) AND company_id=1;
-- UPDATE account_groups SET nature='LIABILITY' WHERE id=31 AND company_id=1; -- if confirmed
```

---

## 7. Reproduce & verify

1. Create a primary income group, then add a **sub-group** under it via the UI; inspect `account_groups.nature` for the new sub-group → expect bug: it is `ASSET` instead of inheriting the parent's nature.
2. Create a ledger under that sub-group, open a **Sales voucher** → the ledger is missing from the credit-side ledger picker.
3. After fixing `nature` to `INCOME` (and restarting), the ledger appears, and its balance reports under **P&L → Income**, not the Balance Sheet.

## 8. Asks for the dev

- Confirm the voucher ledger-picker filter and the P&L/BS rollup both key off `account_groups.nature`.
- Implement parent-nature inheritance for sub-groups (§3.1–3.3).
- Ship the migration + startup integrity check (§3.4, §6).
- Decide on unique-name enforcement to kill the duplicate-group class of bug (§3.5).
