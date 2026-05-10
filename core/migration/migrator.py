"""
Migration engine — applies a normalized MigrationPayload to a target company.

v1 scope:
    • Groups: insert non-existing groups (skip-on-name-match).
    • Ledger master: insert each ledger with all available fields
      (GSTIN/PAN/state/bank/IFSC/TDS), opening balance + Dr/Cr.
    • Company metadata: fill empty company.gstin / state_code / fy_start
      from the payload only — never overwrite.
    • NO voucher migration. The book starts fresh; opening balances
      reflect the prior-period closing.

Target rules: target company must not have any vouchers. The user can
create a fresh empty company OR import into an empty existing one.
Refuses otherwise.

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
from .payload import MigrationPayload, GroupSpec, LedgerSpec


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
        errors: list[str] = []
        warnings: list[str] = []

        if not payload.ledgers and not payload.groups:
            errors.append("Payload is empty — no groups or ledgers to import.")

        # Required fields per ledger
        seen: set[str] = set()
        for ld in payload.ledgers:
            if not ld.name:
                errors.append("Found a ledger with no name.")
                continue
            if ld.name in seen:
                errors.append(f"Duplicate ledger name in payload: {ld.name}")
            seen.add(ld.name)
            if not ld.group_name:
                errors.append(f"Ledger '{ld.name}' has no group.")
            if ld.opening_type and ld.opening_type not in ("Dr", "Cr"):
                errors.append(
                    f"Ledger '{ld.name}': opening_type must be Dr or Cr "
                    f"(got '{ld.opening_type}')."
                )

        # Group name uniqueness
        gseen: set[str] = set()
        for g in payload.groups:
            if not g.name:
                errors.append("Found a group with no name.")
                continue
            if g.name in gseen:
                errors.append(f"Duplicate group name in payload: {g.name}")
            gseen.add(g.name)

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
                # Topologically sort: parents before children
                for g in self._sorted_groups(payload.groups):
                    if g.name in existing_groups:
                        continue
                    parent_id = None
                    if g.parent_name:
                        prow = self.db.execute(
                            "SELECT id FROM account_groups "
                            " WHERE company_id=? AND name=?",
                            (self.company_id, g.parent_name),
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
                    groups_added += 1

                # 2. Ledger master
                for ld in payload.ledgers:
                    if ld.group_name not in existing_groups:
                        skipped.append(
                            f"{ld.name} (unknown group {ld.group_name})"
                        )
                        continue
                    # Auto-derive is_bank / is_cash / is_gst_ledger from group
                    # name if not explicitly set in the payload.
                    is_bank      = ld.is_bank
                    is_cash      = ld.is_cash
                    is_gst       = ld.is_gst_ledger
                    glower = ld.group_name.lower()
                    if not is_bank and "bank accounts" in glower:
                        is_bank = True
                    if not is_cash and "cash-in-hand" in glower:
                        is_cash = True
                    if not is_gst and "duties & taxes" in glower:
                        is_gst = True

                    try:
                        self.tree.add_ledger(
                            ld.name, ld.group_name,
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
        """Default nature when the parser doesn't supply one."""
        if g.parent_name:
            for other in payload.groups:
                if other.name == g.parent_name and other.nature:
                    return other.nature
        return "ASSET"   # safest fallback

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
