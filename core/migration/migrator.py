"""
Migration engine — applies a normalized MigrationPayload to a target company.

Scope:
    • Groups: insert non-existing groups (skip-on-name-match).
    • Ledger master: insert each ledger with all available fields
      (GSTIN/PAN/state/bank/IFSC/TDS), opening balance + Dr/Cr.
    • Company metadata: fill empty company.gstin / state_code / fy_start
      from the payload only — never overwrite.
    • Vouchers (via apply_vouchers — separate entry from apply()): direct
      INSERT preserving the source voucher number + date verbatim, with
      source='MIGRATION'. Re-running is naturally idempotent thanks to
      the (company_id, voucher_type, voucher_number) unique constraint.

Target rules:
    • apply() — refuses if the target already has vouchers (only allowed
      on an empty book to avoid CoA drift).
    • apply_vouchers() — allowed any time; dedupes per the unique
      constraint above. Skips vouchers that reference unknown ledgers
      or fail to balance.

Audit: every run is logged in migration_runs (DRY_RUN / COMPLETED /
FAILED) with counts JSON.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from core.models import Database
from core.account_tree import AccountTree
from .payload import (
    MigrationPayload, GroupSpec, LedgerSpec, VoucherSpec,
    nature_for_group_name, group_dedup_key,
)


# ── Public exception type ────────────────────────────────────────────────────

class MigrationError(Exception):
    """Raised when migration cannot proceed (target check / validation / apply)."""


@dataclass
class ValidationResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    counts: dict = field(default_factory=dict)


@dataclass
class ApplyResult:
    run_id: int
    counts: dict
    errors: list[str] = field(default_factory=list)


# ── Engine ───────────────────────────────────────────────────────────────────

class Migrator:
    """Construct once per migration: Migrator(db, company_id, tree)."""

    def __init__(self, db: Database, company_id: int, tree: AccountTree):
        self.db         = db
        self.company_id = company_id
        self.tree       = tree

    # ── Pre-flight: target compatibility ──────────────────────────────────────

    def check_target_compatible(self) -> None:
        """
        v1 rule: target company must have ZERO posted vouchers. Caller is
        free to add chart of accounts (the seeded chart is fine), but if
        any vouchers exist we refuse — too risky to merge with a live book.
        """
        row = self.db.execute(
            "SELECT COUNT(*) AS c FROM vouchers WHERE company_id=?",
            (self.company_id,),
        ).fetchone()
        if row and row["c"]:
            raise MigrationError(
                f"This company already has {row['c']} voucher(s). "
                "Migration only runs on companies with no vouchers yet — "
                "create a fresh company to migrate into."
            )

    # ── Validation (no DB writes) ──────────────────────────────────────────────

    def validate(self, payload: MigrationPayload) -> ValidationResult:
        """
        Validation is intentionally LIBERAL. Anything we can recover from at
        apply-time becomes a warning rather than an error, so one weird row
        in a 100-row export doesn't block the whole import. Genuinely fatal
        cases (empty payload, completely garbled file) still produce errors.

        Recoverable cases → warning + skip-on-apply:
          - Ledger has no name (the row is empty)
          - Ledger has no group (Tally has reserved system ledgers like this)
          - Ledger has bad opening_type (defaults to Dr on apply)
          - Duplicate ledger name (first wins)
          - Duplicate group name (first wins)
        """
        errors: list[str] = []
        warnings: list[str] = []

        if not payload.ledgers and not payload.groups:
            errors.append("Payload is empty — no groups or ledgers to import.")

        # Per-ledger checks — all warning-level. Apply step does the skipping.
        seen: set[str] = set()
        nameless_count = 0
        no_group_names: list[str] = []
        dup_ledger_names: list[str] = []
        bad_optype_names: list[str] = []
        for ld in payload.ledgers:
            if not ld.name:
                nameless_count += 1
                continue
            if ld.name in seen:
                dup_ledger_names.append(ld.name)
            seen.add(ld.name)
            if not ld.group_name:
                no_group_names.append(ld.name)
            if ld.opening_type and ld.opening_type not in ("Dr", "Cr"):
                bad_optype_names.append(f"{ld.name} ({ld.opening_type!r})")

        if nameless_count:
            warnings.append(
                f"{nameless_count} ledger row(s) had no name — those rows "
                f"will be skipped."
            )
        if no_group_names:
            warnings.append(
                f"{len(no_group_names)} ledger(s) have no parent group and "
                f"will be skipped on apply: "
                f"{', '.join(no_group_names[:6])}"
                + (f", … and {len(no_group_names)-6} more"
                   if len(no_group_names) > 6 else "")
            )
        if dup_ledger_names:
            warnings.append(
                f"{len(dup_ledger_names)} duplicate ledger name(s) — first "
                f"occurrence wins: {', '.join(dup_ledger_names[:6])}"
            )
        if bad_optype_names:
            warnings.append(
                f"{len(bad_optype_names)} ledger(s) had a non-Dr/Cr opening "
                f"type — defaulting to Dr: {', '.join(bad_optype_names[:6])}"
            )

        # Group name uniqueness — also warning-level (first wins).
        gseen: set[str] = set()
        nameless_groups = 0
        dup_groups: list[str] = []
        for g in payload.groups:
            if not g.name:
                nameless_groups += 1
                continue
            if g.name in gseen:
                dup_groups.append(g.name)
            gseen.add(g.name)
        if nameless_groups:
            warnings.append(
                f"{nameless_groups} group(s) had no name — those entries "
                f"will be skipped."
            )
        if dup_groups:
            warnings.append(
                f"{len(dup_groups)} duplicate group name(s) — first wins: "
                f"{', '.join(dup_groups[:6])}"
            )

        # All ledger group_names must exist in payload.groups OR in the
        # already-seeded company groups.
        existing_groups = {
            r["name"] for r in self.db.execute(
                "SELECT name FROM account_groups WHERE company_id=?",
                (self.company_id,),
            ).fetchall()
        }
        known_groups = existing_groups | gseen
        for ld in payload.ledgers:
            if ld.group_name and ld.group_name not in known_groups:
                warnings.append(
                    f"Ledger '{ld.name}' references group "
                    f"'{ld.group_name}' which doesn't exist yet — "
                    "will be created if the parser supplied it, otherwise "
                    "the ledger will be skipped on apply."
                )

        # Books must balance: Σ(Dr opening) ≈ Σ(Cr opening). Tolerance 1₹.
        total_dr = sum(
            (ld.opening_balance or 0.0)
            for ld in payload.ledgers
            if (ld.opening_type or "Dr") == "Dr"
        )
        total_cr = sum(
            (ld.opening_balance or 0.0)
            for ld in payload.ledgers
            if (ld.opening_type or "Dr") == "Cr"
        )
        diff = round(total_dr - total_cr, 2)
        if abs(diff) > 1.00:
            warnings.append(
                f"Opening balances don't balance: Dr {total_dr:,.2f} "
                f"vs Cr {total_cr:,.2f} (diff {diff:+,.2f}). The trial "
                "balance will be off by this amount until you correct it."
            )

        counts = {
            "groups":          len(payload.groups),
            "ledgers":         len(payload.ledgers),
            "opening_total_dr": round(total_dr, 2),
            "opening_total_cr": round(total_cr, 2),
            "opening_diff":     diff,
        }
        return ValidationResult(
            ok=not errors,
            errors=errors,
            warnings=warnings,
            counts=counts,
        )

    # ── Apply (writes to DB) ──────────────────────────────────────────────────

    def apply(self, payload: MigrationPayload) -> ApplyResult:
        self.check_target_compatible()
        v = self.validate(payload)
        if not v.ok:
            raise MigrationError("\n".join(v.errors))

        run_id = self._open_run(payload, status="IN_PROGRESS")

        groups_added  = 0
        ledgers_added = 0
        skipped: list[str] = []
        errors: list[str] = []

        try:
            with self.db:
                # 1. Groups
                existing_groups = {
                    r["name"] for r in self.db.execute(
                        "SELECT name FROM account_groups WHERE company_id=?",
                        (self.company_id,),
                    ).fetchall()
                }
                # Canonical index so an imported group equal to an existing/seed
                # one under a near-duplicate spelling ('Direct Incomes' vs the
                # seed 'Direct Income') is folded onto it, not inserted as a twin.
                existing_by_canon = {
                    group_dedup_key(name): name for name in existing_groups
                }
                group_alias: dict[str, str] = {}
                # Topologically sort: parents before children. Skip
                # nameless rows (validator already warned).
                seen_payload_groups: set[str] = set()
                for g in self._sorted_groups(payload.groups):
                    if not g.name:
                        continue
                    if g.name in seen_payload_groups:
                        # Duplicate within the payload — first wins.
                        continue
                    seen_payload_groups.add(g.name)
                    if g.name in existing_groups:
                        continue
                    canon = group_dedup_key(g.name)
                    twin = existing_by_canon.get(canon)
                    if twin and twin != g.name:
                        group_alias[g.name] = twin
                        skipped.append(
                            f"group '{g.name}' (already present as '{twin}')"
                        )
                        continue
                    parent_id = None
                    if g.parent_name:
                        parent_name = group_alias.get(g.parent_name, g.parent_name)
                        prow = self.db.execute(
                            "SELECT id FROM account_groups "
                            " WHERE company_id=? AND name=?",
                            (self.company_id, parent_name),
                        ).fetchone()
                        if prow:
                            parent_id = prow["id"]
                        else:
                            errors.append(
                                f"Group '{g.name}' references unknown parent "
                                f"'{g.parent_name}' — created as top-level."
                            )
                    self.db.execute(
                        """INSERT INTO account_groups
                           (company_id, name, parent_id, nature, affects_gross_profit)
                           VALUES (?,?,?,?,?)""",
                        (
                            self.company_id, g.name, parent_id,
                            g.nature or self._guess_nature(payload, g),
                            int(bool(g.affects_gross_profit)),
                        ),
                    )
                    existing_groups.add(g.name)
                    existing_by_canon[canon] = g.name
                    groups_added += 1

                # 2. Ledger master
                seen_ledger_names: set[str] = set()
                for ld in payload.ledgers:
                    if not ld.name:
                        # Validator already warned about nameless rows.
                        continue
                    if ld.name in seen_ledger_names:
                        # Duplicate within the payload — first wins.
                        skipped.append(f"{ld.name} (duplicate name)")
                        continue
                    seen_ledger_names.add(ld.name)
                    if not ld.group_name:
                        skipped.append(f"{ld.name} (no parent group in source)")
                        continue
                    # Fold a near-duplicate source group onto the real one.
                    grp = group_alias.get(ld.group_name, ld.group_name)
                    if grp not in existing_groups:
                        skipped.append(
                            f"{ld.name} (unknown group {ld.group_name})"
                        )
                        continue
                    # Auto-derive is_bank / is_cash / is_gst_ledger from group
                    # name if not explicitly set in the payload.
                    is_bank      = ld.is_bank
                    is_cash      = ld.is_cash
                    is_gst       = ld.is_gst_ledger
                    glower = grp.lower()
                    if not is_bank and "bank accounts" in glower:
                        is_bank = True
                    if not is_cash and "cash-in-hand" in glower:
                        is_cash = True
                    if not is_gst and "duties & taxes" in glower:
                        is_gst = True

                    try:
                        self.tree.add_ledger(
                            ld.name, grp,
                            opening_balance   = ld.opening_balance or 0.0,
                            opening_type      = ld.opening_type or "Dr",
                            is_bank           = is_bank,
                            is_cash           = is_cash,
                            gstin             = ld.gstin,
                            pan               = ld.pan,
                            state_code        = ld.state_code,
                            is_tds_applicable = ld.is_tds_applicable,
                            tds_section       = ld.tds_section,
                            tds_rate          = ld.tds_rate,
                            bank_name         = ld.bank_name,
                            account_number    = ld.account_number,
                            ifsc              = ld.ifsc,
                        )
                        ledgers_added += 1
                    except Exception as e:
                        errors.append(f"Could not add ledger '{ld.name}': {e}")

                # 3. Company metadata — only fill blanks, never overwrite
                cspec = payload.company
                if cspec:
                    self._fill_company_metadata(cspec)

            counts = {
                "groups_added":   groups_added,
                "ledgers_added":  ledgers_added,
                "skipped":        skipped,
                "warnings":       v.warnings,
                "opening_diff":   v.counts.get("opening_diff", 0),
            }
            self._close_run(run_id, status="COMPLETED",
                            counts=counts, error_log="\n".join(errors))
            return ApplyResult(run_id=run_id, counts=counts, errors=errors)
        except Exception as e:
            self._close_run(run_id, status="FAILED",
                            counts={
                                "groups_added": groups_added,
                                "ledgers_added": ledgers_added,
                            },
                            error_log=str(e))
            raise

    # ── Voucher validation + apply (writes to DB) ────────────────────────────

    def validate_vouchers(self, payload: MigrationPayload) -> ValidationResult:
        """Dry-run check for the voucher portion of a payload. Returns
        warnings + counts but writes nothing. Used by the wizard's
        preview step."""
        warnings: list[str] = []

        if not payload.vouchers:
            return ValidationResult(ok=True, counts={"vouchers": 0})

        # Ledgers known after running apply(): existing + those the payload
        # will add. Caller may invoke this before or after apply().
        existing_ledgers = {
            r["name"] for r in self.db.execute(
                "SELECT name FROM ledgers WHERE company_id=?",
                (self.company_id,),
            ).fetchall()
        }
        pending_ledgers = {ld.name for ld in payload.ledgers if ld.name}
        known = existing_ledgers | pending_ledgers

        missing_refs: dict[str, int] = {}
        unbalanced_count = 0
        no_lines_count = 0
        by_type: dict[str, int] = {}
        earliest = ""
        latest = ""

        seen_keys: set[tuple[str, str]] = set()
        duplicate_in_payload = 0

        for v in payload.vouchers:
            by_type[v.voucher_type] = by_type.get(v.voucher_type, 0) + 1
            if v.date:
                if not earliest or v.date < earliest:
                    earliest = v.date
                if not latest or v.date > latest:
                    latest = v.date
            key = (v.voucher_type, v.voucher_number)
            if key in seen_keys:
                duplicate_in_payload += 1
            seen_keys.add(key)
            if not v.lines:
                no_lines_count += 1
                continue
            for ln in v.lines:
                if ln.ledger_name not in known:
                    missing_refs[ln.ledger_name] = missing_refs.get(ln.ledger_name, 0) + 1
            total_dr = sum(ln.amount for ln in v.lines if ln.dr_cr == "Dr")
            total_cr = sum(ln.amount for ln in v.lines if ln.dr_cr == "Cr")
            if abs(total_dr - total_cr) > 0.01:
                unbalanced_count += 1

        if missing_refs:
            top = sorted(missing_refs.items(), key=lambda kv: -kv[1])[:6]
            warnings.append(
                f"{len(missing_refs)} ledger name(s) referenced by vouchers "
                f"are not in the target or in the ledger master being "
                f"imported — vouchers using them will be skipped: "
                + ", ".join(f"'{n}' ({c}x)" for n, c in top)
            )
        if unbalanced_count:
            warnings.append(
                f"{unbalanced_count} voucher(s) don't balance "
                f"(Dr != Cr) and will be skipped."
            )
        if no_lines_count:
            warnings.append(
                f"{no_lines_count} voucher(s) have no accounting lines "
                f"and will be skipped."
            )
        if duplicate_in_payload:
            warnings.append(
                f"{duplicate_in_payload} duplicate (voucher_type, "
                f"voucher_number) pair(s) within the payload — first wins."
            )

        counts = {
            "vouchers":             len(payload.vouchers),
            "by_type":              by_type,
            "date_range":           [earliest, latest],
            "missing_ledger_refs":  len(missing_refs),
            "unbalanced":           unbalanced_count,
            "no_lines":             no_lines_count,
        }
        return ValidationResult(ok=True, warnings=warnings, counts=counts)

    def apply_vouchers(self, payload: MigrationPayload) -> ApplyResult:
        """Apply payload.vouchers to the target company. Preserves the
        source voucher number + date verbatim, marks source='MIGRATION'.
        Idempotent on re-run via the (company_id, voucher_type,
        voucher_number) unique constraint.

        Bypasses VoucherEngine.post() deliberately: post() reassigns
        voucher numbers and re-applies GST/TDS rules, both of which would
        break migration intent. Tally's own validation produced these
        vouchers; we trust them and only check that the lines balance and
        that referenced ledgers exist.
        """
        if not payload.vouchers:
            return ApplyResult(
                run_id=0,
                counts={"vouchers_in_payload": 0, "vouchers_added": 0,
                        "duplicate": 0, "skipped": []},
                errors=[],
            )

        run_id = self._open_run(payload, status="IN_PROGRESS")

        added = 0
        duplicate = 0
        skipped: list[str] = []
        errors: list[str] = []

        try:
            ledger_map = {
                r["name"]: r["id"] for r in self.db.execute(
                    "SELECT id, name FROM ledgers WHERE company_id=?",
                    (self.company_id,),
                ).fetchall()
            }
            seen_in_run: set[tuple[str, str]] = set()

            with self.db:
                for v in payload.vouchers:
                    tag = f"{v.voucher_type} {v.voucher_number} ({v.date})"

                    if not v.lines:
                        skipped.append(f"{tag}: no lines")
                        continue

                    missing = [
                        ln.ledger_name for ln in v.lines
                        if ln.ledger_name not in ledger_map
                    ]
                    if missing:
                        seen_missing = ", ".join(sorted(set(missing))[:3])
                        skipped.append(f"{tag}: unknown ledger(s) {seen_missing}")
                        continue

                    total_dr = round(sum(ln.amount for ln in v.lines if ln.dr_cr == "Dr"), 2)
                    total_cr = round(sum(ln.amount for ln in v.lines if ln.dr_cr == "Cr"), 2)
                    if abs(total_dr - total_cr) > 0.01:
                        skipped.append(
                            f"{tag}: unbalanced Dr {total_dr:.2f} != Cr {total_cr:.2f}"
                        )
                        continue

                    key = (v.voucher_type, v.voucher_number)
                    if key in seen_in_run:
                        duplicate += 1
                        continue
                    seen_in_run.add(key)

                    cur = self.db.execute(
                        """INSERT OR IGNORE INTO vouchers
                           (company_id, voucher_type, voucher_number, voucher_date,
                            narration, reference, total_amount, source)
                           VALUES (?,?,?,?,?,?,?,?)""",
                        (
                            self.company_id, v.voucher_type, v.voucher_number,
                            v.date, v.narration, v.reference_number or "",
                            total_dr,        # total_amount = Dr side, per VoucherEngine convention
                            "MIGRATION",
                        ),
                    )
                    if cur.rowcount == 0:
                        # Already in DB from an earlier migration run.
                        duplicate += 1
                        continue
                    voucher_id = cur.lastrowid

                    line_rows = []
                    for ln in v.lines:
                        dr = ln.amount if ln.dr_cr == "Dr" else 0.0
                        cr = ln.amount if ln.dr_cr == "Cr" else 0.0
                        is_tax = bool(ln.gst_type or ln.tds_section)
                        tax_type = ln.gst_type or ("TDS" if ln.tds_section else "")
                        tax_rate = ln.gst_rate if ln.gst_type else (ln.tds_rate or 0.0)
                        line_rows.append((
                            voucher_id,
                            ledger_map[ln.ledger_name],
                            dr, cr,
                            "",                      # cost_centre — not migrated in v1
                            "",                      # bill_ref — not migrated in v1
                            int(is_tax),
                            tax_type,
                            tax_rate or 0.0,
                            ln.narration or "",
                        ))
                    self.db.executemany(
                        """INSERT INTO voucher_lines
                           (voucher_id, ledger_id, dr_amount, cr_amount,
                            cost_centre, bill_ref, is_tax_line, tax_type,
                            tax_rate, line_narration)
                           VALUES (?,?,?,?,?,?,?,?,?,?)""",
                        line_rows,
                    )
                    added += 1

            counts = {
                "vouchers_in_payload": len(payload.vouchers),
                "vouchers_added":      added,
                "duplicate":           duplicate,
                "skipped":             skipped,
            }
            self._close_run(run_id, status="COMPLETED",
                            counts=counts, error_log="\n".join(errors))
            return ApplyResult(run_id=run_id, counts=counts, errors=errors)
        except Exception as e:
            self._close_run(run_id, status="FAILED",
                            counts={"vouchers_added": added, "duplicate": duplicate},
                            error_log=str(e))
            raise

    # ── Helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _sorted_groups(groups: list[GroupSpec]) -> list[GroupSpec]:
        """Topological sort by parent_name — parents inserted before children."""
        by_name = {g.name: g for g in groups}
        visited: set[str] = set()
        out: list[GroupSpec] = []

        def visit(g: GroupSpec, stack: set[str]):
            if g.name in visited:
                return
            if g.name in stack:
                return        # cycle — give up gracefully
            stack.add(g.name)
            if g.parent_name and g.parent_name in by_name:
                visit(by_name[g.parent_name], stack)
            stack.discard(g.name)
            visited.add(g.name)
            out.append(g)

        for g in groups:
            visit(g, set())
        return out

    @staticmethod
    def _guess_nature(payload: MigrationPayload, g: GroupSpec) -> str:
        """Resolve a group's nature when the parser supplied none: inherit from
        parent → recognise this group's own standard name → ASSET only when
        genuinely unknown (so 'Direct Incomes' becomes INCOME, not ASSET)."""
        if g.parent_name:
            for other in payload.groups:
                if other.name == g.parent_name:
                    inherited = other.nature or nature_for_group_name(other.name)
                    if inherited:
                        return inherited
                    break
        own = nature_for_group_name(g.name)
        if own:
            return own
        return "ASSET"   # genuinely unknown group — last-resort fallback

    def _fill_company_metadata(self, cspec) -> None:
        row = self.db.execute(
            "SELECT gstin, pan, state_code, address, fy_start "
            "  FROM companies WHERE id=?",
            (self.company_id,),
        ).fetchone()
        if not row:
            return
        sets, params = [], []
        if cspec.gstin and not (row["gstin"] or "").strip():
            sets.append("gstin=?"); params.append(cspec.gstin)
        if cspec.pan and not (row["pan"] or "").strip():
            sets.append("pan=?"); params.append(cspec.pan)
        if cspec.state_code and not (row["state_code"] or "").strip():
            sets.append("state_code=?"); params.append(cspec.state_code)
        if cspec.address and not (row["address"] or "").strip():
            sets.append("address=?"); params.append(cspec.address)
        if cspec.fy_start and (row["fy_start"] or "") == "04-01":
            # only override the default seeded FY start
            sets.append("fy_start=?"); params.append(cspec.fy_start)
        if sets:
            params.append(self.company_id)
            self.db.execute(
                f"UPDATE companies SET {', '.join(sets)} WHERE id=?",
                params,
            )

    # ── migration_runs persistence ────────────────────────────────────────────

    def _open_run(self, payload: MigrationPayload, status: str) -> int:
        cur = self.db.execute(
            """INSERT INTO migration_runs
               (company_id, source_type, source_label, file_name, file_hash, status)
               VALUES (?,?,?,?,?,?)""",
            (
                self.company_id,
                payload.source_type,
                payload.source_label or payload.source_type,
                payload.file_name,
                payload.file_hash,
                status,
            ),
        )
        self.db.commit()
        return cur.lastrowid

    def _close_run(self, run_id: int, status: str,
                   counts: dict, error_log: str = "") -> None:
        self.db.execute(
            """UPDATE migration_runs
                  SET status=?, counts=?, error_log=?,
                      completed_at=datetime('now')
                WHERE id=?""",
            (status, json.dumps(counts), error_log or None, run_id),
        )
        self.db.commit()

    # ── Convenience: hash a file for the migration_runs table ─────────────────

    @staticmethod
    def sha256(path: Path | str) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()

    def history(self) -> list[dict]:
        rows = self.db.execute(
            """SELECT id, source_type, source_label, file_name, status,
                      started_at, completed_at, counts, error_log, notes
                 FROM migration_runs
                WHERE company_id=?
             ORDER BY started_at DESC""",
            (self.company_id,),
        ).fetchall()
        return [dict(r) for r in rows]
