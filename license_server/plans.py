"""
Server-side source of truth for plan features and limits.

Mirrors core/license_manager.py on the desktop client. The desktop has its own
copy as a fallback for when the server is unreachable; this is what gets
returned from /license/validate and is what should be authoritative.
"""

PLANS = ["FREE", "STANDARD", "PRO", "PREMIUM"]

PLAN_LIMITS = {
    "FREE":     5_000,
    "STANDARD": 20_000,
    "PRO":      50_000,
    "PREMIUM":  100_000,
}

PLAN_USER_LIMITS = {
    "FREE":     1,
    "STANDARD": 2,
    "PRO":      5,
    "PREMIUM":  999,
}

PLAN_FEATURES = {
    "FREE": [
        "vouchers",
        "daybook",
        "ledger_balances",
        "backup",
    ],
    "STANDARD": [
        "vouchers",
        "daybook",
        "ledger_balances",
        "reports",
        "export_excel",
        "export_pdf",
        "bank_reconciliation",
        "ledger_reconciliation",
        "book_migration",
        "backup",
        "multi_user_2",
    ],
    "PRO": [
        "vouchers",
        "daybook",
        "ledger_balances",
        "reports",
        "export_excel",
        "export_pdf",
        "bank_reconciliation",
        "ledger_reconciliation",
        "book_migration",
        "backup",
        "multi_user_5",
        "gst",
        "tds",
        "ai_document_reader",
        "verbal_entry",
        "auto_billing",
    ],
    "PREMIUM": [
        "vouchers",
        "daybook",
        "ledger_balances",
        "reports",
        "export_excel",
        "export_pdf",
        "bank_reconciliation",
        "ledger_reconciliation",
        "book_migration",
        "backup",
        "multi_user_unlimited",
        "gst",
        "tds",
        "ai_document_reader",
        "verbal_entry",
        "auto_billing",
        "whatsapp",
        "audit_export",
        "api_access",
        "verticals",
    ],
}
