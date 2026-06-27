"""Per-company dashboard — quick stats + recent activity."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from web.deps import get_company
from web.models import CompanyRef
from web import engine_bridge

router = APIRouter()
templates = Jinja2Templates(directory="web/templates")


@router.get("/c/{slug}/", response_class=HTMLResponse)
def dashboard(request: Request, slug: str, ref: CompanyRef = Depends(get_company)):
    today = date.today()
    year_start = today.replace(month=1, day=1).isoformat()
    tree = engine_bridge.tree_for(ref.slug, ref.company_id)
    n_ledgers = len(tree.get_all_ledgers())
    rpt = engine_bridge.reports_for(ref.slug, ref.company_id)
    day_rows = rpt.day_book(year_start, today.isoformat())
    pnl = rpt.profit_and_loss(year_start, today.isoformat())
    return templates.TemplateResponse(request, "dashboard.html", {
        "request": request, "slug": slug, "company": ref,
        "n_ledgers": n_ledgers, "n_vouchers": len(day_rows),
        "recent": list(reversed(day_rows))[:10], "pnl": pnl,
        "year_start": year_start, "today": today.isoformat(),
    })
