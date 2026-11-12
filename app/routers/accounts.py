import pandas as pd
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from ..db import get_db
from ..services import charts, metrics
from ..web import TODAY, render, require_user

router = APIRouter()


@router.get("/accounts")
def accounts(request: Request, db: Session = Depends(get_db), user=Depends(require_user)):
    pl = metrics.profit_and_loss(db)
    this = pd.Period(TODAY, "M")
    closed = pl[pl.index < this].iloc[-12:]           # last 12 closed months
    year = closed.sum()
    margin = year["Gross profit"] / year["Sales"] * 100 if year["Sales"] else 0
    net_margin = year["Net profit"] / year["Sales"] * 100 if year["Sales"] else 0
    chart = charts.single_columns([m.strftime("%b") for m in closed.index], closed["Net profit"].tolist())
    rec = metrics.receivables(db, TODAY)
    pay = metrics.payables(db, TODAY)
    rows = ["Sales", "Materials", "Labour", "Gross profit", "Overheads", "Net profit"]
    table = [(r, [closed.at[m, r] for m in closed.index], year[r]) for r in rows]
    return render(request, "accounts.html", active="Accounts", year=year, margin=margin, net_margin=net_margin,
                  chart=chart, rec=rec, pay=pay, months=[m.strftime("%b %y") for m in closed.index], table=table,
                  first=closed.index[0], last=closed.index[-1])
