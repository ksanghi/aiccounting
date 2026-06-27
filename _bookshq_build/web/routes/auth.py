"""Email + password auth: signup, login, logout."""
from __future__ import annotations

from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from web.config import settings
from web.db import get_db
from web.deps import current_user
from web.models import User
from web.security import hash_password, verify_password, make_session_token

router = APIRouter()
templates = Jinja2Templates(directory="web/templates")

_MAX_AGE = settings.session_max_age_days * 86400


def _set_session(resp: RedirectResponse, user_id: int) -> RedirectResponse:
    resp.set_cookie(
        settings.session_cookie, make_session_token(user_id),
        max_age=_MAX_AGE, httponly=True, samesite="lax", secure=True)
    return resp


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request, user=Depends(current_user)):
    if user:
        return RedirectResponse("/companies", status_code=303)
    return templates.TemplateResponse(request, "auth/login.html", {"request": request})


@router.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...),
          db: Session = Depends(get_db)):
    email = email.strip().lower()
    user = db.query(User).filter_by(email=email).first()
    if not user or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(
            "auth/login.html",
            {"request": request, "error": "Wrong email or password.", "email": email},
            status_code=400)
    return _set_session(RedirectResponse("/companies", status_code=303), user.id)


@router.get("/signup", response_class=HTMLResponse)
def signup_form(request: Request, user=Depends(current_user)):
    if user:
        return RedirectResponse("/companies", status_code=303)
    return templates.TemplateResponse(request, "auth/signup.html", {"request": request})


@router.post("/signup")
def signup(request: Request, name: str = Form(""), email: str = Form(...),
           password: str = Form(...), db: Session = Depends(get_db)):
    email = email.strip().lower()
    ctx = {"request": request, "name": name, "email": email}
    if len(password) < 8:
        return templates.TemplateResponse(
            "auth/signup.html", {**ctx, "error": "Password must be at least 8 characters."},
            status_code=400)
    if db.query(User).filter_by(email=email).first():
        return templates.TemplateResponse(
            "auth/signup.html", {**ctx, "error": "That email is already registered."},
            status_code=400)
    user = User(email=email, name=name.strip(), password_hash=hash_password(password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return _set_session(RedirectResponse("/companies", status_code=303), user.id)


@router.post("/logout")
def logout():
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(settings.session_cookie)
    return resp
