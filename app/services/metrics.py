"""Numbers the pages show: stock on hand, reorder points, KPIs, money owed.

Everything is computed from the transaction tables, so the pages always
agree with the ledger.
"""
import math
from collections import defaultdict
from datetime import date, timedelta

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..models import (Expense, Invoice, Material, Payment, Product, PurchaseOrder, PurchaseOrderLine,
                      SalesOrder, SalesOrderLine, StockMove, WorkOrder)

ORDER_COST = 600        # Rs spent per purchase order (calls, transport, checking)
HOLDING_RATE = 0.20     # yearly cost of holding stock, as a share of its value
CATEGORIES = ["Fabric", "Uniforms", "Sarees", "Flags", "Dhoti & Safi"]


def lakh(x: float, digits: int = 1) -> str:
    return f"₹{x / 1e5:,.{digits}f} L"


def rupees(x: float) -> str:
    """Indian digit grouping: 1,84,200."""
    neg = x < 0
    s = f"{abs(round(x)):d}"
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts) + "," + tail
    return ("-₹" if neg else "₹") + s


def unit_cost(p: Product) -> float:
    """Materials from the bill of materials plus labour, for one unit."""
    return sum(b.qty * b.material.cost for b in p.bom) + p.labour_cost


def product_stock(db: Session) -> dict[int, float]:
    rows = db.execute(select(StockMove.product_id, func.sum(StockMove.qty))
                      .where(StockMove.product_id.is_not(None)).group_by(StockMove.product_id))
    return {pid: q for pid, q in rows}


def material_stock(db: Session) -> dict[int, float]:
    rows = db.execute(select(StockMove.material_id, func.sum(StockMove.qty))
                      .where(StockMove.material_id.is_not(None)).group_by(StockMove.material_id))
    return {mid: q for mid, q in rows}


def material_status(db: Session, today: date) -> list[dict]:
    """Reorder point = daily use x supplier lead time + safety stock.
    Order quantity = EOQ, sqrt(2 x yearly use x order cost / holding cost per unit)."""
    stock = material_stock(db)
    since = today - timedelta(days=60)
    use = dict(db.execute(select(StockMove.material_id, -func.sum(StockMove.qty))
                          .where(StockMove.reason == "consumption", StockMove.move_date > since)
                          .group_by(StockMove.material_id)).all())
    on_order = defaultdict(float)
    for po in db.scalars(select(PurchaseOrder).where(PurchaseOrder.status == "Ordered")
                         .options(selectinload(PurchaseOrder.lines))):
        for l in po.lines:
            on_order[l.material_id] += l.qty
    planned = defaultdict(float)
    for wo in db.scalars(select(WorkOrder).where(WorkOrder.stage == "Planned")
                         .options(selectinload(WorkOrder.product).selectinload(Product.bom))):
        for b in wo.product.bom:
            planned[b.material_id] += b.qty * wo.qty
    out = []
    for m in db.scalars(select(Material).options(selectinload(Material.supplier)).order_by(Material.code)):
        rate = (use.get(m.id) or 0) / 60
        lead = m.supplier.lead_days
        rop = rate * lead + m.safety_stock
        have = stock.get(m.id, 0)
        position = have + on_order[m.id] - planned[m.id]
        yearly = rate * 365
        eoq = math.sqrt(2 * yearly * ORDER_COST / (HOLDING_RATE * m.cost)) if yearly > 0 else 0
        qty = max(eoq, rop - position + rate * 14)
        qty = math.ceil(qty / 10) * 10 if m.unit in ("pcs", "m") else round(qty + 0.05, 1)
        status = "Reorder" if position < rop else ("Low" if have < m.safety_stock else "OK")
        out.append(dict(m=m, have=have, on_order=on_order[m.id], planned=planned[m.id], rate=rate, lead=lead,
                        rop=rop, position=position, eoq=eoq, suggest=qty if status == "Reorder" else 0,
                        cover=(have / rate) if rate > 0 else None, status=status))
    return out


def product_status(db: Session) -> list[dict]:
    stock = product_stock(db)
    wip = defaultdict(float)
    for wo in db.scalars(select(WorkOrder).where(WorkOrder.stage != "Packed")):
        wip[wo.product_id] += wo.qty
    booked = defaultdict(float)
    for l in db.scalars(select(SalesOrderLine).join(SalesOrder).where(SalesOrder.status == "Open")):
        booked[l.product_id] += l.qty
    out = []
    for p in db.scalars(select(Product).order_by(Product.sku)):
        have = stock.get(p.id, 0)
        free = have - booked[p.id]
        status = "Short" if free < 0 else ("Low" if free < p.safety_stock else "OK")
        out.append(dict(p=p, have=have, wip=wip[p.id], booked=booked[p.id], free=free, status=status))
    return out


def sales_lines_df(db: Session) -> pd.DataFrame:
    """One row per order line with date, category and value (booked sales)."""
    q = (select(SalesOrder.order_date, SalesOrder.status, Product.category, Product.sku, SalesOrderLine.qty,
                (SalesOrderLine.qty * SalesOrderLine.price).label("value"))
         .join(SalesOrderLine, SalesOrderLine.order_id == SalesOrder.id)
         .join(Product, Product.id == SalesOrderLine.product_id)
         .where(SalesOrder.status != "Cancelled"))
    df = pd.DataFrame(db.execute(q).all(), columns=["date", "status", "category", "sku", "qty", "value"])
    df["date"] = pd.to_datetime(df["date"])
    return df


def monthly_by_category(df: pd.DataFrame) -> pd.DataFrame:
    m = df.assign(month=df["date"].dt.to_period("M")).pivot_table(
        index="month", columns="category", values="value", aggfunc="sum", fill_value=0)
    return m.reindex(columns=CATEGORIES, fill_value=0)


def receivables(db: Session, today: date) -> dict:
    invs = db.scalars(select(Invoice).options(selectinload(Invoice.payments), selectinload(Invoice.customer))).all()
    buckets = {"Not due": 0.0, "1–30 days late": 0.0, "31–60 days late": 0.0, "Over 60 days late": 0.0}
    open_invs = []
    for inv in invs:
        bal = inv.balance
        if bal <= 1:
            continue
        late = (today - inv.due_date).days
        key = "Not due" if late <= 0 else "1–30 days late" if late <= 30 else "31–60 days late" if late <= 60 else "Over 60 days late"
        buckets[key] += bal
        open_invs.append((inv, bal, late))
    open_invs.sort(key=lambda t: -t[2])
    total = sum(buckets.values())
    overdue = total - buckets["Not due"]
    late_customers = len({inv.customer_id for inv, bal, late in open_invs if late > 0})
    return dict(buckets=buckets, total=total, overdue=overdue, open=open_invs, late_customers=late_customers)


def payables(db: Session, today: date) -> dict:
    pos = db.scalars(select(PurchaseOrder).where(PurchaseOrder.status == "Received")
                     .options(selectinload(PurchaseOrder.lines), selectinload(PurchaseOrder.payments),
                              selectinload(PurchaseOrder.supplier))).all()
    rows = []
    for po in pos:
        bal = po.amount - sum(p.amount for p in po.payments)
        if bal > 1:
            rows.append((po, bal, (today - po.received_date).days))
    rows.sort(key=lambda t: -t[2])
    return dict(rows=rows, total=sum(r[1] for r in rows))


def profit_and_loss(db: Session) -> pd.DataFrame:
    """Monthly P&L: sales (invoiced) minus material and labour cost of goods made, minus expenses."""
    inv = pd.DataFrame(db.execute(select(Invoice.invoice_date, Invoice.amount)).all(), columns=["d", "amount"])
    cons = pd.DataFrame(db.execute(select(StockMove.move_date, StockMove.qty, Material.cost)
                                   .join(Material, Material.id == StockMove.material_id)
                                   .where(StockMove.reason == "consumption")).all(), columns=["d", "qty", "cost"])
    lab = pd.DataFrame(db.execute(select(StockMove.move_date, StockMove.qty, Product.labour_cost)
                                  .join(Product, Product.id == StockMove.product_id)
                                  .where(StockMove.reason == "production")).all(), columns=["d", "qty", "cost"])
    exp = pd.DataFrame(db.execute(select(Expense.exp_date, Expense.category, Expense.amount)).all(), columns=["d", "cat", "amount"])
    per = lambda s: pd.to_datetime(s).dt.to_period("M")
    pl = pd.DataFrame({
        "Sales": inv.groupby(per(inv.d))["amount"].sum(),
        "Materials": (-cons.qty * cons.cost).groupby(per(cons.d)).sum(),
        "Labour": (lab.qty * lab.cost).groupby(per(lab.d)).sum(),
        "Overheads": exp.groupby(per(exp.d))["amount"].sum(),
    }).fillna(0)
    pl["Gross profit"] = pl["Sales"] - pl["Materials"] - pl["Labour"]
    pl["Net profit"] = pl["Gross profit"] - pl["Overheads"]
    return pl.sort_index()


def kpis(db: Session, today: date, forecast_month: float | None = None) -> dict:
    m0 = today.replace(day=1)
    booked = db.execute(select(func.sum(SalesOrderLine.qty * SalesOrderLine.price)).join(SalesOrder)
                        .where(SalesOrder.order_date >= m0, SalesOrder.order_date <= today,
                               SalesOrder.status != "Cancelled")).scalar() or 0
    open_orders = db.scalars(select(SalesOrder).where(SalesOrder.status == "Open")
                             .options(selectinload(SalesOrder.lines))).all()
    due_week = sum(1 for o in open_orders if o.due_date <= today + timedelta(days=7))
    wos = db.scalars(select(WorkOrder).where(WorkOrder.stage.not_in(["Packed", "Planned"]))).all()
    made = db.execute(select(func.sum(StockMove.qty)).where(StockMove.reason == "production",
                                                            StockMove.move_date > today - timedelta(days=7))).scalar() or 0
    rec = receivables(db, today)
    return dict(
        booked=booked, forecast_month=forecast_month,
        booked_pct=min(100, round(100 * booked / forecast_month)) if forecast_month else None,
        open_count=len(open_orders), open_value=sum(o.amount for o in open_orders), due_week=due_week,
        wo_running=len(wos), wo_lines=len({w.line for w in wos}), made_week=made,
        receivable=rec["total"], overdue=rec["overdue"], late_customers=rec["late_customers"],
    )
