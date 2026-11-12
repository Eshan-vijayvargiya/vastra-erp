"""Demand forecast: a festival-calendar regression, checked against a simple baseline.

Baseline ("last year"): next month will sell what the same month sold last year.
That works until a festival moves. Diwali was on 21 Oct in 2025 but falls on
8 Nov in 2026, so last November is the wrong guide for this November.

Model: for each category, daily sales are explained by
    month of year + Sunday
    + days before Diwali (sarees, dhoti & safi)
    + days before 26 Jan / 15 Aug (flags)
    + wedding season (sarees, dhoti & safi)
fitted with ridge regression (least squares with a small penalty). Older days
are scaled up by the recent year-on-year growth, so the model forecasts at
today's level instead of the average level of the last two years.

Accuracy is measured with WAPE = sum of |forecast - actual| / sum of actual,
on months the model did not see (rolling-origin backtest).
"""
from datetime import date, timedelta

import numpy as np
import pandas as pd

from .metrics import CATEGORIES

DIWALI = [date(2023, 11, 12), date(2024, 11, 1), date(2025, 10, 21), date(2026, 11, 8), date(2027, 10, 29)]
EVENTS = {"Fabric": [], "Uniforms": [], "Sarees": ["diwali", "wedding"], "Flags": ["national"],
          "Dhoti & Safi": ["diwali", "wedding"]}
_cache: dict = {}


def feature_names(cat: str) -> list[str]:
    names = [f"month_{m}" for m in range(1, 13)] + ["sunday"]
    if "diwali" in EVENTS[cat]:
        names += ["diwali_0_7d", "diwali_8_14d", "diwali_15_21d", "diwali_22_35d"]
    if "national" in EVENTS[cat]:
        names += ["natday_0_7d", "natday_8_14d", "natday_15_28d"]
    if "wedding" in EVENTS[cat]:
        names += ["wedding_season"]
    return names


def features(days: pd.DatetimeIndex, cat: str) -> np.ndarray:
    rows = []
    for ts in days:
        d = ts.date()
        row = [float(d.month == m) for m in range(1, 13)] + [float(d.weekday() == 6)]
        if "diwali" in EVENTS[cat]:
            gap = min((dw - d).days for dw in DIWALI if (dw - d).days >= 0)
            row += [gap <= 7, 8 <= gap <= 14, 15 <= gap <= 21, 22 <= gap <= 35]
        if "national" in EVENTS[cat]:
            nd = min((t - d).days for t in (date(d.year, 1, 26), date(d.year, 8, 15), date(d.year + 1, 1, 26))
                     if (t - d).days >= 0)
            row += [nd <= 7, 8 <= nd <= 14, 15 <= nd <= 28]
        if "wedding" in EVENTS[cat]:
            row += [(d.month == 11 and d.day >= 15) or (d.month == 12 and d.day <= 15) or d.month == 2]
        rows.append(row)
    return np.array(rows, dtype=float)


def daily_series(df: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    idx = pd.date_range(start, end, freq="D")
    s = df.pivot_table(index="date", columns="category", values="value", aggfunc="sum", fill_value=0)
    return s.reindex(index=idx, columns=CATEGORIES, fill_value=0)


def yoy_growth(train: pd.DataFrame) -> pd.Series:
    """Last 6 full months vs the same 6 months a year earlier, per category (kept between 0.85 and 1.30)."""
    m = train.resample("MS").sum()
    if len(m) < 18:
        return pd.Series(1.0, index=train.columns)
    last, prev = m.iloc[-7:-1], m.shift(12).iloc[-7:-1]
    return (last.sum() / prev.sum()).clip(0.85, 1.30).fillna(1.0)


def fit_predict(train: pd.DataFrame, future: pd.DatetimeIndex, lam: float = 1.0) -> tuple[pd.DataFrame, dict]:
    g = yoy_growth(train)
    origin = train.index[-1]
    age = np.array([(origin - ts).days / 365 for ts in train.index])
    out = pd.DataFrame(index=future, columns=CATEGORIES, dtype=float)
    coefs = {}
    for cat in CATEGORIES:
        X, Xf = features(train.index, cat), features(future, cat)
        y = train[cat].to_numpy() * g[cat] ** age          # bring old days up to today's level
        beta = np.linalg.solve(X.T @ X + lam * np.eye(X.shape[1]), X.T @ y)
        out[cat] = np.clip(Xf @ beta, 0, None)
        coefs[cat] = dict(zip(feature_names(cat), beta), growth=float(g[cat]))
    return out, coefs


def backtest(daily: pd.DataFrame, cutoffs: list[pd.Timestamp], months: int = 3) -> pd.DataFrame:
    monthly = daily.resample("MS").sum()
    rows = []
    for co in cutoffs:
        train = daily[daily.index <= co]
        test = daily[(daily.index > co) & (daily.index <= co + pd.offsets.MonthEnd(months))]
        pred, _ = fit_predict(train, test.index)
        pm, am = pred.resample("MS").sum(), test.resample("MS").sum()
        for cat in CATEGORIES:
            for m in am.index:
                rows.append(dict(cutoff=co, category=cat, month=m, actual=am.at[m, cat], model=pm.at[m, cat],
                                 naive=monthly[cat].shift(12).get(m, np.nan)))
    return pd.DataFrame(rows).dropna()


def wape(df: pd.DataFrame, col: str) -> float:
    return float((df[col] - df["actual"]).abs().sum() / df["actual"].sum() * 100) if df["actual"].sum() else float("nan")


def run(sales_df: pd.DataFrame, today: date, horizon_months: int = 3) -> dict:
    key = (len(sales_df), round(float(sales_df["value"].sum())), today)
    if key in _cache:
        return _cache[key]
    daily = daily_series(sales_df, sales_df["date"].min().date(), today)
    this_month = pd.Timestamp(today).replace(day=1)

    # 1) backtest: four forecasts made at the end of four past months, each for the next 3 months
    last_full = this_month - pd.Timedelta(days=1)
    cutoffs = [last_full - pd.offsets.MonthEnd(k) for k in (6, 5, 4, 3)]
    bt = backtest(daily, cutoffs)
    acc = {cat: dict(model=wape(g, "model"), naive=wape(g, "naive")) for cat, g in bt.groupby("category")}
    tot = bt.groupby(["cutoff", "month"])[["actual", "model", "naive"]].sum()
    acc["All"] = dict(model=wape(tot, "model"), naive=wape(tot, "naive"))

    # 2) live check on this month so far: model trained to the end of last month vs last year's same days
    mtd_days = daily[(daily.index >= this_month)].index
    pred_mtd, _ = fit_predict(daily[daily.index <= last_full], mtd_days)
    ly = daily.reindex(mtd_days - pd.DateOffset(years=1)).fillna(0)
    mtd = pd.DataFrame({"actual": daily.loc[mtd_days].sum(), "model": pred_mtd.sum(), "last_year": ly.sum()})

    # 3) final forecast: train on everything up to today
    end = this_month + pd.offsets.MonthEnd(horizon_months)
    future = pd.date_range(pd.Timestamp(today) + pd.Timedelta(days=1), end, freq="D")
    fc_daily, coefs = fit_predict(daily, future)
    actual_m = daily.resample("MS").sum()
    fc_m = fc_daily.resample("MS").sum()
    fc_m.loc[this_month] = fc_m.loc[this_month] + actual_m.loc[this_month]   # sold so far + rest of month
    naive_m = pd.DataFrame([actual_m.loc[m - pd.DateOffset(years=1)] if (m - pd.DateOffset(years=1)) in actual_m.index
                            else pd.Series(np.nan, index=CATEGORIES) for m in fc_m.index], index=fc_m.index)
    # spread: typical size of a monthly miss in the backtest, per category
    spread = {cat: float((g["model"] - g["actual"]).abs().mean()) for cat, g in bt.groupby("category")}
    result = dict(actual=actual_m, forecast=fc_m, naive=naive_m, daily_forecast=fc_daily, accuracy=acc,
                  backtest=bt, mtd=mtd, spread=spread, coefs=coefs, this_month=this_month,
                  cutoffs=cutoffs, mtd_days=len(mtd_days))
    _cache.clear()
    _cache[key] = result
    return result


def production_plan(fc: dict, sales_df: pd.DataFrame, statuses: list[dict], today: date, days: int = 30) -> list[dict]:
    """How many of each product to make so the next `days` of forecast demand are covered."""
    recent = sales_df[sales_df["date"] > pd.Timestamp(today - timedelta(days=365))]
    share = recent.groupby(["category", "sku"])["value"].sum()
    share = share / share.groupby(level=0).transform("sum")
    window = fc["daily_forecast"].iloc[:days].sum()
    rows = []
    for st in statuses:
        p = st["p"]
        demand = window[p.category] * share.get((p.category, p.sku), 0.0) / p.price
        need = demand + p.safety_stock + st["booked"] - st["have"] - st["wip"]
        make = int(np.ceil(need / p.batch_size) * p.batch_size) if need > 0 else 0
        rows.append(dict(p=p, demand=demand, have=st["have"], wip=st["wip"], booked=st["booked"], make=make))
    rows.sort(key=lambda r: -r["make"] * r["p"].price)
    return rows
