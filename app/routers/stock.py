from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..db import get_db
from ..models import BomLine, Product
from ..services import metrics
from ..web import TODAY, render, require_user

router = APIRouter()


@router.get("/stock")
def stock(request: Request, db: Session = Depends(get_db), user=Depends(require_user)):
    prods = metrics.product_status(db)
    mats = metrics.material_status(db, TODAY)
    full = {p.id: p for p in db.scalars(select(Product).options(selectinload(Product.bom).selectinload(BomLine.material)))}
    goods_value = sum(max(r["have"], 0) * metrics.unit_cost(full[r["p"].id]) for r in prods)
    mat_value = sum(max(r["have"], 0) * r["m"].cost for r in mats)
    order = {"Short": 0, "Reorder": 0, "Low": 1, "OK": 2}
    prods.sort(key=lambda r: (order[r["status"]], r["p"].category, r["p"].sku))
    mats.sort(key=lambda r: (order[r["status"]], r["m"].code))
    return render(request, "stock.html", active="Stock", prods=prods, mats=mats, goods_value=goods_value, mat_value=mat_value,
                  n_reorder=sum(r["status"] == "Reorder" for r in mats), n_low=sum(r["status"] != "OK" for r in prods))
