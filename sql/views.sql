-- Analytics views for Power BI (and any SQL tool).
-- Plain joins only, so the same file runs on SQLite and Postgres.
-- The app creates them on start; /export/<name>.csv serves each one as a CSV.

DROP VIEW IF EXISTS v_sales_lines;
CREATE VIEW v_sales_lines AS
SELECT o.number        AS order_number,
       o.order_date,
       o.due_date,
       o.shipped_date,
       o.status        AS order_status,
       c.name          AS customer,
       c.kind          AS customer_type,
       c.city,
       p.sku,
       p.name          AS product,
       p.category,
       l.qty,
       l.price,
       l.qty * l.price AS value
FROM sales_orders o
JOIN sales_order_lines l ON l.order_id = o.id
JOIN customers c ON c.id = o.customer_id
JOIN products p ON p.id = l.product_id;

DROP VIEW IF EXISTS v_invoices;
CREATE VIEW v_invoices AS
SELECT i.number AS invoice_number,
       i.invoice_date,
       i.due_date,
       c.name   AS customer,
       c.kind   AS customer_type,
       i.amount,
       COALESCE((SELECT SUM(p.amount) FROM payments p WHERE p.invoice_id = i.id), 0) AS paid,
       i.amount - COALESCE((SELECT SUM(p.amount) FROM payments p WHERE p.invoice_id = i.id), 0) AS balance,
       (SELECT MAX(p.pay_date) FROM payments p WHERE p.invoice_id = i.id) AS last_payment_date
FROM invoices i
JOIN customers c ON c.id = i.customer_id;

DROP VIEW IF EXISTS v_payments;
CREATE VIEW v_payments AS
SELECT i.number AS invoice_number, c.name AS customer, p.pay_date, p.amount, p.mode
FROM payments p
JOIN invoices i ON i.id = p.invoice_id
JOIN customers c ON c.id = i.customer_id;

DROP VIEW IF EXISTS v_stock_moves;
CREATE VIEW v_stock_moves AS
SELECT m.move_date,
       CASE WHEN m.product_id IS NOT NULL THEN 'Product' ELSE 'Material' END AS item_type,
       COALESCE(p.sku, ma.code)  AS item_code,
       COALESCE(p.name, ma.name) AS item_name,
       COALESCE(p.category, 'Material') AS category,
       m.qty,
       m.reason,
       m.ref
FROM stock_moves m
LEFT JOIN products p ON p.id = m.product_id
LEFT JOIN materials ma ON ma.id = m.material_id;

DROP VIEW IF EXISTS v_work_orders;
CREATE VIEW v_work_orders AS
SELECT w.number AS work_order, p.sku, p.name AS product, p.category, w.qty, w.line,
       w.start_date, w.due_date, w.done_date, w.stage
FROM work_orders w
JOIN products p ON p.id = w.product_id;

DROP VIEW IF EXISTS v_purchase_lines;
CREATE VIEW v_purchase_lines AS
SELECT po.number AS po_number, s.name AS supplier, po.order_date, po.expected_date, po.received_date, po.status,
       m.code AS material_code, m.name AS material, l.qty, l.cost, l.qty * l.cost AS value
FROM purchase_orders po
JOIN purchase_order_lines l ON l.po_id = po.id
JOIN suppliers s ON s.id = po.supplier_id
JOIN materials m ON m.id = l.material_id;

DROP VIEW IF EXISTS v_products;
CREATE VIEW v_products AS
SELECT p.sku, p.name, p.category, p.unit, p.price, p.labour_cost, p.safety_stock, p.batch_size,
       COALESCE((SELECT SUM(b.qty * m.cost) FROM bom_lines b JOIN materials m ON m.id = b.material_id
                 WHERE b.product_id = p.id), 0) + p.labour_cost AS unit_cost
FROM products p;

DROP VIEW IF EXISTS v_expenses;
CREATE VIEW v_expenses AS
SELECT exp_date, category, amount FROM expenses;
