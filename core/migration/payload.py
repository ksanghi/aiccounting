"""
Normalized payload shape that every source parser produces and the
Migrator consumes. v1 is groups + ledger master + optional company
metadata — no transactions.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional


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
class MigrationPayload:
    """What every source parser returns."""
    source_type: str                       # 'TALLY_XML' | 'EXCEL_COA' | 'CLOUD_CSV'
    source_label: str = ""                 # e.g. 'Tally Prime export'
    file_name: str = ""
    file_hash: str = ""
    company: CompanySpec = field(default_factory=CompanySpec)
    groups: list[GroupSpec] = field(default_factory=list)
    ledgers: list[LedgerSpec] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)   # parser warnings

    def as_dict(self) -> dict:
        return asdict(self)
