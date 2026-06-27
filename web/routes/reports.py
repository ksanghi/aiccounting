"""Reports — TB, P&L, Balance Sheet, A/R & A/P aging, and the US tax
reports (Schedule C, Form 1099)."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Request, Depends, Query
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from web.deps import get_company
from web.models import CompanyRef
from web import engine_bridge

router = APIRouter()
templates = Jinja2Templates(directory="web/templates")


def _today() -> str:
    return date.today().isoformat()


def _year_start() -> str:
    return date.today().replace(month=1, day=1).isoformat()


def _r(request, slug, ref, template, **extra):
    return templates.TemplateResponse(
        request, template, {"slug": slug, "company": ref, **extra})


@router.get("/c/{slug}/reports", response_class=HTMLResponse)
def index(request: Request, slug: str, ref: CompanyRef = Depends(get_company)):
    return _r(request, slug, ref, "reports/index.html")


@router.get("/c/{slug}/reports/trial-balance", response_class=HTMLResponse)
def trial_balance(request: Request, slug: str, as_of: str = Query(None),
                  ref: CompanyRef = Depends(get_company)):
    a = as_of or _today()
    rows = engine_bridge.reports_for(ref.slug, ref.company_id).trial_balance(a)
    return _r(request, slug, ref, "reports/trial_balance.html", rows=rows, as_of=a)


@router.get("/c/{slug}/reports/pnl", response_class=HTMLResponse)
def pnl(request: Request, slug: str, from_: str = Query(None, alias="from"),
        to: str = Query(None), ref: CompanyRef = Depends(get_company)):
    f, t = (from_ or _year_start()), (to or _today())
    data = engine_bridge.reports_for(ref.slug, ref.company_id).profit_and_loss(f, t)
    return _r(request, slug, ref, "reports/pnl.html", d=data, from_=f, to=t)


@router.get("/c/{slug}/reports/balance-sheet", response_class=HTMLResponse)
def balance_sheet(request: Request, slug: str, as_of: str = Query(None),
                  ref: CompanyRef = Depends(get_company)):
    a = as_of or _today()
    data = engine_bridge.reports_for(ref.slug, ref.company_id).balance_sheet(a)
    return _r(request, slug, ref, "reports/balance_sheet.html", d=data, as_of=a)


@router.get("/c/{slug}/reports/receivables", response_class=HTMLResponse)
def receivables(request: Request, slug: str, as_of: str = Query(None),
                ref: CompanyRef = Depends(get_company)):
    a = as_of or _today()
    data = engine_bridge.reports_for(ref.slug, ref.company_id).receivables_aging(a)
    return _r(request, slug, ref, "reports/aging.html", d=data, as_of=a,
              title="Receivables Aging (A/R)")


@router.get("/c/{slug}/reports/payables", response_class=HTMLResponse)
def payables(request: Request, slug: str, as_of: str = Query(None),
             ref: CompanyRef = Depends(get_company)):
    a = as_of or _today()
    data = engine_bridge.reports_for(ref.slug, ref.company_id).payables_aging(a)
    return _r(request, slug, ref, "reports/aging.html", d=data, as_of=a,
              title="Payables Aging (A/P)")


@router.get("/c/{slug}/reports/schedule-c", response_class=HTMLResponse)
def schedule_c(request: Request, slug: str, from_: str = Query(None, alias="from"),
               to: str = Query(None), ref: CompanyRef = Depends(get_company)):
    f, t = (from_ or _year_start()), (to or _today())
    data = engine_bridge.reports_for(ref.slug, ref.company_id).schedule_c(f, t)
    return _r(request, slug, ref, "reports/schedule_c.html", d=data, from_=f, to=t)


@router.get("/c/{slug}/reports/form-1099", response_class=HTMLResponse)
def form_1099(request: Request, slug: str, from_: str = Query(None, alias="from"),
              to: str = Query(None), ref: CompanyRef = Depends(get_company)):
    f, t = (from_ or _year_start()), (to or _today())
    data = engine_bridge.reports_for(ref.slug, ref.company_id).form_1099(f, t)
    return _r(request, slug, ref, "reports/form_1099.html", d=data, from_=f, to=t)
