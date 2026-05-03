"""
Voucher Engine — Core Accounting Logic

Handles all 8 Indian accounting voucher types:
  PAYMENT, RECEIPT, JOURNAL, CONTRA,
  SALES, PURCHASE, DEBIT_NOTE, CREDIT_NOTE

Enforces DR/CR rules, computes GST, hooks TDS deduction.
"""
from __future__ import annotations
import json
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional
from .models import Database


# ─── GST Rates (common HSN/SAC) ───────────────────────────────────────────────
GST_RATES = {0: 0.0, 5: 5.0, 12: 12.0, 18: 18.0, 28: 28.0}

# ─── TDS Sections & Rates ─────────────────────────────────────────────────────
TDS_SECTIONS = {
    "194C": {"desc": "Contractor / Sub-contractor",   "rate": 1.0,  "threshold": 30000},
    "194H": {"desc": "Commission / Brokerage",        "rate": 5.0,  "threshold": 15000},
    "194I": {"desc": "Rent",                          "rate": 10.0, "threshold": 240000},
    "194J": {"desc": "Professional / Technical fees", "rate": 10.0, "threshold": 30000},
    "194A": {"desc": "Interest (other than bank)",    "rate": 10.0, "threshold": 5000},
    "194B": {"desc": "Lottery / Crossword",           "rate": 30.0, "threshold": 10000},
    "194D": {"desc": "Insurance commission",          "rate": 5.0,  "threshold": 15000},
    "194Q": {"desc": "Purchase of goods",             "rate": 0.1,  "threshold": 5000000},
}


# ─── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class VoucherLine:
    """One ledger entry line in a voucher."""
    ledger_id:      int
    ledger_name:    str         = ""
    dr_amount:      float       = 0.0
    cr_amount:      float       = 0.0
    cost_centre:    str         = ""
    bill_ref:       str         = ""
    is_tax_line:    bool        = False
    tax_type:       str         = ""    # CGST / SGST / IGST / TDS
    tax_rate:       float       = 0.0
    line_narration: str         = ""

    @property
    def net(self) -> float:
        return self.dr_amount - self.cr_amount


@dataclass
class VoucherDraft:
    """
    A voucher before it is posted.
    Created by voucher builders or the AI engine.
    """
    voucher_type:   str
    voucher_date:   str                     # ISO YYYY-MM-DD
    lines:          list[VoucherLine]       = field(default_factory=list)
    narration:      str                     = ""
    reference:      str                     = ""
    source:         str                     = "MANUAL"   # MANUAL / AI_DOC / VERBAL
    ai_confidence:  float | None            = None

    @property
    def total_dr(self) -> float:
        return round(sum(l.dr_amount for l in self.lines), 2)

    @property
    def total_cr(self) -> float:
        return round(sum(l.cr_amount for l in self.lines), 2)

    @property
    def is_balanced(self) -> bool:
        return abs(self.total_dr - self.total_cr) < 0.01


@dataclass
class PostedVoucher:
    """Result after a voucher is posted to the database."""
    voucher_id:     int
    voucher_number: str
    voucher_type:   str
    voucher_date:   str
    total_amount:   float
    lines:          list[VoucherLine]


# ─── Validation Errors ────────────────────────────────────────────────────────

class VoucherValidationError(Exception):
    """Raised when a voucher fails validation before posting."""
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__(" | ".join(errors))


# ─── GST Engine ───────────────────────────────────────────────────────────────

class GSTEngine:
    """Computes GST lines for sales and purchase vouchers."""

    def __init__(self, db: Database, company_id: int):
        self.db = db
        self.company_id = company_id
        self._company_state: str | None = None

    @property
    def company_state(self) -> str:
        if not self._company_state:
            row = self.db.execute(
                "SELECT state_code FROM companies WHERE id=?",
                (self.company_id,)
            ).fetchone()
            self._company_state = row["state_code"] if row else "07"
        return self._company_state

    def compute_gst(
        self,
        base_amount: float,
        gst_rate_pct: float,
        party_ledger_id: int,
        is_sales: bool = True,
    ) -> list[VoucherLine]:
        """
        Returns tax VoucherLines for a transaction.
        Decides CGST+SGST (intra-state) or IGST (inter-state).
        """
        if gst_rate_pct == 0:
            return []

        # Get party state code
        row = self.db.execute(
            "SELECT state_code FROM ledgers WHERE id=?",
            (party_ledger_id,)
        ).fetchone()
        party_state = row["state_code"] if row and row["state_code"] else None

        # Determine intra / inter state
        inter_state = (
            party_state is not None and
            party_state != self.company_state
        )

        tax_amount = round(base_amount * gst_rate_pct / 100, 2)
        lines: list[VoucherLine] = []

        if is_sales:
            # For sales: output tax = Cr to GST payable ledger
            if inter_state:
                igst_id = self._get_tax_ledger("IGST", output=True)
                lines.append(VoucherLine(
                    ledger_id=igst_id, cr_amount=tax_amount,
                    is_tax_line=True, tax_type="IGST", tax_rate=gst_rate_pct,
                    line_narration=f"IGST @{gst_rate_pct}%"
                ))
            else:
                half = round(tax_amount / 2, 2)
                cgst_id = self._get_tax_ledger("CGST", output=True)
                sgst_id = self._get_tax_ledger("SGST", output=True)
                lines.append(VoucherLine(
                    ledger_id=cgst_id, cr_amount=half,
                    is_tax_line=True, tax_type="CGST", tax_rate=gst_rate_pct / 2,
                    line_narration=f"CGST @{gst_rate_pct/2}%"
                ))
                lines.append(VoucherLine(
                    ledger_id=sgst_id, cr_amount=half,
                    is_tax_line=True, tax_type="SGST", tax_rate=gst_rate_pct / 2,
                    line_narration=f"SGST @{gst_rate_pct/2}%"
                ))
        else:
            # For purchases: input tax = Dr to ITC ledger
            if inter_state:
                itc_id = self._get_tax_ledger("IGST", output=False)
                lines.append(VoucherLine(
                    ledger_id=itc_id, dr_amount=tax_amount,
                    is_tax_line=True, tax_type="IGST", tax_rate=gst_rate_pct,
                    line_narration=f"ITC IGST @{gst_rate_pct}%"
                ))
            else:
                half = round(tax_amount / 2, 2)
                itc_cgst = self._get_tax_ledger("CGST", output=False)
                itc_sgst = self._get_tax_ledger("SGST", output=False)
                lines.append(VoucherLine(
                    ledger_id=itc_cgst, dr_amount=half,
                    is_tax_line=True, tax_type="CGST", tax_rate=gst_rate_pct / 2,
                    line_narration=f"ITC CGST @{gst_rate_pct/2}%"
                ))
                lines.append(VoucherLine(
                    ledger_id=itc_sgst, dr_amount=half,
                    is_tax_line=True, tax_type="SGST", tax_rate=gst_rate_pct / 2,
                    line_narration=f"ITC SGST @{gst_rate_pct/2}%"
                ))
        return lines

    def _get_tax_ledger(self, gst_type: str, output: bool) -> int:
        """Returns the ledger ID for a GST type."""
        if output:
            name_map = {
                "CGST": "CGST", "SGST": "SGST/UTGST", "IGST": "IGST"
            }
        else:
            name_map = {
                "CGST": "Input CGST", "SGST": "Input SGST/UTGST", "IGST": "Input IGST"
            }
        name = name_map.get(gst_type, gst_type)
        row = self.db.execute(
            "SELECT id FROM ledgers WHERE company_id=? AND name=?",
            (self.company_id, name)
        ).fetchone()
        if not row:
            raise ValueError(f"GST ledger '{name}' not found. Run account seed first.")
        return row["id"]


# ─── TDS Engine ───────────────────────────────────────────────────────────────

class TDSEngine:
    """Handles TDS deduction on payment vouchers."""

    def __init__(self, db: Database, company_id: int):
        self.db = db
        self.company_id = company_id

    def should_deduct(self, ledger_id: int, amount: float) -> dict | None:
        """
        Checks if TDS applies to this ledger.
        Returns deduction details or None.
        """
        row = self.db.execute(
            """SELECT is_tds_applicable, tds_section, tds_rate
               FROM ledgers WHERE id=?""",
            (ledger_id,)
        ).fetchone()
        if not row or not row["is_tds_applicable"]:
            return None

        section = row["tds_section"]
        rate = row["tds_rate"] or TDS_SECTIONS.get(section, {}).get("rate", 0)
        if rate == 0:
            return None

        tds_amount = round(amount * rate / 100, 2)
        net_amount = round(amount - tds_amount, 2)

        return {
            "section":    section,
            "rate":       rate,
            "gross":      amount,
            "tds_amount": tds_amount,
            "net_amount": net_amount,
        }

    def get_tds_payable_ledger(self) -> int:
        row = self.db.execute(
            "SELECT id FROM ledgers WHERE company_id=? AND name='TDS Payable'",
            (self.company_id,)
        ).fetchone()
        if not row:
            raise ValueError("TDS Payable ledger not found.")
        return row["id"]


# ─── Voucher Number Generator ─────────────────────────────────────────────────

class VoucherNumberer:
    """Generates sequential voucher numbers per type per FY."""

    PREFIX = {
        "PAYMENT":     "PMT",
        "RECEIPT":     "RCT",
        "JOURNAL":     "JNL",
        "CONTRA":      "CTR",
        "SALES":       "SLS",
        "PURCHASE":    "PUR",
        "DEBIT_NOTE":  "DBN",
        "CREDIT_NOTE": "CDN",
    }

    def __init__(self, db: Database, company_id: int):
        self.db = db
        self.company_id = company_id

    def next_number(self, voucher_type: str, fy: str) -> str:
        conn = self.db.connect()
        conn.execute(
            """INSERT OR IGNORE INTO voucher_series
               (company_id, voucher_type, prefix, last_number, fy)
               VALUES (?,?,?,0,?)""",
            (self.company_id, voucher_type,
             self.PREFIX.get(voucher_type, "VCH"), fy)
        )
        conn.execute(
            """UPDATE voucher_series SET last_number = last_number + 1
               WHERE company_id=? AND voucher_type=? AND fy=?""",
            (self.company_id, voucher_type, fy)
        )
        row = conn.execute(
            """SELECT prefix, last_number FROM voucher_series
               WHERE company_id=? AND voucher_type=? AND fy=?""",
            (self.company_id, voucher_type, fy)
        ).fetchone()
        # e.g. PMT/2025-26/00045
        return f"{row['prefix']}/{fy}/{row['last_number']:05d}"

    @staticmethod
    def get_fy(d: str) -> str:
        """Returns FY string like '2025-26' for a given ISO date."""
        dt = date.fromisoformat(d)
        if dt.month >= 4:
            return f"{dt.year}-{str(dt.year + 1)[2:]}"
        return f"{dt.year - 1}-{str(dt.year)[2:]}"


# ─── Voucher Validators ────────────────────────────────────────────────────────

class VoucherValidator:
    """
    Enforces DR/CR rules specific to each voucher type.
    Raises VoucherValidationError on failure.
    """

    RULES = {
        "PAYMENT": {
            "desc": "Payment must have exactly one Cr leg on a bank/cash account",
            "min_lines": 2,
        },
        "RECEIPT": {
            "desc": "Receipt must have exactly one Dr leg on a bank/cash account",
            "min_lines": 2,
        },
        "CONTRA": {
            "desc": "Contra is only between bank and cash accounts",
            "min_lines": 2,
        },
        "JOURNAL": {
            "desc": "Journal must balance (total Dr = total Cr)",
            "min_lines": 2,
        },
        "SALES": {
            "desc": "Sales voucher must have a Dr to debtor/bank and Cr to sales",
            "min_lines": 2,
        },
        "PURCHASE": {
            "desc": "Purchase voucher must have a Dr to purchase and Cr to creditor/bank",
            "min_lines": 2,
        },
        "DEBIT_NOTE": {
            "desc": "Debit Note: Dr party, Cr purchase return",
            "min_lines": 2,
        },
        "CREDIT_NOTE": {
            "desc": "Credit Note: Dr sales return, Cr party",
            "min_lines": 2,
        },
    }

    def __init__(self, db: Database, company_id: int):
        self.db = db
        self.company_id = company_id
        self._ledger_cache: dict[int, dict] = {}

    def _get_ledger(self, ledger_id: int) -> dict:
        if ledger_id not in self._ledger_cache:
            row = self.db.execute(
                """SELECT l.id, l.name, l.is_bank, l.is_cash,
                          l.is_gst_ledger, g.nature
                   FROM ledgers l JOIN account_groups g ON l.group_id=g.id
                   WHERE l.id=?""",
                (ledger_id,)
            ).fetchone()
            self._ledger_cache[ledger_id] = dict(row) if row else {}
        return self._ledger_cache[ledger_id]

    def validate(self, draft: VoucherDraft) -> None:
        errors: list[str] = []
        vtype = draft.voucher_type

        # 1. Must have minimum lines
        if len(draft.lines) < self.RULES[vtype]["min_lines"]:
            errors.append(
                f"{vtype} requires at least {self.RULES[vtype]['min_lines']} ledger lines."
            )

        # 2. Must balance
        if not draft.is_balanced:
            errors.append(
                f"Voucher is not balanced: Dr {draft.total_dr:.2f} ≠ Cr {draft.total_cr:.2f}"
            )

        # 3. No zero lines
        zero_lines = [
            l for l in draft.lines if l.dr_amount == 0 and l.cr_amount == 0
        ]
        if zero_lines:
            errors.append("Voucher contains lines with zero amount.")

        # 4. No negative amounts
        neg = [
            l for l in draft.lines if l.dr_amount < 0 or l.cr_amount < 0
        ]
        if neg:
            errors.append("Amounts cannot be negative.")

        # 5. Date must be valid
        try:
            date.fromisoformat(draft.voucher_date)
        except ValueError:
            errors.append(f"Invalid voucher date: {draft.voucher_date}")

        # 6. Type-specific rules
        type_errors = self._type_rules(draft)
        errors.extend(type_errors)

        if errors:
            raise VoucherValidationError(errors)

    def _type_rules(self, draft: VoucherDraft) -> list[str]:
        errors = []
        vtype = draft.voucher_type

        cr_ledgers = [
            self._get_ledger(l.ledger_id)
            for l in draft.lines if l.cr_amount > 0
        ]
        dr_ledgers = [
            self._get_ledger(l.ledger_id)
            for l in draft.lines if l.dr_amount > 0
        ]

        def is_bank_cash(ldg: dict) -> bool:
            return bool(ldg.get("is_bank") or ldg.get("is_cash"))

        if vtype == "PAYMENT":
            # Cr side must include a bank/cash account
            if not any(is_bank_cash(l) for l in cr_ledgers):
                errors.append(
                    "Payment: credit side must include a bank or cash account."
                )

        elif vtype == "RECEIPT":
            # Dr side must include a bank/cash account
            if not any(is_bank_cash(l) for l in dr_ledgers):
                errors.append(
                    "Receipt: debit side must include a bank or cash account."
                )

        elif vtype == "CONTRA":
            # Both sides must be bank or cash only
            all_sides = dr_ledgers + cr_ledgers
            if not all(is_bank_cash(l) for l in all_sides):
                errors.append(
                    "Contra: both sides must be bank or cash accounts only."
                )

        elif vtype in ("SALES", "CREDIT_NOTE"):
            # Dr side must have a debtor/bank for SALES;
            # for CREDIT_NOTE the Dr can be INCOME (sales return) — check Cr side has party
            if vtype == "SALES":
                valid_dr = any(
                    is_bank_cash(l) or l.get("nature") == "ASSET"
                    for l in dr_ledgers
                )
                if not valid_dr:
                    errors.append(
                        "Sales: debit side must be a debtor, bank, or cash account."
                    )

        elif vtype == "PURCHASE":
            # Cr side must be creditor or bank/cash (ignore ITC dr lines)
            non_tax_cr = [
                self._get_ledger(l.ledger_id)
                for l in draft.lines
                if l.cr_amount > 0 and not l.is_tax_line
            ]
            valid_cr = any(
                is_bank_cash(l) or l.get("nature") == "LIABILITY"
                for l in non_tax_cr
            )
            if non_tax_cr and not valid_cr:
                errors.append(
                    "Purchase: credit side must be a creditor, bank, or cash account."
                )

        elif vtype == "DEBIT_NOTE":
            # Dr side must have a party (LIABILITY) — Cr side is purchase return (EXPENSE) + tax lines
            non_tax_dr = [
                self._get_ledger(l.ledger_id)
                for l in draft.lines
                if l.dr_amount > 0 and not l.is_tax_line
            ]
            has_party = any(
                l.get("nature") == "LIABILITY" or is_bank_cash(l)
                for l in non_tax_dr
            )
            if not has_party:
                errors.append(
                    "Debit Note: debit side must include a creditor or bank/cash account."
                )

        elif vtype == "CREDIT_NOTE":
            # Cr side must have a debtor/bank; Dr side is sales return (INCOME) + tax lines
            non_tax_cr = [
                self._get_ledger(l.ledger_id)
                for l in draft.lines
                if l.cr_amount > 0 and not l.is_tax_line
            ]
            has_party = any(
                l.get("nature") == "ASSET" or is_bank_cash(l)
                for l in non_tax_cr
            )
            if not has_party:
                errors.append(
                    "Credit Note: credit side must include a debtor or bank/cash account."
                )

        return errors


# ─── Voucher Engine (Main) ─────────────────────────────────────────────────────

class VoucherEngine:
    """
    Central voucher posting engine.

    Usage:
        engine = VoucherEngine(db, company_id, user_id)

        # Build a payment voucher manually
        draft = engine.build_payment(
            voucher_date="2025-05-01",
            narration="Paid rent for April 2025",
            expense_ledger_id=rent_id,
            bank_ledger_id=hdfc_id,
            amount=25000.00,
        )
        posted = engine.post(draft)
    """

    def __init__(self, db: Database, company_id: int, user_id: int | None = None):
        self.db = db
        self.company_id = company_id
        self.user_id = user_id
        self.gst = GSTEngine(db, company_id)
        self.tds = TDSEngine(db, company_id)
        self.numberer = VoucherNumberer(db, company_id)
        self.validator = VoucherValidator(db, company_id)

    # ── Voucher builders ──────────────────────────────────────────────────────

    def build_payment(
        self,
        voucher_date: str,
        expense_ledger_id: int,
        bank_ledger_id: int,
        amount: float,
        narration: str = "",
        reference: str = "",
        tds_override: bool | None = None,
    ) -> VoucherDraft:
        """
        Build a Payment voucher.
        Optionally deducts TDS if party has TDS applicable.
        Dr: Expense / Party   Cr: Bank/Cash  [Cr: TDS Payable if TDS]
        """
        lines: list[VoucherLine] = [
            VoucherLine(ledger_id=expense_ledger_id, dr_amount=amount)
        ]

        # Check TDS
        tds_info = self.tds.should_deduct(expense_ledger_id, amount)
        apply_tds = tds_override if tds_override is not None else bool(tds_info)

        if apply_tds and tds_info:
            # Cr Bank with net amount
            lines.append(VoucherLine(
                ledger_id=bank_ledger_id,
                cr_amount=tds_info["net_amount"]
            ))
            # Cr TDS Payable
            tds_ledger_id = self.tds.get_tds_payable_ledger()
            lines.append(VoucherLine(
                ledger_id=tds_ledger_id,
                cr_amount=tds_info["tds_amount"],
                is_tax_line=True,
                tax_type="TDS",
                tax_rate=tds_info["rate"],
                line_narration=f"TDS u/s {tds_info['section']} @{tds_info['rate']}%"
            ))
        else:
            lines.append(VoucherLine(
                ledger_id=bank_ledger_id, cr_amount=amount
            ))

        return VoucherDraft(
            voucher_type="PAYMENT",
            voucher_date=voucher_date,
            lines=lines,
            narration=narration,
            reference=reference,
        )

    def build_receipt(
        self,
        voucher_date: str,
        party_ledger_id: int,
        bank_ledger_id: int,
        amount: float,
        narration: str = "",
        reference: str = "",
    ) -> VoucherDraft:
        """
        Build a Receipt voucher.
        Dr: Bank/Cash   Cr: Party / Income
        """
        return VoucherDraft(
            voucher_type="RECEIPT",
            voucher_date=voucher_date,
            narration=narration,
            reference=reference,
            lines=[
                VoucherLine(ledger_id=bank_ledger_id,  dr_amount=amount),
                VoucherLine(ledger_id=party_ledger_id, cr_amount=amount),
            ],
        )

    def build_contra(
        self,
        voucher_date: str,
        from_ledger_id: int,
        to_ledger_id: int,
        amount: float,
        narration: str = "",
    ) -> VoucherDraft:
        """
        Build a Contra voucher (cash ↔ bank transfer only).
        Dr: To Account   Cr: From Account
        """
        return VoucherDraft(
            voucher_type="CONTRA",
            voucher_date=voucher_date,
            narration=narration,
            lines=[
                VoucherLine(ledger_id=to_ledger_id,   dr_amount=amount),
                VoucherLine(ledger_id=from_ledger_id, cr_amount=amount),
            ],
        )

    def build_journal(
        self,
        voucher_date: str,
        lines: list[VoucherLine],
        narration: str = "",
        reference: str = "",
    ) -> VoucherDraft:
        """
        Build a Journal voucher (free-form, must balance).
        """
        return VoucherDraft(
            voucher_type="JOURNAL",
            voucher_date=voucher_date,
            lines=lines,
            narration=narration,
            reference=reference,
        )

    def build_sales(
        self,
        voucher_date: str,
        party_ledger_id: int,
        sales_ledger_id: int,
        base_amount: float,
        gst_rate_pct: float = 18.0,
        narration: str = "",
        reference: str = "",
    ) -> VoucherDraft:
        """
        Build a Sales voucher with auto-GST.
        Dr: Party (gross)   Cr: Sales (base) + CGST/SGST or IGST
        """
        tax_lines = self.gst.compute_gst(
            base_amount, gst_rate_pct, party_ledger_id, is_sales=True
        )
        total_tax = sum(l.cr_amount for l in tax_lines)
        gross = round(base_amount + total_tax, 2)

        lines: list[VoucherLine] = [
            VoucherLine(ledger_id=party_ledger_id, dr_amount=gross),
            VoucherLine(ledger_id=sales_ledger_id, cr_amount=base_amount),
        ] + tax_lines

        return VoucherDraft(
            voucher_type="SALES",
            voucher_date=voucher_date,
            lines=lines,
            narration=narration,
            reference=reference,
        )

    def build_purchase(
        self,
        voucher_date: str,
        party_ledger_id: int,
        purchase_ledger_id: int,
        base_amount: float,
        gst_rate_pct: float = 18.0,
        narration: str = "",
        reference: str = "",
    ) -> VoucherDraft:
        """
        Build a Purchase voucher with auto-GST (ITC).
        Dr: Purchase (base) + Input CGST/SGST or IGST   Cr: Party (gross)
        """
        tax_lines = self.gst.compute_gst(
            base_amount, gst_rate_pct, party_ledger_id, is_sales=False
        )
        total_tax = sum(l.dr_amount for l in tax_lines)
        gross = round(base_amount + total_tax, 2)

        lines: list[VoucherLine] = [
            VoucherLine(ledger_id=purchase_ledger_id, dr_amount=base_amount),
        ] + tax_lines + [
            VoucherLine(ledger_id=party_ledger_id, cr_amount=gross),
        ]

        return VoucherDraft(
            voucher_type="PURCHASE",
            voucher_date=voucher_date,
            lines=lines,
            narration=narration,
            reference=reference,
        )

    def build_debit_note(
        self,
        voucher_date: str,
        party_ledger_id: int,
        purchase_return_ledger_id: int,
        base_amount: float,
        gst_rate_pct: float = 18.0,
        narration: str = "",
        reference: str = "",
    ) -> VoucherDraft:
        """
        Build a Debit Note (purchase return or upward revision).
        Dr: Party   Cr: Purchase Return + GST reversal
        """
        # Reverse the ITC (Dr party, Cr purchase return & reverse GST)
        tax_lines = self.gst.compute_gst(
            base_amount, gst_rate_pct, party_ledger_id, is_sales=False
        )
        # Flip Dr/Cr on tax lines (reversal)
        reversed_tax = [
            VoucherLine(
                ledger_id=l.ledger_id,
                dr_amount=l.cr_amount, cr_amount=l.dr_amount,
                is_tax_line=l.is_tax_line, tax_type=l.tax_type,
                tax_rate=l.tax_rate, line_narration="ITC Reversal: " + l.line_narration
            )
            for l in tax_lines
        ]
        total_tax = sum(l.cr_amount for l in reversed_tax)
        gross = round(base_amount + total_tax, 2)

        lines: list[VoucherLine] = [
            VoucherLine(ledger_id=party_ledger_id, dr_amount=gross),
            VoucherLine(ledger_id=purchase_return_ledger_id, cr_amount=base_amount),
        ] + reversed_tax

        return VoucherDraft(
            voucher_type="DEBIT_NOTE",
            voucher_date=voucher_date,
            lines=lines,
            narration=narration,
            reference=reference,
        )

    def build_credit_note(
        self,
        voucher_date: str,
        party_ledger_id: int,
        sales_return_ledger_id: int,
        base_amount: float,
        gst_rate_pct: float = 18.0,
        narration: str = "",
        reference: str = "",
    ) -> VoucherDraft:
        """
        Build a Credit Note (sales return or downward revision).
        Dr: Sales Return + GST reversal   Cr: Party
        """
        tax_lines = self.gst.compute_gst(
            base_amount, gst_rate_pct, party_ledger_id, is_sales=True
        )
        # Flip Dr/Cr (reversal)
        reversed_tax = [
            VoucherLine(
                ledger_id=l.ledger_id,
                dr_amount=l.cr_amount, cr_amount=l.dr_amount,
                is_tax_line=l.is_tax_line, tax_type=l.tax_type,
                tax_rate=l.tax_rate, line_narration="GST Reversal: " + l.line_narration
            )
            for l in tax_lines
        ]
        total_tax = sum(l.dr_amount for l in reversed_tax)
        gross = round(base_amount + total_tax, 2)

        lines: list[VoucherLine] = [
            VoucherLine(ledger_id=sales_return_ledger_id, dr_amount=base_amount),
        ] + reversed_tax + [
            VoucherLine(ledger_id=party_ledger_id, cr_amount=gross),
        ]

        return VoucherDraft(
            voucher_type="CREDIT_NOTE",
            voucher_date=voucher_date,
            lines=lines,
            narration=narration,
            reference=reference,
        )

    # ── Post & Cancel ──────────────────────────────────────────────────────────

    def post(self, draft: VoucherDraft) -> PostedVoucher:
        """
        Validates and posts a VoucherDraft to the database.
        Returns a PostedVoucher with the assigned voucher number.
        Raises VoucherValidationError on failure.
        """
        # Validate
        self.validator.validate(draft)

        conn = self.db.connect()
        fy = VoucherNumberer.get_fy(draft.voucher_date)

        try:
            # Generate voucher number
            vno = self.numberer.next_number(draft.voucher_type, fy)

            # Insert voucher header
            cur = conn.execute(
                """INSERT INTO vouchers
                   (company_id, voucher_type, voucher_number, voucher_date,
                    narration, reference, total_amount, created_by, source, ai_confidence)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    self.company_id, draft.voucher_type, vno,
                    draft.voucher_date, draft.narration, draft.reference,
                    draft.total_dr,    # total_amount = total Dr side
                    self.user_id, draft.source, draft.ai_confidence,
                ),
            )
            voucher_id = cur.lastrowid

            # Insert voucher lines
            conn.executemany(
                """INSERT INTO voucher_lines
                   (voucher_id, ledger_id, dr_amount, cr_amount,
                    cost_centre, bill_ref, is_tax_line, tax_type,
                    tax_rate, line_narration)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                [
                    (
                        voucher_id, line.ledger_id,
                        line.dr_amount, line.cr_amount,
                        line.cost_centre, line.bill_ref,
                        int(line.is_tax_line), line.tax_type,
                        line.tax_rate, line.line_narration,
                    )
                    for line in draft.lines
                ],
            )

            # Audit log
            conn.execute(
                """INSERT INTO audit_log
                   (company_id, user_id, action, table_name, record_id, new_data)
                   VALUES (?,?,?,?,?,?)""",
                (
                    self.company_id, self.user_id, "CREATE",
                    "vouchers", voucher_id,
                    json.dumps({
                        "voucher_type": draft.voucher_type,
                        "voucher_number": vno,
                        "total": draft.total_dr,
                    }),
                ),
            )

            self.db.commit()

            return PostedVoucher(
                voucher_id=voucher_id,
                voucher_number=vno,
                voucher_type=draft.voucher_type,
                voucher_date=draft.voucher_date,
                total_amount=draft.total_dr,
                lines=draft.lines,
            )

        except Exception:
            self.db.rollback()
            raise

    def cancel_voucher(self, voucher_id: int, reason: str = "") -> None:
        """Mark a voucher as cancelled (soft delete, preserves audit trail)."""
        conn = self.db.connect()

        row = conn.execute(
            "SELECT * FROM vouchers WHERE id=? AND company_id=?",
            (voucher_id, self.company_id)
        ).fetchone()
        if not row:
            raise ValueError(f"Voucher {voucher_id} not found.")
        if row["is_cancelled"]:
            raise ValueError("Voucher is already cancelled.")

        conn.execute(
            """UPDATE vouchers SET is_cancelled=1, updated_at=datetime('now')
               WHERE id=?""",
            (voucher_id,)
        )
        conn.execute(
            """INSERT INTO audit_log
               (company_id, user_id, action, table_name, record_id, old_data)
               VALUES (?,?,?,?,?,?)""",
            (
                self.company_id, self.user_id, "CANCEL",
                "vouchers", voucher_id,
                json.dumps({"reason": reason, "voucher_number": row["voucher_number"]}),
            ),
        )
        self.db.commit()

    # ── Queries ───────────────────────────────────────────────────────────────

    def get_voucher(self, voucher_id: int) -> dict | None:
        """Fetch a posted voucher with all its lines."""
        conn = self.db.connect()
        row = conn.execute(
            "SELECT * FROM vouchers WHERE id=? AND company_id=?",
            (voucher_id, self.company_id)
        ).fetchone()
        if not row:
            return None

        lines = conn.execute(
            """SELECT vl.*, l.name as ledger_name
               FROM voucher_lines vl
               JOIN ledgers l ON vl.ledger_id = l.id
               WHERE vl.voucher_id = ?
               ORDER BY vl.id""",
            (voucher_id,)
        ).fetchall()

        return {
            **dict(row),
            "lines": [dict(l) for l in lines]
        }

    def list_vouchers(
        self,
        from_date: str | None = None,
        to_date: str | None = None,
        voucher_type: str | None = None,
        ledger_id: int | None = None,
        include_cancelled: bool = False,
        limit: int = 500,
        offset: int = 0,
    ) -> list[dict]:
        """List vouchers with optional filters."""
        q = "SELECT * FROM vouchers WHERE company_id=?"
        params: list = [self.company_id]

        if not include_cancelled:
            q += " AND is_cancelled=0"
        if from_date:
            q += " AND voucher_date >= ?"
            params.append(from_date)
        if to_date:
            q += " AND voucher_date <= ?"
            params.append(to_date)
        if voucher_type:
            q += " AND voucher_type = ?"
            params.append(voucher_type)
        if ledger_id:
            q += """ AND id IN (
                SELECT voucher_id FROM voucher_lines WHERE ledger_id=?
            )"""
            params.append(ledger_id)

        q += " ORDER BY voucher_date DESC, id DESC LIMIT ? OFFSET ?"
        params += [limit, offset]

        rows = self.db.execute(q, params).fetchall()
        return [dict(r) for r in rows]
