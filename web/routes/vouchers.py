"""Post vouchers (all 8 types) + the day book."""
from __future__ import annotations

from datetime import date
from typing import Optional, List

from fastapi import APIRouter, Request, Depends, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from web.deps import get_company
from web.models import CompanyRef
from web import engine_bridge
from core.voucher_engine import VoucherLine

router = APIRouter()
templates = Jinja2Templates(directory="web/templates")

VTYPES = ["PAYMENT", "RECEIPT", "CONTRA", "SALES", "PURCHASE",
          "JOURNAL", "DEBIT_NOTE", "CREDIT_NOTE"]


def _ledgers(ref: CompanyRef):
    return engine_bridge.tree_for(ref.slug, ref.company_id).get_all_ledgers()


@router.get("/c/{slug}/vouchers", response_class=HTMLResponse)
def daybook(request: Request, slug: str, from_: str = Query(None, alias="from"),
            to: str = Query(None), posted: str = Query(None),
            ref: CompanyRef = Depends(get_company)):
    today = date.today()
    f = from_ or today.replace(month=1, day=1).isoformat()
    t = to or today.isoformat()
    rows = engine_bridge.reports_for(ref.slug, ref.company_id).day_book(f, t)
    return templates.TemplateResponse(request, "daybook.html", {
        "request": request, "slug": slug, "company": ref,
        "rows": list(reversed(rows)), "from_": f, "to": t, "posted": posted})


@router.get("/c/{slug}/vouchers/new", response_class=HTMLResponse)
def new_voucher(request: Request, slug: str, type: str = "PAYMENT",
                ref: CompanyRef = Depends(get_company)):
    vt = type.upper()
    vt = vt if vt in VTYPES else "PAYMENT"
    return templates.TemplateResponse(request, "voucher_form.html", {
        "request": request, "slug": slug, "company": ref, "vtype": vt,
        "vtypes": VTYPES, "ledgers": _ledgers(ref), "today": date.today().isoformat()})


@router.post("/c/{slug}/vouchers")
def post_voucher(
    request: Request, slug: str, ref: CompanyRef = Depends(get_company),
    vtype: str = Form(...), voucher_date: str = Form(...),
    narration: str = Form(""), reference: str = Form(""),
    ledger_a: int = Form(0), ledger_b: int = Form(0),
    amount: float = Form(0.0), gst_rate: float = Form(0.0),
    j_ledger: Optional[List[int]] = Form(None),
    j_dr: Optional[List[float]] = Form(None),
    j_cr: Optional[List[float]] = Form(None),
):
    eng = engine_bridge.engine_for(ref.slug, ref.company_id)
    vt = vtype.upper()
    try:
        if vt == "PAYMENT":
            draft = eng.build_payment(voucher_date, ledger_a, ledger_b, amount, narration, reference)
        elif vt == "RECEIPT":
            draft = eng.build_receipt(voucher_date, ledger_a, ledger_b, amount, narration, reference)
        elif vt == "CONTRA":
            draft = eng.build_contra(voucher_date, ledger_a, ledger_b, amount, narration)
        elif vt == "SALES":
            draft = eng.build_sales(voucher_date, ledger_a, ledger_b, amount, gst_rate, narration, reference)
        elif vt == "PURCHASE":
            draft = eng.build_purchase(voucher_date, ledger_a, ledger_b, amount, gst_rate, narration, reference)
        elif vt == "DEBIT_NOTE":
            draft = eng.build_debit_note(voucher_date, ledger_a, ledger_b, amount, gst_rate, narration, reference)
        elif vt == "CREDIT_NOTE":
            draft = eng.build_credit_note(voucher_date, ledger_a, ledger_b, amount, gst_rate, narration, reference)
        elif vt == "JOURNAL":
            jl, jd, jc = (j_ledger or []), (j_dr or []), (j_cr or [])
            lines: List[VoucherLine] = []
            for i, lid in enumerate(jl):
                dr = jd[i] if i < len(jd) else 0.0
                cr = jc[i] if i < len(jc) else 0.0
                if lid and (dr or cr):
                    lines.append(VoucherLine(ledger_id=int(lid),
                                             dr_amount=float(dr or 0),
                                             cr_amount=float(cr or 0)))
            draft = eng.build_journal(voucher_date, lines, narration, reference)
        else:
            raise ValueError("Unknown voucher type.")
        posted = eng.post(draft)
    except Exception as exc:
        return templates.TemplateResponse(request, "voucher_form.html", {
            "request": request, "slug": slug, "company": ref, "vtype": vt,
            "vtypes": VTYPES, "ledgers": _ledgers(ref), "today": voucher_date,
            "error": str(exc)}, status_code=400)
    return RedirectResponse(
        f"/c/{slug}/vouchers?posted={posted.voucher_number}", status_code=303)
