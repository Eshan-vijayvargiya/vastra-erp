"""Builds the demo company: master data plus two years of day-by-day history.

Run:  python -m app.seed            (writes data/vastra.db)

How the history is made (a small simulation, not random rows):
  1. Demand: each category has a monthly sales level in Rs lakh, a seasonal
     shape (uniforms peak when schools reopen, flags before 26 Jan and 15 Aug,
     sarees before Diwali and in the wedding season) and ~8% yearly growth.
  2. Every day, customer orders arrive (Poisson count, log-normal size).
  3. Orders ship only when finished stock exists. Shipping creates an invoice;
     customers pay after their credit period plus their own habit of delay.
  4. A planner checks stock every day. If stock plus work in progress will not
     cover the next few weeks of demand, it raises a work order. A work order
     uses up materials from its bill of materials and adds finished stock when done.
  5. A buyer checks materials every day. Below the reorder point, it raises a
     purchase order; the supplier delivers after its lead time (sometimes late).
Every stock change is written to the stock_moves ledger.
"""
import calendar
import functools
import hashlib
import math
import os
from collections import defaultdict, deque
from datetime import date, timedelta

import numpy as np
from sqlalchemy import insert

from .db import Base, SessionLocal, engine
from .models import (BomLine, Customer, Expense, Invoice, Material, Payment, Product, PurchaseOrder,
                     PurchaseOrderLine, SalesOrder, SalesOrderLine, StockMove, Supplier, SupplierPayment,
                     User, WorkOrder)

START = date(2024, 11, 1)
TODAY = date(2026, 11, 12)
SEED = 42

# ----------------------------------------------------------------------------- master data
SUPPLIERS = [  # name, city, lead days
    ("Surat Fab Supply", "Surat", 6), ("Rajasthan Yarn Co.", "Bhilwara", 5), ("Trims & Co.", "Delhi", 4),
    ("Dyechem Traders", "Ahmedabad", 5), ("Kota Packaging", "Kota", 3), ("Varanasi Silk House", "Varanasi", 10),
    ("Erode Cotton Mills", "Erode", 8), ("Panipat Weaves", "Panipat", 7),
]
MATERIALS = [  # code, name, unit, cost, supplier index, photo
    ("M01", "Poplin, white, 58 in", "m", 62, 0, "white-textile.jpg"),
    ("M02", "Poplin, sky blue, 58 in", "m", 64, 0, "blue-shirts.jpg"),
    ("M03", "Terry-wool suiting, navy", "m", 140, 7, "navy-fabric.jpg"),
    ("M04", "Terry-wool suiting, grey", "m", 135, 7, ""),
    ("M05", "Silk-blend Banarasi base", "m", 260, 5, "saree-embroidered.jpg"),
    ("M06", "Cotton saree base", "m", 78, 6, "fabric-rolls-pattern.jpg"),
    ("M07", "Polyester satin", "m", 48, 0, "fabric-rolls-pattern.jpg"),
    ("M08", "Khadi cotton for flags", "m", 70, 6, "white-textile.jpg"),
    ("M09", "Cotton yarn 40s", "kg", 290, 1, "spools-rack.jpg"),
    ("M10", "Zari thread", "cone", 420, 5, "thread-lot.jpg"),
    ("M11", "Sewing thread", "cone", 55, 2, "spools-dark.jpg"),
    ("M12", "Buttons 15 mm", "pcs", 0.45, 2, ""),
    ("M13", "Collar interlining", "m", 40, 2, ""),
    ("M14", "Size labels", "pcs", 0.8, 2, ""),
    ("M15", "Reactive dye, navy", "kg", 520, 3, "navy-fabric.jpg"),
    ("M16", "Reactive dye, saffron", "kg", 480, 3, ""),
    ("M17", "Screen-print ink", "kg", 650, 3, ""),
    ("M18", "Poly bags", "pcs", 1.2, 4, ""),
    ("M19", "Zip, 7 in", "pcs", 4, 2, ""),
    ("M20", "Elastic, 1 in", "m", 6, 2, ""),
    ("M21", "Grey cotton cloth (greige)", "m", 38, 6, "white-textile.jpg"),
]
SHIRT = {"M11": 0.10, "M12": 7, "M13": 0.06, "M14": 1, "M18": 1}
TROUSER = {"M11": 0.10, "M12": 2, "M19": 1, "M14": 1, "M18": 1}
# sku, name, category, unit, price, labour, weight in category, photo, bom {code: qty per unit}
PRODUCTS = [
    ("U01", "School shirt, white (22–28)", "Uniforms", "pcs", 245, 32, .18, "school-shirt.jpg", {"M01": 1.1, **SHIRT}),
    ("U02", "School shirt, white (30–34)", "Uniforms", "pcs", 285, 36, .16, "school-shirt.jpg", {"M01": 1.4, **SHIRT}),
    ("U03", "School shirt, white (36–40)", "Uniforms", "pcs", 320, 40, .10, "school-shirt.jpg", {"M01": 1.7, **SHIRT}),
    ("U04", "House shirt, sky blue (22–28)", "Uniforms", "pcs", 255, 32, .06, "blue-shirts.jpg", {"M02": 1.1, **SHIRT}),
    ("U05", "House shirt, sky blue (30–40)", "Uniforms", "pcs", 295, 38, .06, "blue-shirts.jpg", {"M02": 1.5, **SHIRT}),
    ("U06", "School trousers, navy (22–28)", "Uniforms", "pcs", 360, 45, .10, "navy-fabric.jpg", {"M03": 0.9, **TROUSER}),
    ("U07", "School trousers, navy (30–36)", "Uniforms", "pcs", 420, 50, .09, "navy-fabric.jpg", {"M03": 1.2, **TROUSER}),
    ("U08", "Girls' tunic, navy (22–30)", "Uniforms", "pcs", 390, 52, .07, "navy-fabric.jpg", {"M03": 1.3, "M11": 0.1, "M12": 3, "M14": 1, "M18": 1}),
    ("U09", "Girls' skirt, grey (22–30)", "Uniforms", "pcs", 340, 40, .06, "", {"M04": 1.0, "M20": 0.7, "M11": 0.08, "M14": 1, "M18": 1}),
    ("U10", "Trousers, grey (30–36)", "Uniforms", "pcs", 410, 48, .06, "", {"M04": 1.2, **TROUSER}),
    ("S01", "Banarasi-style silk saree, red", "Sarees", "pcs", 2450, 420, .10, "saree-red.jpg", {"M05": 6.3, "M10": 0.5, "M18": 1}),
    ("S02", "Banarasi-style silk saree, green", "Sarees", "pcs", 2450, 420, .07, "saree-red.jpg", {"M05": 6.3, "M10": 0.5, "M18": 1}),
    ("S03", "Banarasi-style silk saree, maroon", "Sarees", "pcs", 2650, 450, .06, "saree-red.jpg", {"M05": 6.3, "M10": 0.6, "M18": 1}),
    ("S04", "Embroidered cotton saree", "Sarees", "pcs", 890, 160, .14, "saree-embroidered.jpg", {"M06": 5.5, "M11": 0.3, "M18": 1}),
    ("S05", "Printed cotton saree, indigo", "Sarees", "pcs", 640, 70, .18, "saree-embroidered.jpg", {"M06": 5.5, "M17": 0.05, "M18": 1}),
    ("S06", "Printed cotton saree, mustard", "Sarees", "pcs", 640, 70, .14, "saree-embroidered.jpg", {"M06": 5.5, "M17": 0.05, "M18": 1}),
    ("S07", "Satin party saree", "Sarees", "pcs", 780, 90, .12, "fabric-rolls-pattern.jpg", {"M07": 5.5, "M17": 0.04, "M18": 1}),
    ("S08", "Wedding saree, gold border", "Sarees", "pcs", 3200, 520, .08, "saree-red.jpg", {"M05": 6.3, "M10": 0.9, "M18": 1}),
    ("S09", "Daily-wear cotton saree", "Sarees", "pcs", 420, 45, .11, "saree-embroidered.jpg", {"M06": 5.5, "M18": 1}),
    ("F01", "National flag, 2 × 3 ft", "Flags", "pcs", 180, 22, .30, "flag-tricolour.jpg", {"M08": 0.62, "M17": 0.01, "M11": 0.02, "M18": 1}),
    ("F02", "National flag, 3 × 4.5 ft", "Flags", "pcs", 340, 30, .25, "flag-tricolour.jpg", {"M08": 1.3, "M17": 0.02, "M11": 0.03, "M18": 1}),
    ("F03", "National flag, 4 × 6 ft", "Flags", "pcs", 560, 42, .10, "flag-sky.jpg", {"M08": 2.3, "M17": 0.03, "M11": 0.04, "M18": 1}),
    ("F04", "National flag, 6 × 9 ft", "Flags", "pcs", 1150, 70, .04, "flag-sky.jpg", {"M08": 5.1, "M17": 0.06, "M11": 0.06, "M18": 1}),
    ("F05", "Table flag with stand", "Flags", "pcs", 95, 12, .12, "flag-tricolour.jpg", {"M08": 0.05, "M17": 0.002, "M18": 1}),
    ("F06", "Saffron flag, 2 × 3 ft", "Flags", "pcs", 150, 18, .12, "", {"M21": 0.62, "M16": 0.01, "M11": 0.02, "M18": 1}),
    ("F07", "Saffron flag, 3 × 4.5 ft", "Flags", "pcs", 260, 26, .07, "", {"M21": 1.3, "M16": 0.02, "M11": 0.03, "M18": 1}),
    ("B01", "Shirting, white, 58 in", "Fabric", "m", 110, 14, .20, "fabric-rolls-pattern.jpg", {"M09": 0.12, "M17": 0.001}),
    ("B02", "Shirting, sky blue, 58 in", "Fabric", "m", 120, 15, .15, "blue-shirts.jpg", {"M09": 0.12, "M15": 0.004}),
    ("B03", "Shirting, checks, 58 in", "Fabric", "m", 135, 17, .12, "fabric-rolls-pattern.jpg", {"M09": 0.13, "M15": 0.003}),
    ("B04", "Printed poplin, 44 in", "Fabric", "m", 120, 10, .15, "fabric-rolls.jpg", {"M21": 1.05, "M17": 0.01}),
    ("B05", "Suiting, navy, 58 in", "Fabric", "m", 220, 20, .10, "navy-fabric.jpg", {"M09": 0.18, "M15": 0.008}),
    ("B06", "Cotton cambric, 44 in", "Fabric", "m", 95, 8, .14, "white-textile.jpg", {"M21": 1.05}),
    ("B07", "Latha, white cotton, 36 in", "Fabric", "m", 70, 6, .14, "white-textile.jpg", {"M21": 1.02}),
    ("D01", "Dhoti, white cotton, 4.5 m", "Dhoti & Safi", "pcs", 310, 25, .35, "white-textile.jpg", {"M21": 4.6, "M18": 1}),
    ("D02", "Dhoti, cream with silk border", "Dhoti & Safi", "pcs", 480, 40, .20, "white-textile.jpg", {"M21": 4.6, "M10": 0.1, "M18": 1}),
    ("D03", "Dhoti-kurta set", "Dhoti & Safi", "pcs", 750, 95, .15, "white-textile.jpg", {"M21": 7.0, "M11": 0.2, "M12": 4, "M18": 1}),
    ("D04", "Safi, saffron", "Dhoti & Safi", "pcs", 180, 12, .15, "", {"M21": 1.0, "M16": 0.02, "M18": 1}),
    ("D05", "Safi, white", "Dhoti & Safi", "pcs", 140, 10, .15, "", {"M21": 1.0, "M18": 1}),
]
CATEGORIES = ["Fabric", "Uniforms", "Sarees", "Flags", "Dhoti & Safi"]
# base sales in Rs lakh per month (Jan..Dec) at the Nov-2025 to Oct-2026 level, before festival bumps
BASE = {
    "Fabric":       [4.0, 3.9, 4.1, 4.4, 4.6, 4.3, 4.0, 4.2, 4.5, 5.1, 5.2, 4.2],
    "Uniforms":     [2.8, 4.5, 8.2, 11.6, 12.9, 9.4, 4.2, 3.0, 2.6, 2.9, 3.2, 3.1],
    "Sarees":       [2.0, 2.1, 2.1, 2.5, 2.8, 2.4, 2.2, 2.6, 2.6, 2.6, 2.8, 2.6],
    "Flags":        [0.9, 0.9, 0.8, 0.7, 0.8, 0.9, 1.0, 1.1, 1.0, 0.9, 1.1, 1.0],
    "Dhoti & Safi": [1.1, 1.3, 1.2, 1.4, 1.5, 1.2, 1.0, 1.1, 1.2, 1.4, 1.6, 1.5],
}
DIWALI = [date(2024, 11, 1), date(2025, 10, 21), date(2026, 11, 8), date(2027, 10, 29)]
LEAD = {"Uniforms": 10, "Sarees": 14, "Flags": 6, "Fabric": 7, "Dhoti & Safi": 6}
BUYERS = {  # who buys each category
    "Uniforms": {"School": .85, "Retailer": .15},
    "Sarees": {"Retailer": .80, "Wholesaler": .20},
    "Flags": {"Government": .45, "Retailer": .25, "School": .15, "Wholesaler": .15},
    "Fabric": {"Retailer": .50, "Wholesaler": .40, "School": .10},
    "Dhoti & Safi": {"Retailer": .70, "Wholesaler": .30},
}
ORDER_SIZE = {"School": 30_000, "Retailer": 5_000, "Government": 10_000, "Wholesaler": 15_000}  # mean Rs
CREDIT = {"School": 45, "Retailer": 30, "Government": 60, "Wholesaler": 30}
CITIES = ["Kota", "Bundi", "Baran", "Jhalawar", "Jaipur", "Ajmer", "Bhilwara", "Sawai Madhopur", "Sheopur",
          "Gwalior", "Indore", "Ujjain", "Bhopal", "Chittorgarh", "Tonk"]
SCHOOLS = ["Green Valley School", "St. Mary's Convent", "Kendriya Vidyalaya No. 2", "Delhi Public School",
           "Saraswati Shishu Mandir", "Modern Public School", "Holy Cross School", "Sunrise Academy",
           "Adarsh Vidya Mandir", "Little Flower School", "Shiksha Bharti School", "Mayur Public School",
           "Vivekanand Vidyalaya", "Sophia Girls' School", "Army Public School", "Rose Garden School",
           "Bal Bharti School", "Gyan Jyoti Academy", "Lotus Valley School", "City Montessori School"]
RETAILERS = ["Shree Ganesh Cloth Store", "Lakshmi Textiles", "Agarwal Saree Kendra", "Mahavir Vastra Bhandar",
             "Jain Cloth House", "Sethi Fabrics", "Raj Saree Palace", "Gupta Kapda Bhandar", "Bansal Textiles",
             "Krishna Cloth Centre", "Shubham Sarees", "New Fashion Cloth Store", "Om Textiles",
             "Maheshwari Vastralaya", "Rathi Saree Sadan", "Khandelwal Cloth Store", "Sai Kripa Textiles",
             "Shyam Vastra Bhandar", "Mittal Cloth Emporium", "Hari Om Sarees", "Goyal Fabrics", "Ambika Textiles"]
GOVERNMENT = ["City Municipal Office", "Collectorate", "Police Lines", "District Panchayat",
              "Railway Division Office", "Nagar Parishad", "Government Girls' College", "Zila Parishad"]
WHOLESALERS = ["Kota Cloth Market Traders", "Jaipur Wholesale Textiles", "Indore Kapda Mandi Agency",
               "Bhopal Textile Agency", "Gwalior Fabric Depot", "Ajmer Cloth Merchants",
               "Ujjain Vastra Wholesale", "Bhilwara Textile Traders"]


def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or os.urandom(8).hex()
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000).hex()
    return f"{salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    salt, _ = stored.split("$", 1)
    return hash_password(password, salt) == stored


# ----------------------------------------------------------------------------- demand curve
@functools.lru_cache(maxsize=None)
def daily_level(cat: str, d: date) -> float:
    """Expected sales in Rs for one category on one day (before randomness)."""
    days = calendar.monthrange(d.year, d.month)[1]
    rs = BASE[cat][d.month - 1] * 1e5 / days
    rs *= 1.08 ** ((d - date(2025, 11, 1)).days / 365)       # ~8% growth a year
    if cat == "Sarees":
        for dw in DIWALI:                                     # Diwali buying: 5 weeks before, peak 10 days before
            gap = (dw - d).days
            if 0 <= gap <= 35:
                rs += 4.6e5 / 35 * 2 * (1 - abs(gap - 10) / 26) * (1.08 ** ((d - date(2025, 11, 1)).days / 365))
        if (d.month == 11 and d.day >= 15) or (d.month == 12 and d.day <= 15) or d.month == 2:
            rs *= 1.35                                        # wedding season
    if cat == "Flags":
        for target in (date(d.year, 1, 26), date(d.year, 8, 15)):
            gap = (target - d).days
            if 0 <= gap <= 28:                                # 4 weeks before 26 Jan / 15 Aug
                rs += 6.0e5 / 28 * 2 * (1 - gap / 28) * (1.08 ** ((d - date(2025, 11, 1)).days / 365))
    if cat == "Dhoti & Safi":
        for dw in DIWALI:
            if 0 <= (dw - d).days <= 25:
                rs *= 1.6
    if d.weekday() == 6:                                      # Sunday: market mostly closed
        rs *= 0.35
    return rs


def month_iter(a: date, b: date):
    d = date(a.year, a.month, 1)
    while d <= b:
        yield d
        d = date(d.year + (d.month == 12), d.month % 12 + 1, 1)


# ----------------------------------------------------------------------------- build
def build(today: date = TODAY, seed: int = SEED, verbose: bool = True):
    rng = np.random.default_rng(seed)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    db = SessionLocal()

    db.add(User(name="Demo owner", email="owner@vastramills.in", password_hash=hash_password("vastra-demo"), role="owner"))
    sups = [Supplier(name=n, city=c, lead_days=l) for n, c, l in SUPPLIERS]
    db.add_all(sups)
    db.flush()
    mats = {}
    for code, name, unit, cost, si, photo in MATERIALS:
        mats[code] = Material(code=code, name=name, unit=unit, cost=cost, supplier_id=sups[si].id, photo=photo)
    db.add_all(mats.values())
    db.flush()
    prods = {}
    for sku, name, cat, unit, price, labour, w, photo, bom in PRODUCTS:
        p = Product(sku=sku, name=name, category=cat, unit=unit, price=price, labour_cost=labour, photo=photo)
        p.weight = w
        for code, q in bom.items():
            p.bom.append(BomLine(material_id=mats[code].id, qty=q))
        prods[sku] = p
    db.add_all(prods.values())
    db.flush()

    # customers
    custs = defaultdict(list)
    for i, n in enumerate(SCHOOLS):
        custs["School"].append(Customer(name=f"{n}, {CITIES[i % len(CITIES)]}", kind="School", city=CITIES[i % len(CITIES)], credit_days=45))
    for i, n in enumerate(RETAILERS):
        city = CITIES[(i * 3) % len(CITIES)]
        custs["Retailer"].append(Customer(name=f"{n}, {city}", kind="Retailer", city=city, credit_days=30))
    for i, n in enumerate(GOVERNMENT):
        city = CITIES[(i * 2) % 8]
        custs["Government"].append(Customer(name=f"{n}, {city}", kind="Government", city=city, credit_days=60))
    for n in WHOLESALERS:
        custs["Wholesaler"].append(Customer(name=n, kind="Wholesaler", city=n.split()[0], credit_days=30))
    for lst in custs.values():
        db.add_all(lst)
    db.flush()
    # payment habit per customer: mean days late after due date (some always late)
    habit = {c.id: float(rng.choice([-5, 0, 3, 8, 20, 40], p=[.15, .25, .25, .17, .12, .06])) for lst in custs.values() for c in lst}
    cust_weight = {k: rng.dirichlet(np.ones(len(v)) * 1.5) for k, v in custs.items()}

    by_cat = defaultdict(list)
    for p in prods.values():
        by_cat[p.category].append(p)
    unit_cost = {p.sku: sum(b.qty * mats_by_id(mats)[b.material_id].cost for b in p.bom) + p.labour_cost for p in prods.values()}

    # expected units per day per product (used by the planner) and starting stock
    def expected_units(p, d, horizon):
        tot = 0.0
        for k in range(horizon):
            dd = d + timedelta(days=k)
            tot += daily_level(p.category, dd) * p.weight / p.price
        return tot

    for p in prods.values():
        p.safety_stock = int(math.ceil(expected_units(p, date(2025, 6, 1), 14) / 10) * 10)
        p.batch_size = {"pcs": 50, "m": 200}[p.unit] if p.category != "Sarees" else 20

    stock_p = defaultdict(float)
    stock_m = defaultdict(float)
    moves = []

    def move(d, qty, reason, ref, product=None, material=None):
        moves.append({"move_date": d, "product_id": product, "material_id": material, "qty": round(qty, 3), "reason": reason, "ref": ref})

    for p in prods.values():
        q = round(expected_units(p, START, 42) + p.safety_stock)
        stock_p[p.id] = q
        move(START, q, "opening", "Opening stock", product=p.id)

    # material usage per day at average demand -> reorder settings
    m_daily = defaultdict(float)
    for p in prods.values():
        avg = expected_units(p, date(2025, 11, 1), 365) / 365
        for b in p.bom:
            m_daily[b.material_id] += avg * b.qty
    sup_lead = {s.id: s.lead_days for s in sups}
    for m in mats.values():
        lead = sup_lead[m.supplier_id]
        m.safety_stock = round(m_daily[m.id] * 10, 2)
        m.reorder_qty = round(max(m_daily[m.id] * 30, 1), 0)   # about a month of use
        q = round(m_daily[m.id] * (lead + 30) + m.safety_stock, 1)
        stock_m[m.id] = q
        move(START, q, "opening", "Opening stock", material=m.id)
    m_by_id = {m.id: m for m in mats.values()}

    open_orders = deque()
    open_wos = []
    open_pos = []
    counters = {"so": 1000, "wo": 1000, "po": 500, "inv": 0}
    wo_rows, so_rows, inv_rows, pay_rows, po_rows, sp_rows = [], [], [], [], [], []
    lines_cycle = 0
    usage_hist = defaultdict(lambda: deque(maxlen=60))

    d = START
    while d <= today:
        # 1) suppliers deliver
        for po in list(open_pos):
            if po.expected_date <= d and rng.random() < 0.8 or (d - po.expected_date).days >= 4:
                po.received_date = d
                po.status = "Received"
                for l in po.lines:
                    stock_m[l.material_id] += l.qty
                    move(d, l.qty, "purchase", po.number, material=l.material_id)
                pay_on = d + timedelta(days=int(30 + rng.integers(-3, 15)))
                if pay_on <= today:
                    sp_rows.append(SupplierPayment(po=po, pay_date=pay_on, amount=round(po.amount, 2)))
                open_pos.remove(po)

        # 2) work orders: start (consume materials) and finish (add stock)
        used_today = defaultdict(float)
        for wo in list(open_wos):
            p = wo.product
            if wo.stage == "Planned" and wo.start_date <= d:
                need = {b.material_id: b.qty * wo.qty for b in p.bom}
                if all(stock_m[mid] >= q for mid, q in need.items()):
                    for mid, q in need.items():
                        stock_m[mid] -= q
                        used_today[mid] += q
                        move(d, -q, "consumption", wo.number, material=mid)
                    wo.stage = "Cutting"
                    span = LEAD[p.category]
                    wo.start_date = d
                    wo.due_date = d + timedelta(days=span)
                else:
                    wo.start_date = d + timedelta(days=1)       # wait for material
                    wo.due_date = wo.due_date + timedelta(days=1)
            elif wo.stage != "Planned":
                span = max((wo.due_date - wo.start_date).days, 1)
                frac = (d - wo.start_date).days / span
                wo.stage = "Cutting" if frac < .3 else "Stitching" if frac < .7 else "Finishing" if frac < 1 else "Packed"
                if wo.stage == "Packed":
                    wo.done_date = d
                    stock_p[p.id] += wo.qty
                    move(d, wo.qty, "production", wo.number, product=p.id)
                    open_wos.remove(wo)
        for m in mats.values():
            usage_hist[m.id].append(used_today.get(m.id, 0.0))

        # 3) new customer orders
        for cat in CATEGORIES:
            level = daily_level(cat, d)
            kinds = list(BUYERS[cat])
            probs = np.array([BUYERS[cat][k] for k in kinds])
            mean_size = sum(BUYERS[cat][k] * ORDER_SIZE[k] for k in kinds)
            n = rng.poisson(level / mean_size)
            for _ in range(n):
                kind = kinds[rng.choice(len(kinds), p=probs)]
                value = ORDER_SIZE[kind] * rng.lognormal(-0.1, 0.45)
                cust = custs[kind][rng.choice(len(custs[kind]), p=cust_weight[kind])]
                items = by_cat[cat]
                w = np.array([p.weight for p in items]); w = w / w.sum()
                k = int(min(len(items), 1 + rng.poisson(1.2 if kind != "Retailer" else 0.8)))
                chosen = rng.choice(len(items), size=k, replace=False, p=w)
                shares = rng.dirichlet(np.ones(k) * 2)
                counters["so"] += 1
                so = SalesOrder(number=f"SO-{counters['so']}", customer_id=cust.id, order_date=d,
                                due_date=d + timedelta(days=int(rng.integers(10, 25) if kind == "School" else rng.integers(3, 11))),
                                status="Open")
                so.customer = cust
                so.ship_after = d + timedelta(days=int(rng.integers(10, 26) if kind == "School" else rng.integers(2, 8)))
                for idx, sh in zip(chosen, shares):
                    p = items[idx]
                    step = 10 if (kind == "School" and p.unit == "pcs") else (10 if p.unit == "m" else 1)
                    qty = max(step, round(value * sh / p.price / step) * step)
                    so.lines.append(SalesOrderLine(product_id=p.id, qty=qty, price=p.price))
                so_rows.append(so)
                open_orders.append(so)

        # 4) ship what we can (first come, first served)
        for so in list(open_orders):
            if d >= so.ship_after and all(stock_p[l.product_id] >= l.qty for l in so.lines):
                for l in so.lines:
                    stock_p[l.product_id] -= l.qty
                    move(d, -l.qty, "sale", so.number, product=l.product_id)
                so.shipped_date = d
                so.status = "Shipped"
                open_orders.remove(so)
                counters["inv"] += 1
                amt = round(so.amount, 2)
                inv = Invoice(number=f"INV-{d.year}-{counters['inv']:05d}", order_id=None, customer_id=so.customer_id,
                              invoice_date=d, due_date=d + timedelta(days=CREDIT[so.customer.kind]), amount=amt)
                inv.order = so
                inv_rows.append(inv)
                late = max(-10, rng.normal(habit[so.customer_id], 6))
                pay_on = inv.due_date + timedelta(days=int(late))
                if rng.random() < 0.15:          # pays in two parts
                    first = inv.invoice_date + timedelta(days=int(max(3, (pay_on - inv.invoice_date).days * .5)))
                    if first <= today:
                        pay_rows.append(Payment(invoice=inv, pay_date=first, amount=round(amt * .5, 2), mode="Cheque"))
                    if pay_on <= today:
                        pay_rows.append(Payment(invoice=inv, pay_date=pay_on, amount=round(amt - round(amt * .5, 2), 2), mode="Bank transfer"))
                elif pay_on <= today and rng.random() > 0.01:
                    pay_rows.append(Payment(invoice=inv, pay_date=pay_on, amount=amt,
                                            mode=str(rng.choice(["Bank transfer", "UPI", "Cheque"], p=[.6, .25, .15]))))

        # 5) planner: raise work orders to cover demand over lead time + 3 weeks
        backlog = defaultdict(float)
        for so in open_orders:
            for l in so.lines:
                backlog[l.product_id] += l.qty
        wip = defaultdict(float)
        for wo in open_wos:
            wip[wo.product_id] += wo.qty
        for p in prods.values():
            horizon = LEAD[p.category] + 21
            need = expected_units(p, d, horizon) * rng.normal(1.0, 0.08) + p.safety_stock + backlog[p.id]
            have = stock_p[p.id] + wip[p.id]
            if have < need:
                qty = math.ceil((need - have) / p.batch_size) * p.batch_size
                counters["wo"] += 1
                lines_cycle += 1
                wo = WorkOrder(number=f"WO-{counters['wo']}", product_id=p.id, qty=qty,
                               line=f"Line {lines_cycle % 3 + 1}", start_date=d + timedelta(days=1),
                               due_date=d + timedelta(days=1 + LEAD[p.category]), stage="Planned")
                wo.product = p
                wo_rows.append(wo)
                open_wos.append(wo)

        # 6) buyer: reorder materials below the reorder point, one PO per supplier
        on_order = defaultdict(float)
        for po in open_pos:
            for l in po.lines:
                on_order[l.material_id] += l.qty
        planned_need = defaultdict(float)
        for wo in open_wos:
            if wo.stage == "Planned":
                for b in wo.product.bom:
                    planned_need[b.material_id] += b.qty * wo.qty
        to_buy = defaultdict(list)
        buyer_day = d.weekday() in (0, 3) and d != today   # buyer reviews on Mon and Thu; today's review is left to the user
        for m in (mats.values() if buyer_day else []):
            hist = usage_hist[m.id]
            rate = max(sum(hist) / max(len(hist), 1), m_daily[m.id] * 0.5)
            lead = sup_lead[m.supplier_id]
            rop = rate * lead + m.safety_stock
            position = stock_m[m.id] + on_order[m.id] - planned_need[m.id]
            if position < rop:
                qty = max(m.reorder_qty, rop - position + rate * 14)
                qty = round(qty, 0) if m.unit in ("pcs", "m") else round(qty, 1)
                to_buy[m.supplier_id].append((m, qty))
        for sid, items in to_buy.items():
            counters["po"] += 1
            po = PurchaseOrder(number=f"PO-{counters['po']}", supplier_id=sid, order_date=d,
                               expected_date=d + timedelta(days=sup_lead[sid] + int(rng.integers(0, 3))), status="Ordered")
            for m, qty in items:
                po.lines.append(PurchaseOrderLine(material_id=m.id, qty=qty, cost=round(m.cost * rng.normal(1, 0.03), 2)))
            po_rows.append(po)
            open_pos.append(po)
        d += timedelta(days=1)

    # expenses, month by month
    exp_rows = []
    for m0 in month_iter(START, today):
        last = min(date(m0.year, m0.month, calendar.monthrange(m0.year, m0.month)[1]), today)
        growth = 1.08 ** ((m0 - date(2025, 11, 1)).days / 365)
        for cat, amt in (("Wages", 2.9e5), ("Power", 0.48e5), ("Rent", 0.55e5), ("Transport", 0.22e5), ("Other", 0.15e5)):
            a = amt * (growth if cat != "Rent" else 1) * (rng.normal(1, 0.06) if cat != "Rent" else 1)
            if last < date(m0.year, m0.month, calendar.monthrange(m0.year, m0.month)[1]) and cat in ("Wages", "Power"):
                continue  # current month not closed yet
            exp_rows.append(Expense(exp_date=last if cat != "Rent" else m0, category=cat, amount=round(a, 0)))

    db.add_all(so_rows); db.add_all(inv_rows); db.add_all(pay_rows)
    db.add_all(wo_rows); db.add_all(po_rows); db.add_all(sp_rows); db.add_all(exp_rows)
    db.flush()
    db.execute(insert(StockMove), moves)
    db.commit()
    if verbose:
        print(f"products {len(prods)}, materials {len(mats)}, customers {sum(len(v) for v in custs.values())}")
        print(f"orders {len(so_rows)} (open {len(open_orders)}), invoices {len(inv_rows)}, payments {len(pay_rows)}")
        print(f"work orders {len(wo_rows)} (open {len(open_wos)}), POs {len(po_rows)} (open {len(open_pos)}), stock moves {len(moves)}")
    db.close()


def mats_by_id(mats):
    return {m.id: m for m in mats.values()}


if __name__ == "__main__":
    build()
