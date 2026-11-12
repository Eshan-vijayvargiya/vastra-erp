from datetime import timedelta

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..db import get_db
from ..models import STAGES, BomLine, Product, StockMove, WorkOrder
from ..services import metrics, ops
from ..web import TODAY, flash, render, require_user

router = APIRouter()


@router.get("/production")
def production(request: Request, wo: int | None = None, db: Session = Depends(get_db), user=Depends(require_user)):
    opts = selectinload(WorkOrder.product).selectinload(Product.bom).selectinload(BomLine.material)
    open_wos = db.scalars(select(WorkOrder).where(WorkOrder.stage != "Packed").options(opts).order_by(WorkOrder.due_date)).all()
    packed = db.scalars(select(WorkOrder).where(WorkOrder.stage == "Packed", WorkOrder.done_date > TODAY - timedelta(days=7))
                        .options(opts).order_by(WorkOrder.done_date.desc()).limit(3)).all()
    board = {s: [w for w in open_wos if w.stage == s] for s in STAGES}
    board["Packed"] = packed
    done30 = db.scalars(select(WorkOrder).where(WorkOrder.done_date > TODAY - timedelta(days=30))).all()
    on_time = round(100 * sum(w.done_date <= w.due_date for w in done30) / len(done30)) if done30 else None
    made_week = db.scalar(select(func.sum(StockMove.qty)).where(StockMove.reason == "production",
                                                                StockMove.move_date > TODAY - timedelta(days=7))) or 0
    running = [w for w in open_wos if w.stage != "Planned"]
    sel = next((w for w in open_wos if w.id == wo), None) or (running[0] if running else (open_wos[0] if open_wos else None))
    bom_rows, cost = [], 0
    if sel:
        stock = metrics.material_stock(db)
        for b in sel.product.bom:
            need = b.qty * sel.qty
            have = stock.get(b.material_id, 0)
            cost += b.qty * b.material.cost
            bom_rows.append(dict(b=b, need=need, have=have,
                                 ok=(sel.stage != "Planned") or have >= need))
        cost += sel.product.labour_cost
    products = db.scalars(select(Product).order_by(Product.category, Product.sku)).all()
    return render(request, "production.html", active="Production", board=board, sel=sel, bom_rows=bom_rows, cost=cost,
                  n_open=len(open_wos), n_running=len(running), lines=len({w.line for w in running}),
                  made_week=made_week, on_time=on_time, products=products)


@router.post("/production/{wo_id}/advance")
def advance(wo_id: int, request: Request, db: Session = Depends(get_db), user=Depends(require_user)):
    try:
        wo = ops.advance_work_order(db, wo_id, TODAY)
        flash(request, f"{wo.number} moved to {wo.stage}." + (" Finished stock added." if wo.stage == "Packed" else "")
              + (" Materials taken from stock." if wo.stage == "Cutting" else ""))
    except ops.ActionError as e:
        flash(request, str(e), "err")
    return RedirectResponse(f"/production?wo={wo_id}", status_code=303)


@router.post("/production/new")
def new_wo(request: Request, product_id: int = Form(...), qty: float = Form(...), db: Session = Depends(get_db),
           user=Depends(require_user)):
    try:
        wo = ops.create_work_order(db, product_id, qty, TODAY)
        flash(request, f"{wo.number} created for {qty:,.0f} × {wo.product.name if wo.product else ''}. Start it when the materials are ready.")
        return RedirectResponse(f"/production?wo={wo.id}", status_code=303)
    except ops.ActionError as e:
        flash(request, str(e), "err")
        return RedirectResponse("/production", status_code=303)
