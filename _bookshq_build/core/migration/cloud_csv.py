"""
Zoho Books / QuickBooks Online chart-of-accounts CSV parser.

Both apps export a similar shape — one row per account with columns for
Name, Type, Parent (or Account Group), Opening Balance. We sniff the
headers case-insensitively and accept several synonyms.

Zoho Books export columns (typical):
    Account Name | Account Code | Account Type | Account Group |
    Description | Opening Balance | Opening Balance Type

QuickBooks Online export columns (typical):
    Account | Type | Detail Type | Description | Balance | …

Output: MigrationPayload with ledgers (group_name = mapped nature group)
plus a few synthesized groups so they exist after migration.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Optional

from .payload import (
    MigrationPayload, GroupSpec, LedgerSpec,
)


_HEADERS = {
    "name":            ("account name", "account", "name"),
    "account_type":    ("account type", "type", "category"),
    "parent":          ("account group", "parent", "parent account",
                        "group", "sub type", "detail type"),
    "opening_balance": ("opening balance", "balance", "opening", "ob"),
    "opening_type":    ("opening balance type", "balance type",
                        "dr/cr", "type (dr/cr)"),
    "gstin":           ("gstin", "gst number", "tax id"),
    "pan":             ("pan",),
}


# Map cloud-system "Type" labels → our nature.
# These are deliberately wide — anything that smells like asset/expense/etc.
_NATURE_HINTS = {
    "ASSET":     ("asset", "bank", "cash", "current asset", "fixed asset",
                  "other asset", "accounts receivable", "stock", "inventory",
                  "deposits", "other current asset"),
    "LIABILITY": ("liability", "accounts payable", "credit card",
                  "current liability", "long term liability", "loan",
                  "equity", "capital"),
    "INCOME":    ("income", "revenue", "sales", "other income"),
    "EXPENSE":   ("expense", "cost of goods sold", "cogs", "depreciation"),
}

# Map cloud-system Type → our default group name (so the migrated ledger
# has a sensible parent in the seeded chart).
_GROUP_HINTS = {
    # Assets
    "bank":               "Bank Accounts",
    "cash":               "Cash-in-Hand",
    "accounts receivable":"Sundry Debtors",
    "stock":              "Stock-in-Trade",
    "inventory":          "Stock-in-Trade",
    "fixed asset":        "Fixed Assets",
    "other asset":        "Investments",
    "other current asset":"Current Assets",
    # Liabilities
    "accounts payable":   "Sundry Creditors",
    "credit card":        "Sundry Creditors",
    "long term liability":"Loans (Liability)",
    "loan":               "Loans (Liability)",
    "equity":             "Capital Account",
    "capital":            "Capital Account",
    # Income
    "income":             "Direct Income",
    "revenue":            "Direct Income",
    "sales":              "Sales Accounts",
    "other income":       "Other Income",
    # Expenses
    "expense":            "Indirect Expenses",
    "cost of goods sold": "Direct Expenses",
    "cogs":               "Direct Expenses",
}


def _norm(s) -> str:
    return str(s or "").strip().lower()


def _pick_header(headers, options) -> Optional[int]:
    norm = [_norm(h) for h in headers]
    for o in options:
        if o in norm:
            return norm.index(o)
    for o in options:
        for i, h in enumerate(norm):
            if o in h:
                return i
    return None


def _parse_amount(raw) -> float:
    if raw is None:
        return 0.0
    s = str(raw).strip()
    if not s:
        return 0.0
    s = re.sub(r"[^\d.\-+]", "", s.replace(",", ""))
    if not s or s in ("-", "+", "."):
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def _classify_type(raw_type: str) -> tuple[str, str]:
    """
    Map a cloud 'Type' label to (nature, default_group_name).
    Returns ('', '') if it can't be classified — caller handles the
    'Unmapped' bucket.
    """
    t = _norm(raw_type)
    if not t:
        return "", ""
    # Check group hints first (more specific)
    for hint, group in _GROUP_HINTS.items():
        if hint in t:
            for nature, hints in _NATURE_HINTS.items():
                if any(h in t for h in hints):
                    return nature, group
            # If we have a group but no nature, derive from group name
            for nature, hints in _NATURE_HINTS.items():
                if any(h in group.lower() for h in hints):
                    return nature, group
    # Fall back to nature only
    for nature, hints in _NATURE_HINTS.items():
        if any(h in t for h in hints):
            # Generic group per nature
            return nature, {
                "ASSET":     "Current Assets",
                "LIABILITY": "Current Liabilities",
                "INCOME":    "Other Income",
                "EXPENSE":   "Indirect Expenses",
            }[nature]
    return "", ""


# ── Top-level parser ────────────────────────────────────────────────────────

def parse_cloud_csv(file_path: str, source_label: str = "") -> MigrationPayload:
    from .migrator import Migrator

    path = Path(file_path)
    if not path.exists():
        raise ValueError(f"File not found: {file_path}")

    rows = _read_csv(path)
    if not rows:
        raise ValueError("CSV is empty.")
    headers = rows[0]
    body    = rows[1:]

    idx_name   = _pick_header(headers, _HEADERS["name"])
    idx_type   = _pick_header(headers, _HEADERS["account_type"])
    idx_parent = _pick_header(headers, _HEADERS["parent"])
    idx_ob     = _pick_header(headers, _HEADERS["opening_balance"])
    idx_obt    = _pick_header(headers, _HEADERS["opening_type"])
    idx_gstin  = _pick_header(headers, _HEADERS["gstin"])
    idx_pan    = _pick_header(headers, _HEADERS["pan"])

    if idx_name is None:
        raise ValueError(
            "Could not find an 'Account Name' column. "
            f"Headers detected: {headers}"
        )
    if idx_type is None and idx_parent is None:
        raise ValueError(
            "Need at least an 'Account Type' or 'Parent Account' column "
            "to infer the group hierarchy. Headers detected: " + str(headers)
        )

    # Detect source from headers / values for the source_label
    if not source_label:
        joined = " | ".join(_norm(h) for h in headers)
        if "account group" in joined or "opening balance type" in joined:
            source_label = "Zoho Books export"
        elif "detail type" in joined:
            source_label = "QuickBooks export"
        else:
            source_label = "Cloud accounting CSV"

    payload = MigrationPayload(
        source_type="CLOUD_CSV",
        source_label=source_label,
        file_name=path.name,
        file_hash=Migrator.sha256(path),
    )

    seen_groups: set[str] = set()
    unmapped: list[str] = []

    for row in body:
        if idx_name >= len(row):
            continue
        name = str(row[idx_name] or "").strip()
        if not name:
            continue

        raw_type = (
            str(row[idx_type] or "").strip()
            if idx_type is not None and idx_type < len(row) else ""
        )
        explicit_parent = (
            str(row[idx_parent] or "").strip()
            if idx_parent is not None and idx_parent < len(row) else ""
        )

        # Group resolution: prefer explicit parent column; else map from Type.
        nature, mapped_group = _classify_type(raw_type)
        group_name = explicit_parent or mapped_group
        if not group_name:
            unmapped.append(f"{name} (type='{raw_type}')")
            group_name = "Indirect Expenses"   # safest fallback

        # Synthesize the group if it isn't a seeded default the migrator
        # will recognise — caller can decide whether to add it.
        if group_name not in seen_groups:
            payload.groups.append(GroupSpec(
                name=group_name,
                parent_name=None,
                nature=nature or "",
            ))
            seen_groups.add(group_name)

        # Opening balance + Dr/Cr
        ob_raw = (
            row[idx_ob] if idx_ob is not None and idx_ob < len(row) else ""
        )
        ob = _parse_amount(ob_raw)
        if idx_obt is not None and idx_obt < len(row):
            t = _norm(row[idx_obt])
            opening_type = "Cr" if t in ("cr", "credit") else "Dr"
            opening_balance = abs(ob)
        else:
            # No explicit Dr/Cr — use sign convention
            opening_type = "Dr" if ob >= 0 else "Cr"
            opening_balance = abs(ob)

        glower = group_name.lower()
        is_bank = "bank" in _norm(raw_type) or "bank accounts" in glower
        is_cash = "cash" in _norm(raw_type) or "cash-in-hand" in glower

        payload.ledgers.append(LedgerSpec(
            name             = name,
            group_name       = group_name,
            opening_balance  = opening_balance,
            opening_type     = opening_type,
            gstin            = (
                str(row[idx_gstin] or "").strip() or None
                if idx_gstin is not None and idx_gstin < len(row) else None
            ),
            pan              = (
                str(row[idx_pan] or "").strip() or None
                if idx_pan is not None and idx_pan < len(row) else None
            ),
            is_bank          = is_bank,
            is_cash          = is_cash,
        ))

    if unmapped:
        payload.notes.append(
            "Could not auto-map account type for these rows — they were "
            "placed under 'Indirect Expenses' as a fallback. Edit them via "
            "F3 after import:\n  " + "\n  ".join(unmapped[:10])
            + (f"\n  ... and {len(unmapped)-10} more" if len(unmapped) > 10 else "")
        )

    return payload


def _read_csv(path: Path) -> list[list[str]]:
    for enc in ("utf-8-sig", "utf-8", "latin-1", "cp1252"):
        try:
            with open(path, newline="", encoding=enc) as f:
                return [list(r) for r in csv.reader(f)]
        except UnicodeDecodeError:
            continue
    raise ValueError(f"Could not decode {path.name} with utf-8/latin-1/cp1252.")
