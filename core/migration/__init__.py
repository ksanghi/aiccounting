"""
Book migration from other software.

  • payload    — normalized data shape produced by source parsers.
  • migrator   — applies a payload to the target company (groups + ledger master).
  • excel_coa  — parser for user-prepared Excel chart-of-accounts.
  • tally_xml  — parser for Tally Prime / ERP 9 master export.
  • cloud_csv  — parser for Zoho Books / QuickBooks COA CSV exports.
"""
from .payload  import GroupSpec, LedgerSpec, CompanySpec, MigrationPayload
from .migrator import Migrator, ValidationResult, ApplyResult, MigrationError

__all__ = [
    "GroupSpec", "LedgerSpec", "CompanySpec", "MigrationPayload",
    "Migrator", "ValidationResult", "ApplyResult", "MigrationError",
]
