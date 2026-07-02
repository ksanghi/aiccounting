# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the app

Two entry points; both wire the same core: `Database` → `AccountTree` → `VoucherEngine`.

- **GUI (primary):** `python main.py` — PyQt6 desktop app. Opens a company-selector dialog, then `MainWindow`. Requires `pip install pyqt6`.
- **CLI (legacy / debugging):** `python start_accounting.py` — text-mode menu for posting vouchers, viewing daybook, ledger balances, adding ledgers. Useful for reproducing engine bugs without the GUI.

There is no test suite, lint config, build system, requirements.txt, or pyproject.toml. PyQt6 is the only third-party dep used by the GUI; the core/CLI are pure-stdlib (sqlite3).

## Architecture

### Per-company SQLite, schema auto-applied

Each company is its own `data/companies/<slug>.db` file. `core/models.py` holds the full schema as a `SCHEMA` string and `executescript`s it on every `Database.connect()` (idempotent — uses `CREATE TABLE IF NOT EXISTS` and `CREATE INDEX IF NOT EXISTS`). **Consequence:** adding a column to an existing table will not propagate to existing company DBs — there is no migration system. New columns require manual `ALTER TABLE` or destroying the .db.

Connections enable `journal_mode=WAL` and `foreign_keys=ON`. `Database` works as a context manager that commits on success / rolls back on exception.

### Voucher domain

The system models 8 Indian voucher types: `PAYMENT, RECEIPT, JOURNAL, CONTRA, SALES, PURCHASE, DEBIT_NOTE, CREDIT_NOTE`. The flow is always:

1. A builder method on `VoucherEngine` (e.g. `build_payment`, `build_sales`) returns a `VoucherDraft` of `VoucherLine`s.
2. `engine.post(draft)` validates (Dr/Cr balance, GST split for intra/inter-state via state codes, TDS thresholds from `TDS_SECTIONS`), assigns a number from `voucher_series`, and writes to `vouchers` + `voucher_lines` atomically.

GST/TDS rates are constants in `core/voucher_engine.py` (`GST_RATES`, `TDS_SECTIONS`). State-code comparison (company vs. party `ledgers.state_code`) drives CGST+SGST vs. IGST.

`AccountTree` (`core/account_tree.py`) seeds the chart of accounts on company creation via `seed_defaults()` — mirrors Tally Prime's group structure (`DEFAULT_GROUPS`, `DEFAULT_LEDGERS`). Several seeded ledgers have `is_system=1` and cannot be deleted.

### UI page registration

`ui/main_window.py` is a sidebar + `QStackedWidget`. To add a screen, instantiate it inside `_build_pages` and call `register_page(label, icon, widget)`. The page receives `(db, company_id, tree, engine)` from `MainWindow.__init__`. `ui/theme.py` is the single source of colors — read `THEME` and apply via `get_stylesheet()` rather than hand-coding hex values.

### Dr/Cr label modes

`core/config.py` exposes a runtime-switchable label style (`natural` / `traditional` / `accounting`) — UI labels for Debit/Credit columns must go through `get_dr_label()` / `get_cr_label()` rather than being hardcoded, otherwise the user's preference won't apply.

### AI features (paid tier)

`ai/document_parser.py` and `ai/voucher_ai.py` produce `VoucherDraft`s from documents/text. They are **metered** through `ai/credit_manager.py` and **gated** by `core/license_manager.py` (consumed by `ui/feature_gate_widget.py` and `ui/license_page.py`). Don't bypass the gate when adding AI surfaces — wrap them with `feature_gate_widget`.

Vouchers created by AI carry `source='AI_DOC'` (or `'VERBAL'`) and an `ai_confidence` score on the `vouchers` row — preserve these when round-tripping through edits.

## Repo quirks (don't "fix" without checking)

- **`core/ __init__.py` has a leading space in the filename** (literal `core\ __init__.py`). Imports of `core.*` work in practice — verify with `python -c "from core.models import Database"` before any rename.
- **Branches:** day-to-day work happens on `main`; the PR target / "main" branch is `master`. Diff scope against `master` (e.g. `git diff master...HEAD`), open PRs against `master`.
- **`.claude/worktrees/`** contains leftover agent worktrees that mirror most of the source tree. Exclude that path from Glob/Grep, otherwise you'll get stale duplicate hits.
