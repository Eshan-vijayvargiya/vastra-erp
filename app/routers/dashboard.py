from datetime import date

import pandas as pd
from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..db import get_db
from ..models import SalesOrder, WorkOrder
from ..services import charts, forecast, metrics
from ..services.forecast import DIWALI
from ..web import TODAY, render, require_user

router = APIRouter()


def season_notes(months: list[pd.Timestamp]) -> list[tuple[int, int, str]]:
    """Labels drawn above the chart: school season, 26 Jan, 15 Aug, Diwali."""
    notes = []
    idx = {(m.year, m.month): i for i, m in enumerate(months)}
    school = [i for i, m in enumerate(months) if m.month in (3, 4, 5, 6)]
    if school:
        run = [school[0]]
        for i in school[1:]:
            if i == run[-1] + 1:
                run.append(i)
            else:
                break
        notes.append((run[0], run[-1], "School reopening"))
    for i, m in enumerate(months):
        if m.month == 1:
            notes.append((i, i, "26 Jan"))
        if m.month == 8:
            notes.append((i, i, "15 Aug"))
    for dw in DIWALI:
        if (dw.year, dw.month) in idx:
            notes.append((idx[(dw.year, dw.month)], idx[(dw.year, dw.month)], "Diwali"))
    return notes


def sales_chart(fc: dict, back: int = 12, ahead: int = 2):
    this = fc["this_month"]
    act = fc["actual"]
    past = act[act.index < this].iloc[-back:]
    fut = fc["forecast"].iloc[: ahead + 1]
    frame = pd.concat([past, fut])
    labels = [f"{m:%b}" + (f" {m:%y}" if m.month == 1 or i == 0 else "") for i, m in enumerate(frame.index)]
    series = {c: frame[c].tolist() for c in metrics.CATEGORIES}
    peak = int(pd.Series(frame.sum(axis=1).to_numpy()[:back]).idxmax())
    html = charts.stacked_columns(labels, series, forecast_from=len(past), notes=season_notes(list(frame.index)),
                                  show_totals={peak, len(past)})
    return html, frame


@router.get("/")
def dashboard(request: Request, db: Session = Depends(get_db), user=Depends(require_user)):
    df = metrics.sales_lines_df(db)
    fc = forecast.run(df, TODAY)
    this = fc["this_month"]
    k = metrics.kpis(db, TODAY, float(fc["forecast"].loc[this].sum()))
    mats = [r for r in metrics.material_status(db, TODAY) if r["status"] == "Reorder"]
    mats.sort(key=lambda r: (r["cover"] if r["cover"] is not None else 999))
    wos = db.scalars(select(WorkOrder).where(WorkOrder.stage != "Packed").options(selectinload(WorkOrder.product))
                     .order_by(WorkOrder.due_date)).all()
    orders = db.scalars(select(SalesOrder).where(SalesOrder.status == "Open")
                        .options(selectinload(SalesOrder.customer), selectinload(SalesOrder.lines))
                        .order_by(SalesOrder.order_date.desc()).limit(5)).all()
    chart, frame = sales_chart(fc)

    # the three photo cards: production, the category having its big month, the most urgent material
    month_fc = fc["forecast"].loc[this]
    ratio = month_fc / fc["actual"].iloc[:-1].mean()
    hot = ratio.idxmax()
    ly = fc["naive"].loc[this, hot]
    change = (month_fc[hot] / ly - 1) * 100 if ly and ly > 0 else None
    photos = {"Sarees": "saree-red.jpg", "Uniforms": "school-shirt.jpg", "Flags": "flag-tricolour.jpg",
              "Fabric": "fabric-rolls.jpg", "Dhoti & Safi": "white-textile.jpg"}
    running = [w for w in wos if w.stage != "Planned"]
    stories = [
        dict(img="loom-workers.jpg", eb="On the floor", color="var(--link)", href="/production",
             text=f"{len(running)} work orders running, {k['made_week']:,.0f} units finished this week."),
        dict(img=photos[hot], eb="Season", color="var(--warn)", href=f"/products?cat={hot}",
             text=f"{hot}: {metrics.lakh(month_fc[hot])} forecast for {this:%B}" + (f", {change:+.0f}% on last year." if change is not None else ".")),
    ]
    if mats:
        m = mats[0]
        cover = f" About {m['cover']:.0f} days left." if m["cover"] else ""
        stories.append(dict(img=m["m"].photo or "spools-rack.jpg", eb="Reorder", color="var(--warn)", href="/purchases",
                            text=f"{m['m'].name} is down to {m['have']:,.0f} {m['m'].unit}.{cover}"))
    else:
        stories.append(dict(img="spools-rack.jpg", eb="Stock", color="var(--ok)", href="/stock", text="All materials are above their reorder points."))
    return render(request, "dashboard.html", active="Overview", k=k, stories=stories, chart=chart, mats=mats[:5],
                  n_reorder=len(mats), wos=wos[:4], n_wos=len(wos), orders=orders, this=this)
