from datetime import timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from ..db import get_db
from ..models import Customer, Invoice, Product, SalesOrder, SalesOrderLine
from ..services import metrics, ops
from ..web import TODAY, flash, render, require_user

router = APIRouter()


@router.get("/sales")
def sales(request: Request, q: str = "", db: Session = Depends(get_db), user=Depends(require_user)):
    opts = (selectinload(SalesOrder.customer), selectinload(SalesOrder.lines).selectinload(SalesOrderLine.product))
    stmt = select(SalesOrder).join(Customer).options(*opts)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Customer.name.ilike(like), SalesOrder.number.ilike(like)))
        orders = db.scalars(stmt.order_by(SalesOrder.order_date.desc()).limit(40)).all()
    else:
        orders = db.scalars(stmt.where(SalesOrder.status == "Open").order_by(SalesOrder.due_date)).all()
    stock = metrics.product_stock(db)
    shippable = {o.id: ops.can_ship(o, stock) for o in orders if o.status == "Open"}
    rec = metrics.receivables(db, TODAY)
    shipped90 = db.scalars(select(SalesOrder).where(SalesOrder.shipped_date > TODAY - timedelta(days=90))).all()
    avg_days = sum((o.shipped_date - o.order_date).days for o in shipped90) / len(shipped90) if shipped90 else None
    on_time = 100 * sum(o.shipped_date <= o.due_date for o in shipped90) / len(shipped90) if shipped90 else None
    # customers: sales in the last 12 months and money they owe
    year = db.execute(select(SalesOrder.customer_id, func.sum(SalesOrderLine.qty * SalesOrderLine.price))
                      .join(SalesOrderLine).where(SalesOrder.order_date > TODAY - timedelta(days=365))
                      .group_by(SalesOrder.customer_id)).all()
    owed = {}
    for inv, bal, late in rec["open"]:
        owed[inv.customer_id] = owed.get(inv.customer_id, 0) + bal
    custs = {c.id: c for c in db.scalars(select(Customer))}
    top = sorted(((custs[cid], v, owed.get(cid, 0)) for cid, v in year), key=lambda t: -t[1])[:12]
    products = db.scalars(select(Product).order_by(Product.category, Product.sku)).all()
    return render(request, "sales.html", active="Sales", orders=orders, q=q, shippable=shippable, rec=rec,
                  avg_days=avg_days, on_time=on_time, top=top, customers=sorted(custs.values(), key=lambda c: c.name),
                  products=products, open_value=sum(o.amount for o in orders if o.status == "Open"))


@router.post("/sales/new")
async def new_order(request: Request, db: Session = Depends(get_db), user=Depends(require_user)):
    form = await request.form()
    lines = []
    for i in range(1, 4):
        pid, qty = form.get(f"product_{i}"), form.get(f"qty_{i}")
        if pid and qty:
            try:
                lines.append((int(pid), float(qty)))
            except ValueError:
                pass
    try:
        so = ops.create_sales_order(db, int(form.get("customer_id") or 0), lines, TODAY)
        flash(request, f"{so.number} booked for {metrics.rupees(so.amount)}. Ship it when the goods are ready.")
    except ops.ActionError as e:
        flash(request, str(e), "err")
    return RedirectResponse("/sales", status_code=303)


@router.post("/sales/{so_id}/ship")
def ship(so_id: int, request: Request, db: Session = Depends(get_db), user=Depends(require_user)):
    try:
        inv = ops.ship_order(db, so_id, TODAY)
        flash(request, f"Shipped. Invoice {inv.number} for {metrics.rupees(inv.amount)} is due on {inv.due_date:%d %b}.")
    except ops.ActionError as e:
        flash(request, str(e), "err")
    return RedirectResponse("/sales", status_code=303)


@router.post("/invoices/{inv_id}/pay")
def pay(inv_id: int, request: Request, db: Session = Depends(get_db), user=Depends(require_user)):
    try:
        p = ops.record_payment(db, inv_id, TODAY)
        flash(request, f"Payment of {metrics.rupees(p.amount)} recorded.")
    except ops.ActionError as e:
        flash(request, str(e), "err")
    return RedirectResponse("/sales#invoices", status_code=303)
