"""Tables of the ERP, written as SQLAlchemy classes.

Stock is never stored as a number on the product. It is the sum of
StockMove rows (a ledger), so every unit can be traced to a purchase,
a work order or a sale.
"""
from datetime import date

from sqlalchemy import Date, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    email: Mapped[str] = mapped_column(String(120), unique=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(20), default="owner")


class Customer(Base):
    __tablename__ = "customers"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(20))  # School, Retailer, Government, Wholesaler
    city: Mapped[str] = mapped_column(String(60))
    credit_days: Mapped[int] = mapped_column(Integer, default=30)


class Supplier(Base):
    __tablename__ = "suppliers"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    city: Mapped[str] = mapped_column(String(60))
    lead_days: Mapped[int] = mapped_column(Integer, default=7)


class Product(Base):
    __tablename__ = "products"
    id: Mapped[int] = mapped_column(primary_key=True)
    sku: Mapped[str] = mapped_column(String(30), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    category: Mapped[str] = mapped_column(String(30))  # Uniforms, Sarees, Flags, Fabric, Dhoti & Safi
    unit: Mapped[str] = mapped_column(String(10))      # pcs or m
    price: Mapped[float] = mapped_column(Float)
    labour_cost: Mapped[float] = mapped_column(Float, default=0)  # stitching / weaving cost per unit
    safety_stock: Mapped[int] = mapped_column(Integer, default=0)
    batch_size: Mapped[int] = mapped_column(Integer, default=100)
    photo: Mapped[str] = mapped_column(String(60), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    bom: Mapped[list["BomLine"]] = relationship(back_populates="product", cascade="all, delete-orphan")


class Material(Base):
    __tablename__ = "materials"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(30), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    unit: Mapped[str] = mapped_column(String(10))  # m, kg, pcs, cone
    cost: Mapped[float] = mapped_column(Float)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"))
    safety_stock: Mapped[float] = mapped_column(Float, default=0)
    reorder_qty: Mapped[float] = mapped_column(Float, default=0)
    photo: Mapped[str] = mapped_column(String(60), default="")
    supplier: Mapped[Supplier] = relationship()


class BomLine(Base):
    """Bill of materials: how much of each material one unit of a product needs."""
    __tablename__ = "bom_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    material_id: Mapped[int] = mapped_column(ForeignKey("materials.id"))
    qty: Mapped[float] = mapped_column(Float)
    product: Mapped[Product] = relationship(back_populates="bom")
    material: Mapped[Material] = relationship()


class SalesOrder(Base):
    __tablename__ = "sales_orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(20), unique=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"))
    order_date: Mapped[date] = mapped_column(Date)
    due_date: Mapped[date] = mapped_column(Date)
    shipped_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="Open")  # Open, Shipped, Cancelled
    customer: Mapped[Customer] = relationship()
    lines: Mapped[list["SalesOrderLine"]] = relationship(back_populates="order", cascade="all, delete-orphan")

    @property
    def amount(self) -> float:
        return sum(l.qty * l.price for l in self.lines)


class SalesOrderLine(Base):
    __tablename__ = "sales_order_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("sales_orders.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    qty: Mapped[float] = mapped_column(Float)
    price: Mapped[float] = mapped_column(Float)
    order: Mapped[SalesOrder] = relationship(back_populates="lines")
    product: Mapped[Product] = relationship()


class Invoice(Base):
    __tablename__ = "invoices"
    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(20), unique=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("sales_orders.id"))
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"))
    invoice_date: Mapped[date] = mapped_column(Date)
    due_date: Mapped[date] = mapped_column(Date)
    amount: Mapped[float] = mapped_column(Float)
    customer: Mapped[Customer] = relationship()
    order: Mapped[SalesOrder] = relationship()
    payments: Mapped[list["Payment"]] = relationship(back_populates="invoice", cascade="all, delete-orphan")

    @property
    def paid(self) -> float:
        return sum(p.amount for p in self.payments)

    @property
    def balance(self) -> float:
        return round(self.amount - self.paid, 2)


class Payment(Base):
    __tablename__ = "payments"
    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"))
    pay_date: Mapped[date] = mapped_column(Date)
    amount: Mapped[float] = mapped_column(Float)
    mode: Mapped[str] = mapped_column(String(20), default="Bank transfer")
    invoice: Mapped[Invoice] = relationship(back_populates="payments")


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(20), unique=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"))
    order_date: Mapped[date] = mapped_column(Date)
    expected_date: Mapped[date] = mapped_column(Date)
    received_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="Ordered")  # Ordered, Received, Cancelled
    supplier: Mapped[Supplier] = relationship()
    lines: Mapped[list["PurchaseOrderLine"]] = relationship(back_populates="po", cascade="all, delete-orphan")
    payments: Mapped[list["SupplierPayment"]] = relationship(back_populates="po", cascade="all, delete-orphan")

    @property
    def amount(self) -> float:
        return sum(l.qty * l.cost for l in self.lines)


class PurchaseOrderLine(Base):
    __tablename__ = "purchase_order_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    po_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id"))
    material_id: Mapped[int] = mapped_column(ForeignKey("materials.id"))
    qty: Mapped[float] = mapped_column(Float)
    cost: Mapped[float] = mapped_column(Float)
    po: Mapped[PurchaseOrder] = relationship(back_populates="lines")
    material: Mapped[Material] = relationship()


class SupplierPayment(Base):
    __tablename__ = "supplier_payments"
    id: Mapped[int] = mapped_column(primary_key=True)
    po_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id"))
    pay_date: Mapped[date] = mapped_column(Date)
    amount: Mapped[float] = mapped_column(Float)
    po: Mapped[PurchaseOrder] = relationship(back_populates="payments")


STAGES = ["Planned", "Cutting", "Stitching", "Finishing", "Packed"]


class WorkOrder(Base):
    __tablename__ = "work_orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(20), unique=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    qty: Mapped[float] = mapped_column(Float)
    line: Mapped[str] = mapped_column(String(20), default="Line 1")
    start_date: Mapped[date] = mapped_column(Date)
    due_date: Mapped[date] = mapped_column(Date)
    done_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    stage: Mapped[str] = mapped_column(String(20), default="Planned")
    product: Mapped[Product] = relationship()

    @property
    def progress(self) -> int:
        return {"Planned": 0, "Cutting": 15, "Stitching": 50, "Finishing": 85, "Packed": 100}[self.stage]


class StockMove(Base):
    """One row per change in stock. +qty in, -qty out. Exactly one of product_id / material_id is set."""
    __tablename__ = "stock_moves"
    id: Mapped[int] = mapped_column(primary_key=True)
    move_date: Mapped[date] = mapped_column(Date, index=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"), nullable=True, index=True)
    material_id: Mapped[int | None] = mapped_column(ForeignKey("materials.id"), nullable=True, index=True)
    qty: Mapped[float] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(String(20))  # opening, purchase, consumption, production, sale, adjustment
    ref: Mapped[str] = mapped_column(String(30), default="")


class Expense(Base):
    __tablename__ = "expenses"
    id: Mapped[int] = mapped_column(primary_key=True)
    exp_date: Mapped[date] = mapped_column(Date)
    category: Mapped[str] = mapped_column(String(30))  # Wages, Power, Rent, Transport, Other
    amount: Mapped[float] = mapped_column(Float)
    note: Mapped[str] = mapped_column(String(120), default="")
