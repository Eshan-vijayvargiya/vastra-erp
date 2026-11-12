"""Business actions. Each one writes the documents and the stock ledger together,
so stock, orders and money always agree. Pages call these; tests call them too."""
import math
from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..models import (STAGES, Customer, Invoice, Material, Payment, Product, PurchaseOrder, PurchaseOrderLine,
                      SalesOrder, SalesOrderLine, StockMove, SupplierPayment, WorkOrder)
from .metrics import material_stock, product_stock

LEAD_DAYS = {"Uniforms": 10, "Sarees": 14, "Flags": 6, "Fabric": 7, "Dhoti & Safi": 6}
CREDIT_DAYS = {"School": 45, "Retailer": 30, "Government": 60, "Wholesaler": 30}


class ActionError(Exception):
    """A business rule said no (not enough stock, wrong stage...). The message is shown to the user."""


def _next_number(db: Session, model, prefix: str) -> str:
    last = db.scalar(select(func.max(model.id)))
    nums = [int(n.split("-")[-1]) for n in db.scalars(select(model.number).order_by(model.id.desc()).limit(1))]
    return f"{prefix}-{(nums[0] if nums else (last or 0)) + 1}"


# ------------------------------------------------------------------ production
def create_work_order(db: Session, product_id: int, qty: float, today: date) -> WorkOrder:
    p = db.get(Product, product_id)
    if not p or qty <= 0:
        raise ActionError("Pick a product and a quantity above zero.")
    busy = defaultdict(int)
    for line in db.scalars(select(WorkOrder.line).where(WorkOrder.stage != "Packed")):
        busy[line] += 1
    line = min(["Line 1", "Line 2", "Line 3"], key=lambda l: busy[l])
    wo = WorkOrder(number=_next_number(db, WorkOrder, "WO"), product_id=p.id, qty=qty, line=line, stage="Planned",
                   start_date=today, due_date=today + timedelta(days=LEAD_DAYS[p.category]))
    db.add(wo)
    db.commit()
    return wo


def advance_work_order(db: Session, wo_id: int, today: date) -> WorkOrder:
    """Move a work order one stage on. Starting it uses up materials; packing it adds finished stock."""
    wo = db.scalar(select(WorkOrder).where(WorkOrder.id == wo_id)
                   .options(selectinload(WorkOrder.product).selectinload(Product.bom)))
    if not wo or wo.stage == "Packed":
        raise ActionError("This work order is already packed.")
    nxt = STAGES[STAGES.index(wo.stage) + 1]
    if wo.stage == "Planned":
        stock = material_stock(db)
        short = []
        for b in wo.product.bom:
            need = b.qty * wo.qty
            if stock.get(b.material_id, 0) < need - 1e-9:
                m = db.get(Material, b.material_id)
                short.append(f"{m.name} (need {need:,.1f} {m.unit}, have {stock.get(b.material_id, 0):,.1f})")
        if short:
            raise ActionError("Not enough material to start: " + "; ".join(short) + ". Raise a purchase order first.")
        for b in wo.product.bom:
            db.add(StockMove(move_date=today, material_id=b.material_id, qty=-b.qty * wo.qty, reason="consumption", ref=wo.number))
        wo.start_date = today
        wo.due_date = today + timedelta(days=LEAD_DAYS[wo.product.category])
    if nxt == "Packed":
        db.add(StockMove(move_date=today, product_id=wo.product_id, qty=wo.qty, reason="production", ref=wo.number))
        wo.done_date = today
    wo.stage = nxt
    db.commit()
    return wo


# ------------------------------------------------------------------ sales
def create_sales_order(db: Session, customer_id: int, lines: list[tuple[int, float]], today: date) -> SalesOrder:
    cust = db.get(Customer, customer_id)
    lines = [(pid, q) for pid, q in lines if pid and q and q > 0]
    if not cust or not lines:
        raise ActionError("Pick a customer and at least one product with a quantity.")
    so = SalesOrder(number=_next_number(db, SalesOrder, "SO"), customer_id=cust.id, order_date=today,
                    due_date=today + timedelta(days=14 if cust.kind == "School" else 5), status="Open")
    for pid, q in lines:
        p = db.get(Product, pid)
        so.lines.append(SalesOrderLine(product_id=p.id, qty=q, price=p.price))
    db.add(so)
    db.commit()
    return so


def can_ship(so: SalesOrder, stock: dict[int, float]) -> bool:
    return all(stock.get(l.product_id, 0) >= l.qty for l in so.lines)


def ship_order(db: Session, so_id: int, today: date) -> Invoice:
    so = db.scalar(select(SalesOrder).where(SalesOrder.id == so_id)
                   .options(selectinload(SalesOrder.lines), selectinload(SalesOrder.customer)))
    if not so or so.status != "Open":
        raise ActionError("Only open orders can be shipped.")
    stock = product_stock(db)
    if not can_ship(so, stock):
        raise ActionError(f"{so.number} cannot ship yet: not enough finished stock. Make it in Production first.")
    for l in so.lines:
        db.add(StockMove(move_date=today, product_id=l.product_id, qty=-l.qty, reason="sale", ref=so.number))
    so.status, so.shipped_date = "Shipped", today
    n = db.scalar(select(func.count()).select_from(Invoice)) + 1
    inv = Invoice(number=f"INV-{today.year}-{n:05d}", order_id=so.id, customer_id=so.customer_id, invoice_date=today,
                  due_date=today + timedelta(days=CREDIT_DAYS[so.customer.kind]), amount=round(so.amount, 2))
    db.add(inv)
    db.commit()
    return inv


def record_payment(db: Session, invoice_id: int, today: date, amount: float | None = None, mode: str = "Bank transfer") -> Payment:
    inv = db.scalar(select(Invoice).where(Invoice.id == invoice_id).options(selectinload(Invoice.payments)))
    if not inv or inv.balance <= 0:
        raise ActionError("This invoice is already paid.")
    amt = round(min(amount or inv.balance, inv.balance), 2)
    pay = Payment(pay_date=today, amount=amt, mode=mode)
    inv.payments.append(pay)
    db.commit()
    return pay


# ------------------------------------------------------------------ purchases
def raise_purchase_orders(db: Session, wanted: dict[int, float], today: date) -> list[PurchaseOrder]:
    """wanted = {material_id: qty}. One purchase order per supplier."""
    by_sup = defaultdict(list)
    for mid, qty in wanted.items():
        m = db.scalar(select(Material).where(Material.id == mid).options(selectinload(Material.supplier)))
        if m and qty > 0:
            by_sup[m.supplier_id].append((m, qty))
    if not by_sup:
        raise ActionError("Nothing to order.")
    pos = []
    for sid, items in by_sup.items():
        lead = items[0][0].supplier.lead_days
        po = PurchaseOrder(number=_next_number(db, PurchaseOrder, "PO"), supplier_id=sid, order_date=today,
                           expected_date=today + timedelta(days=lead), status="Ordered")
        for m, qty in items:
            po.lines.append(PurchaseOrderLine(material_id=m.id, qty=qty, cost=m.cost))
        db.add(po)
        db.flush()
        pos.append(po)
    db.commit()
    return pos


def receive_po(db: Session, po_id: int, today: date) -> PurchaseOrder:
    po = db.scalar(select(PurchaseOrder).where(PurchaseOrder.id == po_id).options(selectinload(PurchaseOrder.lines)))
    if not po or po.status != "Ordered":
        raise ActionError("Only open purchase orders can be received.")
    for l in po.lines:
        db.add(StockMove(move_date=today, material_id=l.material_id, qty=l.qty, reason="purchase", ref=po.number))
    po.status, po.received_date = "Received", today
    db.commit()
    return po


def pay_supplier(db: Session, po_id: int, today: date) -> SupplierPayment:
    po = db.scalar(select(PurchaseOrder).where(PurchaseOrder.id == po_id)
                   .options(selectinload(PurchaseOrder.lines), selectinload(PurchaseOrder.payments)))
    bal = po.amount - sum(p.amount for p in po.payments) if po else 0
    if not po or po.status != "Received" or bal <= 1:
        raise ActionError("Nothing to pay on this purchase order.")
    sp = SupplierPayment(pay_date=today, amount=round(bal, 2))
    po.payments.append(sp)
    db.commit()
    return sp
