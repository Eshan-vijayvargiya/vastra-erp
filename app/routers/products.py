from datetime import timedelta

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..db import get_db
from ..models import BomLine, Product, SalesOrder, SalesOrderLine
from ..services import charts, metrics
from ..services.metrics import unit_cost
from ..web import TODAY, render, require_user

router = APIRouter()
CAT_PHOTOS = {"Uniforms": "blue-shirts.jpg", "Sarees": "saree-red.jpg", "Flags": "flag-tricolour.jpg",
              "Fabric": "fabric-rolls-pattern.jpg", "Dhoti & Safi": "white-textile.jpg"}


@router.get("/products")
def product_list(request: Request, cat: str | None = None, sort: str = "sales", db: Session = Depends(get_db),
                 user=Depends(require_user)):
    statuses = {s["p"].id: s for s in metrics.product_status(db)}
    df = metrics.sales_lines_df(db)
    last_year = df[df["date"] > pd.Timestamp(TODAY - timedelta(days=365))].groupby("sku")["value"].sum()
    prods = db.scalars(select(Product).options(selectinload(Product.bom).selectinload(BomLine.material))).all()
    if cat:
        prods = [p for p in prods if p.category == cat]
    rows = [dict(p=p, st=statuses[p.id], sales=float(last_year.get(p.sku, 0)), cost=unit_cost(p)) for p in prods]
    if sort == "stock":
        rows.sort(key=lambda r: r["st"]["free"] / max(r["p"].safety_stock, 1))
    elif sort == "price":
        rows.sort(key=lambda r: -r["p"].price)
    else:
        rows.sort(key=lambda r: -r["sales"])
    # feature panel: how much bigger the uniform season is than February, from last year's data
    m = metrics.monthly_by_category(df)["Uniforms"]
    feb = m[m.index.month == 2].iloc[-1] if (m.index.month == 2).any() else 0
    peak = m[m.index.month.isin([4, 5])].iloc[-2:].mean() if (m.index.month == 4).any() else 0
    season_x = peak / feb if feb else None
    return render(request, "products.html", active="Products", rows=rows, cat=cat, sort=sort,
                  cats=list(CAT_PHOTOS.items()), total=len(prods), season_x=season_x)


@router.get("/products/{sku}")
def product_detail(sku: str, request: Request, db: Session = Depends(get_db), user=Depends(require_user)):
    p = db.scalar(select(Product).where(Product.sku == sku).options(selectinload(Product.bom).selectinload(BomLine.material)))
    if not p:
        raise HTTPException(404, "No such product")
    st = next(s for s in metrics.product_status(db) if s["p"].id == p.id)
    df = metrics.sales_lines_df(db)
    d = df[df["sku"] == sku]
    monthly = d.assign(month=d["date"].dt.to_period("M")).groupby("month")["qty"].sum()
    months = pd.period_range(pd.Period(TODAY, "M") - 12, pd.Period(TODAY, "M") - 1, freq="M")
    monthly = monthly.reindex(months, fill_value=0)
    chart = charts.single_columns([m.strftime("%b") for m in months], monthly.tolist(), scale=1, unit=f"{p.unit} sold per month", digits=0, label="Sold")
    recent = db.scalars(select(SalesOrderLine).join(SalesOrder).where(SalesOrderLine.product_id == p.id)
                        .options(selectinload(SalesOrderLine.order).selectinload(SalesOrder.customer))
                        .order_by(SalesOrder.order_date.desc()).limit(8)).all()
    cost = unit_cost(p)
    return render(request, "product.html", active="Products", p=p, st=st, chart=chart, recent=recent, cost=cost,
                  margin=(p.price - cost) / p.price * 100, year_units=float(monthly.sum()))
