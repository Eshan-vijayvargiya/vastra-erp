from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from ..db import get_db
from ..services import forecast, metrics
from ..services.metrics import CATEGORIES
from ..web import TODAY, render, require_user
from .dashboard import sales_chart

router = APIRouter()


@router.get("/forecast")
def forecast_page(request: Request, db: Session = Depends(get_db), user=Depends(require_user)):
    df = metrics.sales_lines_df(db)
    fc = forecast.run(df, TODAY)
    chart, frame = sales_chart(fc, back=12, ahead=2)
    months = list(fc["forecast"].index)
    table = []
    for cat in CATEGORIES + ["All"]:
        f = fc["forecast"][CATEGORIES].sum(axis=1) if cat == "All" else fc["forecast"][cat]
        n = fc["naive"][CATEGORIES].sum(axis=1, min_count=1) if cat == "All" else fc["naive"][cat]
        table.append(dict(cat=cat, fc=[f[m] for m in months], ly=[n[m] for m in months],
                          spread=sum(fc["spread"].values()) if cat == "All" else fc["spread"][cat],
                          acc=fc["accuracy"][cat]))
    mtd = fc["mtd"]
    sarees = mtd.loc["Sarees"]
    plan = forecast.production_plan(fc, df, metrics.product_status(db), TODAY)
    make = [r for r in plan if r["make"] > 0]
    coefs = fc["coefs"]
    drivers = dict(
        diwali=coefs["Sarees"]["diwali_0_7d"], diwali2=coefs["Sarees"]["diwali_8_14d"],
        natday=coefs["Flags"]["natday_0_7d"], sunday=coefs["Fabric"]["sunday"],
        school=(coefs["Uniforms"]["month_5"] - coefs["Uniforms"]["month_9"]) * 31,
    )
    dw_this = min((d for d in forecast.DIWALI if d.year == TODAY.year), default=None)
    dw_last = min((d for d in forecast.DIWALI if d.year == TODAY.year - 1), default=None)
    return render(request, "forecast.html", dw_this=dw_this, dw_last=dw_last, active="Forecast", chart=chart, months=months, table=table, fc=fc,
                  mtd=mtd, sarees=sarees, make=make, drivers=drivers, cutoffs=fc["cutoffs"])
