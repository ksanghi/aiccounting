"""Request dependencies — current user, login gate, and company scoping."""
from __future__ import annotations

from typing import Optional

from fastapi import Request, Depends, HTTPException, status
from sqlalchemy.orm import Session

from web.config import settings
from web.db import get_db
from web.models import User, Account, CompanyRef
from web.security import read_session_token


def current_user(request: Request, db: Session = Depends(get_db)) -> Optional[User]:
    token = request.cookies.get(settings.session_cookie)
    payload = read_session_token(token or "")
    if not payload:
        return None
    return db.get(User, payload.get("uid"))


def login_required(user: Optional[User] = Depends(current_user)) -> User:
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER, headers={"location": "/login"})
    return user


def current_account(
    db: Session = Depends(get_db), user: User = Depends(login_required)
) -> Account:
    """The user's account (tenant). Auto-creates one on first use so a
    brand-new signup can immediately make a company."""
    acct = db.query(Account).filter_by(owner_id=user.id).first()
    if acct is None:
        acct = Account(name=(user.name or user.email.split("@")[0]) + "'s books",
                       owner_id=user.id, plan="FREE")
        db.add(acct)
        db.commit()
        db.refresh(acct)
    return acct


def get_company(
    slug: str,
    db: Session = Depends(get_db),
    user: User = Depends(login_required),
) -> CompanyRef:
    """Resolve a company by slug and verify it belongs to the signed-in
    user's account. Redirects to the picker if not."""
    ref = db.query(CompanyRef).filter_by(slug=slug).first()
    if ref is None:
        raise HTTPException(404, "Company not found")
    acct = db.get(Account, ref.account_id)
    if acct is None or acct.owner_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER, headers={"location": "/companies"})
    return ref
