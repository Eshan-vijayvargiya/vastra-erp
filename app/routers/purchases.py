from collections import defaultdict
from datetime import timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..db import get_db
from ..models import PurchaseOrder, PurchaseOrderLine, Supplier
from ..services import metrics, ops
from ..web import TODAY, flash, render, require_user

router = APIRouter()


@router.get("/purchases")
def purchases(request: Request, db: Session = Depends(get_db), user=Depends(require_user)):
    mats = [r for r in metrics.material_status(db, TODAY) if r["status"] == "Reorder"]
    by_sup = defaultdict(list)
    for r in mats:
        by_sup[r["m"].supplier.name].append(r)
    opts = (selectinload(PurchaseOrder.lines).selectinload(PurchaseOrderLine.material), selectinload(PurchaseOrder.supplier),
            selectinload(PurchaseOrder.payments))
    open_pos = db.scalars(select(PurchaseOrder).where(PurchaseOrder.status == "Ordered").options(*opts)
                          .order_by(PurchaseOrder.expected_date)).all()
    recent = db.scalars(select(PurchaseOrder).where(PurchaseOrder.status == "Received").options(*opts)
                        .order_by(PurchaseOrder.received_date.desc()).limit(8)).all()
    pay = metrics.payables(db, TODAY)
    # supplier scorecard over the last 12 months: how often they deliver on time
    year = db.scalars(select(PurchaseOrder).where(PurchaseOrder.received_date > TODAY - timedelta(days=365)).options(*opts)).all()
    score = defaultdict(lambda: dict(n=0, on_time=0, value=0.0, late_days=0))
    for po in year:
        s = score[po.supplier_id]
        s["n"] += 1
        s["on_time"] += po.received_date <= po.expected_date
        s["value"] += po.amount
        s["late_days"] += max(0, (po.received_date - po.expected_date).days)
    sups = db.scalars(select(Supplier).order_by(Supplier.name)).all()
    return render(request, "purchases.html", active="Purchases", by_sup=dict(by_sup), n_reorder=len(mats),
                  open_pos=open_pos, recent=recent, pay=pay, sups=sups, score=score,
                  spend=sum(s["value"] for s in score.values()))


@router.post("/purchases/raise")
async def raise_po(request: Request, db: Session = Depends(get_db), user=Depends(require_user)):
    form = await request.form()
    ids = {int(x) for x in form.getlist("material_id")}
    status = {r["m"].id: r for r in metrics.material_status(db, TODAY)}
    wanted = {}
    for mid in ids:
        r = status.get(mid)
        if r:
            wanted[mid] = r["suggest"] or r["m"].reorder_qty or round(r["eoq"])
    try:
        pos = ops.raise_purchase_orders(db, wanted, TODAY)
        flash(request, "Raised " + ", ".join(f"{po.number} ({po.supplier.name if po.supplier else ''})" for po in pos) + ".")
    except ops.ActionError as e:
        flash(request, str(e), "err")
    return RedirectResponse("/purchases", status_code=303)


@router.post("/purchases/{po_id}/receive")
def receive(po_id: int, request: Request, db: Session = Depends(get_db), user=Depends(require_user)):
    try:
        po = ops.receive_po(db, po_id, TODAY)
        flash(request, f"{po.number} received. Materials added to stock.")
    except ops.ActionError as e:
        flash(request, str(e), "err")
    return RedirectResponse("/purchases", status_code=303)


@router.post("/purchases/{po_id}/pay")
def pay(po_id: int, request: Request, db: Session = Depends(get_db), user=Depends(require_user)):
    try:
        sp = ops.pay_supplier(db, po_id, TODAY)
        flash(request, f"Paid {metrics.rupees(sp.amount)} to the supplier.")
    except ops.ActionError as e:
        flash(request, str(e), "err")
    return RedirectResponse("/purchases#payables", status_code=303)
