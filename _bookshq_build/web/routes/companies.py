"""Company picker — create / list / enter a company (engine books file)."""
from __future__ import annotations

from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from web.db import get_db
from web.deps import current_user, current_account
from web.models import Account, CompanyRef
from web import engine_bridge

router = APIRouter()
templates = Jinja2Templates(directory="web/templates")


@router.get("/")
def root(user=Depends(current_user)):
    return RedirectResponse("/companies" if user else "/login", status_code=303)


@router.get("/companies", response_class=HTMLResponse)
def list_companies(request: Request, db: Session = Depends(get_db),
                   acct: Account = Depends(current_account)):
    refs = (db.query(CompanyRef).filter_by(account_id=acct.id)
            .order_by(CompanyRef.created_at.desc()).all())
    return templates.TemplateResponse(
        "companies.html", {"request": request, "companies": refs, "account": acct})


@router.post("/companies")
def create_company(display_name: str = Form(...), db: Session = Depends(get_db),
                   acct: Account = Depends(current_account)):
    name = display_name.strip() or "My Company"
    slug, company_id = engine_bridge.create_company(name)
    db.add(CompanyRef(account_id=acct.id, slug=slug,
                      company_id=company_id, display_name=name))
    db.commit()
    return RedirectResponse(f"/c/{slug}/", status_code=303)
