"""Chart of accounts — list ledgers with balances, add a ledger, and a
per-ledger statement."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Request, Depends, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from web.deps import get_company
from web.models import CompanyRef
from web import engine_bridge

router = APIRouter()
templates = Jinja2Templates(directory="web/templates")

# Common groups offered in the "add ledger" dropdown (seeded by the engine).
GROUPS = [
    "Sundry Debtors", "Sundry Creditors", "Bank Accounts", "Cash-in-Hand",
    "Sales Accounts", "Purchase Accounts", "Direct Expenses", "Indirect Expenses",
    "Direct Incomes", "Indirect Incomes", "Fixed Assets", "Current Assets",
    "Current Liabilities", "Loans (Liability)", "Capital Account",
]


@router.get("/c/{slug}/ledgers", response_class=HTMLResponse)
def ledgers_page(request: Request, slug: str, ref: CompanyRef = Depends(get_company)):
    tree = engine_bridge.tree_for(ref.slug, ref.company_id)
    ledgers = tree.get_all_ledgers()
    balances = tree.get_all_ledger_balances()
    for lg in ledgers:
        b = balances.get(lg["id"], {"balance": 0.0, "type": "Dr"})
        lg["balance"] = b["balance"]
        lg["bal_type"] = b["type"]
    return templates.TemplateResponse(request, "ledgers.html", {
        "request": request, "slug": slug, "company": ref,
        "ledgers": ledgers, "groups": GROUPS})


@router.post("/c/{slug}/ledgers")
def add_ledger(slug: str, name: str = Form(...), group_name: str = Form(...),
               opening_balance: float = Form(0.0), opening_type: str = Form("Dr"),
               ref: CompanyRef = Depends(get_company)):
    tree = engine_bridge.tree_for(ref.slug, ref.company_id)
    if name.strip():
        tree.add_ledger(name.strip(), group_name,
                        opening_balance=opening_balance, opening_type=opening_type)
    return RedirectResponse(f"/c/{slug}/ledgers", status_code=303)


@router.get("/c/{slug}/ledgers/{ledger_id}/statement", response_class=HTMLResponse)
def ledger_statement(request: Request, slug: str, ledger_id: int,
                     from_: str = Query(None, alias="from"), to: str = Query(None),
                     ref: CompanyRef = Depends(get_company)):
    today = date.today()
    f = from_ or today.replace(month=1, day=1).isoformat()
    t = to or today.isoformat()
    stmt = engine_bridge.reports_for(ref.slug, ref.company_id).ledger_account(
        ledger_id, f, t)
    return templates.TemplateResponse(request, "ledger_statement.html", {
        "request": request, "slug": slug, "company": ref,
        "stmt": stmt, "from_": f, "to": t})
