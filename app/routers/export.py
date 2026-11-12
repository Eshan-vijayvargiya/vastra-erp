"""CSV exports for Power BI.

In Power BI: Get data > Web > paste  https://<your-app>/export/sales_lines.csv?key=<EXPORT_KEY>
Each file is one SQL view from sql/views.sql (plus the forecast, which is made in Python).
"""
import io
import os

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..db import ROOT, engine, get_db
from ..services import forecast, metrics
from ..web import TODAY, render

router = APIRouter()
EXPORT_KEY = os.getenv("EXPORT_KEY", "vastra-demo")
VIEWS = {"sales_lines": "Order lines with customer and product", "invoices": "Invoices with paid and balance",
         "payments": "Customer payments", "stock_moves": "Stock ledger: every unit in and out",
         "work_orders": "Work orders by stage", "purchase_lines": "Purchase order lines",
         "products": "Products with unit cost", "expenses": "Overheads by month"}


def create_views() -> None:
    sql = (ROOT / "sql" / "views.sql").read_text(encoding="utf-8")
    sql = "\n".join(l for l in sql.splitlines() if not l.strip().startswith("--"))   # drop comments first
    with engine.begin() as conn:
        for statement in sql.split(";"):
            if statement.strip():
                conn.execute(text(statement))


def _allowed(request: Request, key: str | None) -> bool:
    return bool(request.session.get("user")) or key == EXPORT_KEY


@router.get("/export")
def export_page(request: Request):
    if not request.session.get("user"):
        raise HTTPException(401, "Sign in first")
    return render(request, "export.html", active="Accounts", views=VIEWS, key=EXPORT_KEY)


@router.get("/export/{name}.csv")
def export_csv(name: str, request: Request, key: str | None = None, db: Session = Depends(get_db)):
    if not _allowed(request, key):
        raise HTTPException(401, "Add ?key=... or sign in")
    if name == "forecast":
        fc = forecast.run(metrics.sales_lines_df(db), TODAY)
        rows = [(m.date(), cat, round(float(v), 2), kind)
                for kind, frame in (("Actual", fc["actual"].iloc[:-1]), ("Forecast", fc["forecast"]))
                for m, r in frame.iterrows() for cat, v in r.items()]
        df = pd.DataFrame(rows, columns=["month", "category", "value", "kind"])
    elif name in VIEWS:
        df = pd.read_sql(text(f"SELECT * FROM v_{name}"), db.bind)
    else:
        raise HTTPException(404, "Unknown export")
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="vastra_{name}.csv"'})
