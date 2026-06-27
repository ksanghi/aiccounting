"""
Normalized payload shape that every source parser produces and the
Migrator consumes. Carries groups + ledger master + optional company
metadata + optional voucher transactions.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional


# ── Standard chart-of-accounts / Tally primary group name → nature ──────────────
# Importers default a group's nature to ASSET when the source supplies none, which
# silently mis-classifies income/expense/liability groups (their ledgers vanish
# from income/expense vouchers and their balances land on the Balance Sheet
# instead of the P&L). This table lets every importer recognise the well-known
# standard group names and assign the correct nature instead.
_STANDARD_GROUP_NATURE: dict[str, str] = {
    # Income
    "direct income": "INCOME", "direct incomes": "INCOME",
    "indirect income": "INCOME", "indirect incomes": "INCOME",
    "income (direct)": "INCOME", "income (indirect)": "INCOME",
    "sales": "INCOME", "sales account": "INCOME", "sales accounts": "INCOME",
    "other income": "INCOME", "revenue": "INCOME", "income": "INCOME",
    # Expense
    "direct expense": "EXPENSE", "direct expenses": "EXPENSE",
    "indirect expense": "EXPENSE", "indirect expenses": "EXPENSE",
    "expenses (direct)": "EXPENSE", "expenses (indirect)": "EXPENSE",
    "purchase": "EXPENSE", "purchases": "EXPENSE",
    "purchase account": "EXPENSE", "purchase accounts": "EXPENSE",
    "expense": "EXPENSE", "expenses": "EXPENSE",
    # Liability
    "capital account": "LIABILITY", "capital": "LIABILITY",
    "reserves & surplus": "LIABILITY", "reserves and surplus": "LIABILITY",
    "loans (liability)": "LIABILITY", "loans": "LIABILITY", "loan": "LIABILITY",
    "secured loans": "LIABILITY", "unsecured loans": "LIABILITY",
    "current liabilities": "LIABILITY", "current liability": "LIABILITY",
    "duties & taxes": "LIABILITY", "duties and taxes": "LIABILITY",
    "provisions": "LIABILITY", "provision": "LIABILITY",
    "sundry creditors": "LIABILITY", "sundry creditor": "LIABILITY",
    "bank od a/c": "LIABILITY", "bank occ a/c": "LIABILITY",
    "bank od account": "LIABILITY", "suspense a/c": "LIABILITY",
    "suspense account": "LIABILITY",
    "branch / divisions": "LIABILITY", "branch/divisions": "LIABILITY",
    # Asset
    "current assets": "ASSET", "fixed assets": "ASSET", "investments": "ASSET",
    "investment": "ASSET", "sundry debtors": "ASSET", "sundry debtor": "ASSET",
    "cash-in-hand": "ASSET", "cash in hand": "ASSET",
    "bank accounts": "ASSET", "bank account": "ASSET",
    "stock-in-hand": "ASSET", "stock in hand": "ASSET",
    "deposits (asset)": "ASSET", "loans & advances (asset)": "ASSET",
    "loans and advances (asset)": "ASSET", "misc. expenses (asset)": "ASSET",
    "miscellaneous expenses (asset)": "ASSET",
}


def canon_group_name(name: str) -> str:
    """Lower-cased, whitespace-collapsed key (no pluralisation, so irregular
    words like 'liabilities'/'surplus' are never mangled)."""
    if not name:
        return ""
    return " ".join(str(name).strip().lower().split())


def _singular(key: str) -> str:
    if key.endswith("ss") or not key.endswith("s"):
        return key
    return key[:-1]


def nature_for_group_name(name: str) -> str:
    """Best-effort nature for a standard CoA / Tally primary group name; '' when
    not recognised. Tolerates singular/plural ('Direct Income' == 'Direct Incomes')."""
    k = canon_group_name(name)
    return (_STANDARD_GROUP_NATURE.get(k)
            or _STANDARD_GROUP_NATURE.get(_singular(k), ""))


def group_dedup_key(name: str) -> str:
    """Case/space/plural-tolerant key so 'Direct Incomes' folds onto 'Direct Income'."""
    return _singular(canon_group_name(name))


@dataclass
class GroupSpec:
    """An account group to be created (or matched-by-name to existing)."""
    name: str
    parent_name: Optional[str] = None     # None = top-level
    nature: str = ""                      # 'ASSET' | 'LIABILITY' | 'INCOME' | 'EXPENSE'
    affects_gross_profit: bool = False    # 1 for trading account items


@dataclass
class LedgerSpec:
    """A ledger master row. Fills in whatever the source provides; missing
    fields stay blank for the user to populate later."""
    name: str
    group_name: str                       # parent group — determines nature
    opening_balance: float = 0.0
    opening_type: str = "Dr"              # 'Dr' or 'Cr'

    # Tax / party fields
    gstin: Optional[str] = None
    pan: Optional[str] = None
    state_code: Optional[str] = None      # 2-digit GST state code

    # System flags — auto-derived from group if not explicit on import
    is_bank: bool = False
    is_cash: bool = False
    is_gst_ledger: bool = False
    gst_type: Optional[str] = None        # CGST / SGST / IGST / CESS

    # Bank fields
    bank_name: Optional[str] = None
    account_number: Optional[str] = None
    ifsc: Optional[str] = None

    # TDS fields
    is_tds_applicable: bool = False
    tds_section: Optional[str] = None
    tds_rate: Optional[float] = None


@dataclass
class CompanySpec:
    """Optional company-level metadata the source can provide.
    Applied only if the target company hasn't already set these fields."""
    name: Optional[str] = None
    gstin: Optional[str] = None
    pan: Optional[str] = None
    state_code: Optional[str] = None
    address: Optional[str] = None
    fy_start: Optional[str] = None         # 'MM-DD' format


@dataclass
class VoucherLineSpec:
    """One Dr or Cr line within a voucher."""
    ledger_name: str                       # must match a LedgerSpec.name or pre-existing ledger
    amount: float                          # positive number
    dr_cr: str                             # 'Dr' or 'Cr'
    narration: Optional[str] = None        # line-level narration (rarely set)

    # GST line metadata (when this line is a GST ledger split)
    gst_type: Optional[str] = None         # CGST / SGST / IGST / CESS
    gst_rate: Optional[float] = None

    # TDS line metadata
    tds_section: Optional[str] = None
    tds_rate: Optional[float] = None


@dataclass
class VoucherSpec:
    """One voucher row to be posted via Migrator.apply_vouchers().
    De-dupe key is (voucher_number, fy) — already a unique index on the
    vouchers table."""
    voucher_type: str                      # PAYMENT|RECEIPT|JOURNAL|CONTRA|SALES|PURCHASE|DEBIT_NOTE|CREDIT_NOTE
    voucher_number: str                    # source system's number; series-prefixed OK
    date: str                              # 'YYYY-MM-DD'
    fy: str                                # 'YYYY-YY' e.g. '2025-26'; dedupe key half
    narration: str = ""
    party_ledger: Optional[str] = None     # the dominant party (debtor/creditor) if applicable
    reference_number: Optional[str] = None # cheque/invoice number
    reference_date: Optional[str] = None   # 'YYYY-MM-DD'
    lines: list[VoucherLineSpec] = field(default_factory=list)


@dataclass
class MigrationPayload:
    """What every source parser returns."""
    source_type: str                       # 'TALLY_XML' | 'EXCEL_COA' | 'CLOUD_CSV' | 'TALLY_HTTP'
    source_label: str = ""                 # e.g. 'Tally Prime export'
    file_name: str = ""
    file_hash: str = ""
    company: CompanySpec = field(default_factory=CompanySpec)
    groups: list[GroupSpec] = field(default_factory=list)
    ledgers: list[LedgerSpec] = field(default_factory=list)
    vouchers: list[VoucherSpec] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)   # parser warnings

    def as_dict(self) -> dict:
        return asdict(self)
