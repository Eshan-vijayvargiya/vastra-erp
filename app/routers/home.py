"""Home: the landing page after sign-in. A big photo, live numbers, a card per module,
what the calendar brings next, and the product categories."""
from datetime import date, timedelta

import pandas as pd
from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Customer, Product, SalesOrder
from ..services import forecast, metrics
from ..web import TODAY, render, require_user

router = APIRouter()
CAT_INFO = {  # photo, one line about the category
    "Uniforms": ("school-shirt.jpg", "Shirts, trousers, tunics and skirts for schools across Rajasthan and MP."),
    "Sarees": ("saree-red.jpg", "Banarasi-style silk to daily-wear cotton. Busiest in the five weeks before Diwali."),
    "Flags": ("flag-sky.jpg", "National flags from table size to 6 × 9 ft, plus saffron flags."),
    "Fabric": ("fabric-rolls-pattern.jpg", "Shirting, poplin, suiting, cambric and latha, sold by the metre."),
    "Dhoti & Safi": ("white-textile.jpg", "Cotton dhotis, dhoti-kurta sets and safi in white and saffron."),
}


def upcoming_events(fc: dict, monthly: pd.DataFrame, today: date) -> list[dict]:
    """The next few calendar moments that move demand, with the numbers behind them."""
    fcm = fc["forecast"]
    def fc_value(y, m, cat):
        ts = pd.Timestamp(y, m, 1)
        return float(fcm.at[ts, cat]) if ts in fcm.index else None
    def last_year(m_list, cat):
        rows = monthly[(monthly.index.month.isin(m_list))]
        return float(rows[cat].iloc[-len(m_list):].sum()) if len(rows) else None
    y = today.year
    events = [
        dict(when=date(y, 11, 15), label="15 Nov – 15 Dec", title="Wedding season", cat="Sarees", color="#1baf7a",
             text=f"Silk and wedding sarees pick up. Saree orders forecast for December: {metrics.lakh(fc_value(y, 12, 'Sarees') or 0)}."),
        dict(when=date(y + 1, 1, 26), label="26 January", title="Republic Day", cat="Flags", color="#eda100",
             text=f"Offices and schools order flags in the four weeks before. January flag forecast: {metrics.lakh(fc_value(y + 1, 1, 'Flags') or 0)}."),
        dict(when=date(y + 1, 3, 1), label="March – June", title="Schools reopen", cat="Uniforms", color="#eb6834",
             text=f"The year's biggest rush. Last year April and May uniform orders came to {metrics.lakh(last_year([4, 5], 'Uniforms') or 0)}."),
        dict(when=date(y + 1, 8, 15), label="15 August", title="Independence Day", cat="Flags", color="#2a78d6",
             text=f"The second flag peak. Last August: {metrics.lakh(last_year([8], 'Flags') or 0)} of flag orders."),
    ]
    return [e for e in events if e["when"] >= today - timedelta(days=30)][:4]


@router.get("/home")
def home(request: Request, db: Session = Depends(get_db), user=Depends(require_user)):
    df = metrics.sales_lines_df(db)
    fc = forecast.run(df, TODAY)
    this = fc["this_month"]
    k = metrics.kpis(db, TODAY, float(fc["forecast"].loc[this].sum()))
    mats = metrics.material_status(db, TODAY)
    n_reorder = sum(r["status"] == "Reorder" for r in mats)
    stock_value = sum(max(r["have"], 0) * r["m"].cost for r in mats)
    monthly = metrics.monthly_by_category(df)
    monthly.index = monthly.index.to_timestamp()
    year = df[df["date"] > pd.Timestamp(TODAY - timedelta(days=365))]
    by_cat = year.groupby("category")["value"].sum()
    counts = dict(db.execute(select(Product.category, func.count()).group_by(Product.category)).all())
    cats = [dict(name=c, img=CAT_INFO[c][0], text=CAT_INFO[c][1], sales=float(by_cat.get(c, 0)), n=counts.get(c, 0))
            for c in metrics.CATEGORIES]
    cats.sort(key=lambda c: -c["sales"])
    modules = [
        ("Overview", "/", "loom-workers.jpg", "Today at the mill", f"{k['open_count']} open orders, {k['wo_running']} work orders running"),
        ("Products", "/products", "fabric-rolls.jpg", f"{sum(counts.values())} products", "Photos, stock, margins and bills of materials"),
        ("Production", "/production", "sewing-hands.jpg", f"{k['wo_running']} on the floor", f"{k['made_week']:,.0f} units finished this week"),
        ("Stock", "/stock", "fabric-shelves.jpg", f"{metrics.lakh(stock_value)} of material", "Every unit traced through the stock ledger"),
        ("Purchases", "/purchases", "thread-lot.jpg", f"{n_reorder} to reorder", "Reorder points, EOQ and supplier on-time scores"),
        ("Sales", "/sales", "shirts-colour-rack.jpg", f"{metrics.lakh(k['open_value'])} to ship", f"{k['due_week']} orders due within a week"),
        ("Accounts", "/accounts", "cotton.jpg", f"{metrics.lakh(k['receivable'])} to collect", f"{metrics.lakh(k['overdue'])} of it overdue"),
        ("Forecast", "/forecast", "spools-dark.jpg", f"{metrics.lakh(k['forecast_month'])} in {this:%B}", "Festival-aware forecast and production plan"),
    ]
    totals = dict(
        orders=db.scalar(select(func.count()).select_from(SalesOrder)),
        sales=float(df["value"].sum()),
        customers=db.scalar(select(func.count()).select_from(Customer)),
        products=sum(counts.values()),
    )
    return render(request, "home.html", active="Home", k=k, this=this, tiles=modules, cats=cats,
                  events=upcoming_events(fc, monthly, TODAY), totals=totals,
                  headline=["Vastra", "Mills."], subline=["From", "yarn", "to", "invoice."])
