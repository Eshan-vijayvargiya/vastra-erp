"""End-to-end checks: every page loads, and each business action keeps stock and money consistent.

Run:  pytest -q
"""
import os
import tempfile
from datetime import date

DB = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["DATABASE_URL"] = f"sqlite:///{DB}"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import func, select  # noqa: E402

from app import seed  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Invoice, Material, Product, PurchaseOrder, SalesOrder, StockMove, WorkOrder  # noqa: E402
from app.services import forecast, metrics, ops  # noqa: E402

TODAY = date(2026, 11, 12)
PAGES = ["/", "/products", "/products?cat=Sarees", "/products/U02", "/production", "/stock", "/purchases",
         "/sales", "/sales?q=school", "/accounts", "/forecast", "/export"]


@pytest.fixture(scope="module")
def client():
    seed.build(verbose=False)
    with TestClient(app) as c:
        c.post("/demo")
        yield c


def test_login_required():
    with TestClient(app) as anon:
        r = anon.get("/", follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/login"
        assert anon.get("/login").status_code == 200


def test_wrong_password_is_refused(client):
    with TestClient(app) as anon:
        r = anon.post("/login", data={"email": "owner@vastramills.in", "password": "nope"}, follow_redirects=True)
        assert "match. Try the demo login" in r.text
        r = anon.post("/login", data={"email": "owner@vastramills.in", "password": "vastra-demo"}, follow_redirects=True)
        assert "Today at the mill" in r.text


@pytest.mark.parametrize("path", PAGES)
def test_pages_load(client, path):
    r = client.get(path)
    assert r.status_code == 200, path
    assert "Traceback" not in r.text


def test_stock_never_negative(client):
    db = SessionLocal()
    for q in metrics.product_stock(db).values():
        assert q >= -1e-6
    for q in metrics.material_stock(db).values():
        assert q >= -1e-6


def test_work_order_flow_moves_stock(client):
    db = SessionLocal()
    p = db.scalar(select(Product).where(Product.sku == "F02"))
    before_goods = metrics.product_stock(db).get(p.id, 0)
    before_mat = metrics.material_stock(db)
    wo = ops.create_work_order(db, p.id, 10, TODAY)
    ops.advance_work_order(db, wo.id, TODAY)          # start: materials issued
    after_mat = metrics.material_stock(db)
    for b in p.bom:
        assert after_mat[b.material_id] == pytest.approx(before_mat[b.material_id] - b.qty * 10)
    for _ in range(3):
        ops.advance_work_order(db, wo.id, TODAY)      # cutting -> stitching -> finishing -> packed
    assert db.get(WorkOrder, wo.id).stage == "Packed"
    assert metrics.product_stock(db)[p.id] == pytest.approx(before_goods + 10)


def test_cannot_start_without_material(client):
    db = SessionLocal()
    p = db.scalar(select(Product).where(Product.sku == "S08"))
    wo = ops.create_work_order(db, p.id, 100_000, TODAY)
    with pytest.raises(ops.ActionError):
        ops.advance_work_order(db, wo.id, TODAY)


def test_sell_ship_invoice_pay(client):
    db = SessionLocal()
    p = db.scalar(select(Product).where(Product.sku == "D01"))
    cust_id = db.scalar(select(SalesOrder.customer_id).limit(1))
    have = metrics.product_stock(db)[p.id]
    so = ops.create_sales_order(db, cust_id, [(p.id, 5)], TODAY)
    inv = ops.ship_order(db, so.id, TODAY)
    assert inv.amount == pytest.approx(5 * p.price)
    assert metrics.product_stock(db)[p.id] == pytest.approx(have - 5)
    ops.record_payment(db, inv.id, TODAY)
    assert db.get(Invoice, inv.id).balance == 0


def test_purchase_receive_adds_material(client):
    db = SessionLocal()
    m = db.scalar(select(Material).where(Material.code == "M09"))
    have = metrics.material_stock(db)[m.id]
    po = ops.raise_purchase_orders(db, {m.id: 100}, TODAY)[0]
    ops.receive_po(db, po.id, TODAY)
    assert metrics.material_stock(db)[m.id] == pytest.approx(have + 100)
    assert db.get(PurchaseOrder, po.id).status == "Received"


def test_forecast_shapes_and_backtest(client):
    db = SessionLocal()
    fc = forecast.run(metrics.sales_lines_df(db), TODAY)
    assert list(fc["forecast"].columns) == metrics.CATEGORIES
    assert len(fc["forecast"]) == 3 and (fc["forecast"].values >= 0).all()
    assert 0 < fc["accuracy"]["All"]["model"] < 60
    # Diwali on 8 Nov 2026: the model should beat "last year" on sarees this month
    mtd = fc["mtd"].loc["Sarees"]
    assert abs(mtd["model"] - mtd["actual"]) < abs(mtd["last_year"] - mtd["actual"])


def test_csv_export_with_key():
    with TestClient(app) as anon:
        assert anon.get("/export/sales_lines.csv").status_code == 401
        r = anon.get("/export/sales_lines.csv?key=vastra-demo")
        assert r.status_code == 200 and r.text.startswith("order_number,")
        assert anon.get("/export/forecast.csv?key=vastra-demo").status_code == 200


def test_post_actions_through_pages(client):
    db = SessionLocal()
    wo_id = db.scalar(select(WorkOrder.id).where(WorkOrder.stage == "Cutting").limit(1))
    r = client.post(f"/production/{wo_id}/advance", follow_redirects=True)
    assert r.status_code == 200 and "moved to Stitching" in r.text
    mat = [x for x in metrics.material_status(db, TODAY) if x["status"] == "Reorder"]
    if mat:
        r = client.post("/purchases/raise", data={"material_id": [str(mat[0]["m"].id)]}, follow_redirects=True)
        assert "Raised PO-" in r.text
