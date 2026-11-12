# Interview notes: Vastra Mills ERP

Short answers you can say out loud. Practise them; don't read them.

## The 30-second pitch

"I built a working ERP for a textile mill that makes uniforms, sarees and flags, the same products my family's cloth shop sells. It handles stock, production, purchasing, sales and accounts in FastAPI with a SQL database. Because the business is very seasonal, I added a demand forecast that knows the festival calendar, and I checked it honestly against a simple 'same month last year' baseline. It also tells the owner what to reorder, using reorder points and EOQ."

## Data

**Where does the data come from?**
A simulation I wrote (`app/seed.py`). It plays out every day for two years: orders arrive with seasonal demand, orders ship only if stock exists, a planner raises work orders, a buyer raises purchase orders when material falls below the reorder point, and customers pay after their credit days with their own habits. So the tables are consistent with each other, like a real ERP's.

**Why simulate instead of using a Kaggle dataset?**
I needed linked tables: orders, invoices, payments, stock, production and purchases for the same company. Public datasets usually give one table. The trade-off is that the model learns patterns I designed; I say that in the README.

**Why is stock a ledger and not a number on the product?**
Every change is a row in `stock_moves` (purchase, consumption, production, sale). Stock = sum of rows. You can always explain a number, and it can't drift out of sync with the documents.

## Forecasting

**What model?**
Ridge regression on daily sales per category, with calendar features: month, Sunday, days-before-Diwali windows, days before 26 Jan / 15 Aug, and wedding season. Old days are scaled by year-on-year growth.

**Why not ARIMA or Prophet?**
Two years is short. The demand is driven by known calendar events, so a regression with those events as features is simple, explainable and handles a moving Diwali directly. Prophet would be the next thing to try; it does a similar decomposition.

**Why ridge and not plain least squares?**
Some festival windows appear only once or twice in two years. The penalty stops those weights from becoming extreme.

**How did you test it?**
Rolling-origin backtest: forecast from four past month-ends, three months ahead each, never letting the model see the months it predicts. Metric WAPE. I compare with a seasonal-naive baseline.

**Did it beat the baseline?**
Honestly, over the backtest months it was about equal (≈13% vs ≈11% WAPE), because no festival moved in those months. In November 2026, when Diwali moved from October to November, the model expected ₹2.8 L of saree orders in the first 12 days; actual was ₹2.6 L; the baseline said ₹1.2 L. So the model earns its place when the calendar shifts. I'd rather report that than tune until the backtest looks good.

**What is WAPE and why not MAPE?**
Sum of absolute errors divided by sum of actuals. MAPE blows up when an actual is near zero (flags in a quiet month); WAPE weights errors by size.

## Inventory

**Reorder point?**
Daily use × supplier lead time + safety stock. I compare it with the inventory position: on hand + on order − what planned work orders will take.

**EOQ?**
√(2 × yearly demand × ordering cost ÷ holding cost per unit). It balances the cost of ordering often against the cost of holding stock. For cheap items like buttons it says "order a lot at once"; for silk it says "order less, more often".

## Engineering

**Why FastAPI and server-rendered pages?**
One Python codebase, fast to build, no separate front end. FastAPI gives dependency injection for the database session and login check.

**SQLite now, Postgres later?**
Everything goes through SQLAlchemy, so switching is one environment variable (`DATABASE_URL`). The SQL views are written without database-specific functions so they run on both.

**How do you keep business rules consistent?**
All actions live in `services/ops.py`: starting a work order checks and issues materials, shipping checks stock and writes the invoice. Pages and tests call the same functions. 22 pytest tests check pages, stock never going negative, and each flow.

**Security basics?**
Passwords hashed with PBKDF2 (salted), signed session cookie with a secret from the environment, every page behind a login check, CSV exports need a key.

## Learnings

- A baseline is not a formality. "Same month last year" was hard to beat; the model's value is specific (moving festivals), and saying that clearly is more convincing than a big accuracy claim.
- Simulated data needs care: my first version had so few, large orders that monthly sales were mostly noise. Smaller, more frequent orders made seasonality visible, as in real B2B textile sales.
- Designing the screens first saved rework: the first four looks were rejected as mockups, not as finished code, and the final pages match what the owner wanted (bright, photo-rich).
- Making stock a ledger made every bug visible: if a number looked wrong, the rows explained why.

## If they ask "what next?"

Batch/lot tracking for dye lots, GST-compliant invoices, a mobile view for the floor supervisor, and a probabilistic forecast (quantiles) so safety stock comes from forecast error instead of a fixed number of days.
