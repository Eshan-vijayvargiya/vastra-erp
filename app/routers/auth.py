from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User, WorkOrder
from ..seed import verify_password
from ..web import flash, render

router = APIRouter()

TILES = [("school-shirt.jpg", "Uniforms", "Shirts, trousers and tunics for schools in Kota and nearby."),
         ("saree-red.jpg", "Sarees", "Banarasi-style silk to daily-wear cotton, busiest before Diwali."),
         ("flag-tricolour.jpg", "Flags", "National flags in four sizes, ahead of 26 January and 15 August."),
         ("fabric-rolls-pattern.jpg", "Fabric by the metre", "Shirting, poplin, cambric and latha for retailers.")]


@router.get("/login")
def login_page(request: Request, db: Session = Depends(get_db)):
    if request.session.get("user"):
        return RedirectResponse("/", status_code=303)
    running = db.scalar(select(func.count()).select_from(WorkOrder).where(WorkOrder.stage.not_in(["Planned", "Packed"])))
    return render(request, "login.html", running=running, tiles=TILES)


@router.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == email.strip().lower()))
    if not user or not verify_password(password, user.password_hash):
        flash(request, "That email and password don't match. Try the demo login below the form.", "err")
        return RedirectResponse("/login", status_code=303)
    request.session["user"] = {"id": user.id, "name": user.name}
    return RedirectResponse("/", status_code=303)


@router.post("/demo")
def demo(request: Request, db: Session = Depends(get_db)):
    user = db.scalar(select(User).order_by(User.id))
    request.session["user"] = {"id": user.id, "name": user.name}
    return RedirectResponse("/", status_code=303)


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)
