"""
Unified document processor for the AI Documents Inbox (the merge of the old
AI Document Reader + Document Inbox surfaces).

ONE entry point — `process_document(filepath, type_override, ...)` — is used by
the per-doc "Process now", the type-override branch, and the auto-process-all
checkbox. It implements the agreed 3-branch logic (DECISIONS 2026-06-21):

  • type_override is None  (the user didn't set a type)
        → AI: classify + extract in one pass  (VoucherAI.extract_auto)
  • type_override has a LOCAL parser registered (e.g. bank_statement)
        → LOCAL parse — no AI, no credits  (falls back to AI if local fails)
  • type_override has no local parser yet (e.g. an invoice PDF)
        → AI extract WITH the known type  (VoucherAI.extract_vouchers) — cheaper
          than auto, it skips the classify step

Local parsers are a REGISTRY keyed by doc_type, so any type can become local
over time (bank statements today; CSV/Excel and e-invoices are good next ones).
Nothing is hardwired to bank statements — "known type ⇒ try local first" is the
rule for every type.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ProcessResult:
    """Outcome of processing one document. `route` tells the caller where the
    result goes: voucher drafts for review/post, or a parsed bank statement for
    reconciliation."""
    doc_type:    str                         # purchase_invoice | sales_invoice | … | bank_statement | other
    route:       str                         # "vouchers" | "bank_statement" | "ledger_statement"
    used_ai:     bool                         # False when a local parser handled it (no credits/key)
    vouchers:    list = field(default_factory=list)   # route == "vouchers"
    bank_parse:  object | None = None         # route == bank/ledger_statement (a local ParseResult)
    confidence:  float = 0.0                  # type confidence (auto branch)
    summary:     dict = field(default_factory=dict)   # {party, doc_number, doc_date, amount}
    text_result: object | None = None         # the DocumentParser ParseResult (pages/cost), AI branches


# ── Local parser registry: doc_type → callable(filepath) → ParseResult|None ──
def _local_bank_statement(filepath: str):
    """OFX/CSV/Excel bank statements parse deterministically — no AI."""
    try:
        from core.local_statement_parser import LocalDocumentParser
        return LocalDocumentParser().parse_bank_statement(filepath)
    except Exception:
        return None


def _local_ledger_statement(filepath: str):
    """CSV/Excel/PDF ledger (party) statements parse deterministically — no AI."""
    try:
        from core.local_statement_parser import LocalDocumentParser
        return LocalDocumentParser().parse_ledger(filepath)
    except Exception:
        return None


# Extend this as local parsers are built (csv/excel tabular, e-invoice XML/JSON…).
LOCAL_PARSERS: dict = {
    "bank_statement":   _local_bank_statement,
    "ledger_statement": _local_ledger_statement,
}


def has_local_parser(doc_type: str) -> bool:
    return doc_type in LOCAL_PARSERS


def process_document(filepath: str, type_override: str | None,
                     ledger_names: list, company_name: str) -> ProcessResult:
    """Process ONE document down exactly one of the three branches above.

    `type_override` = the doc_type the user set on the row, or None for Auto.
    Raises ValueError if the file can't be read and no local parser handled it.
    """
    # ── Branch B: known type WITH a local parser → try local first (no AI) ──
    if type_override and type_override in LOCAL_PARSERS:
        local = LOCAL_PARSERS[type_override](filepath)
        if local is not None and getattr(local, "success", False):
            return ProcessResult(
                doc_type=type_override, route=type_override,  # bank_statement | ledger_statement
                used_ai=False, bank_parse=local,
            )
        # local couldn't handle this file → fall through to the AI path

    # The AI branches need the document text first (local text extraction —
    # pdfplumber/etc — happens here; Claude is only called on the text).
    from ai.document_parser import DocumentParser
    result = DocumentParser().parse(filepath)
    if not result.success:
        raise ValueError(result.error or "Could not read the document.")

    from ai.voucher_ai import VoucherAI

    # ── Branch C: known type, no local parser → AI extract WITH the type ──
    if type_override:
        vouchers = VoucherAI().extract_vouchers(
            result.full_text, ledger_names, type_override, company_name)
        return ProcessResult(
            doc_type=type_override, route="vouchers",
            used_ai=True, vouchers=vouchers, text_result=result,
        )

    # ── Branch A: Auto → AI classify + extract in one pass ──
    auto = VoucherAI().extract_auto(result.full_text, ledger_names, company_name)
    return ProcessResult(
        doc_type=auto.get("doc_type", "other"),
        route="vouchers",
        used_ai=True,
        vouchers=auto.get("vouchers", []),
        confidence=auto.get("confidence", 0.0),
        summary=auto.get("summary", {}),
        text_result=result,
    )
