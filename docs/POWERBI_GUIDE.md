# Power BI guide: Vastra Mills sales and operations report

You build the `.pbix` yourself. This guide gives the data, the model, the DAX and the pages. Save your file as `powerbi/vastra_mills.pbix` in this repo and add screenshots to the README when done.

Time needed: about 3–4 hours.

## 1. Get the data (15 min)

Run the app (locally or on Render) and open `/export`. Each link is one SQL view from `sql/views.sql`.

In Power BI Desktop: **Home → Get data → Web**, paste the link, **OK**. Repeat for:

| Table name in Power BI | Link | What it is |
|---|---|---|
| `Sales` | `/export/sales_lines.csv?key=vastra-demo` | One row per order line (the fact table) |
| `Invoices` | `/export/invoices.csv?key=vastra-demo` | Amount, paid, balance per invoice |
| `Stock` | `/export/stock_moves.csv?key=vastra-demo` | Every stock movement |
| `Products` | `/export/products.csv?key=vastra-demo` | Price and unit cost per SKU |
| `Forecast` | `/export/forecast.csv?key=vastra-demo` | Monthly actual + forecast by category |
| `Expenses` | `/export/expenses.csv?key=vastra-demo` | Overheads |

If running locally the base is `http://127.0.0.1:8000`. If Power BI cannot reach the link, download the CSV from the export page and use **Get data → Text/CSV** instead.

In **Transform data** (Power Query): check every date column is type **Date** and money columns are **Decimal number**. Rename tables as in the first column above. **Close & Apply**.

## 2. Date table (10 min)

**Modeling → New table**:

```DAX
Date =
ADDCOLUMNS (
    CALENDAR ( DATE ( 2024, 11, 1 ), DATE ( 2027, 1, 31 ) ),
    "Year", YEAR ( [Date] ),
    "Month", FORMAT ( [Date], "mmm yyyy" ),
    "MonthStart", DATE ( YEAR ( [Date] ), MONTH ( [Date] ), 1 ),
    "MonthNo", MONTH ( [Date] ),
    "Weekday", FORMAT ( [Date], "ddd" )
)
```

Select the table → **Mark as date table** → column `Date`. Sort `Month` by `MonthStart`.

## 3. Relationships (10 min)

Model view, drag to connect (all one-to-many, single direction):

- `Date[Date]` → `Sales[order_date]`
- `Date[Date]` → `Invoices[invoice_date]`
- `Date[Date]` → `Stock[move_date]`
- `Date[Date]` → `Expenses[exp_date]`
- `Products[sku]` → `Sales[sku]`

This is a **star schema**: facts (Sales, Invoices, Stock) in the middle, dimensions (Date, Products) around them.

## 4. Measures (30 min)

Create a table to hold measures (**Enter data**, name it `_Measures`), then **New measure** for each:

```DAX
Sales = SUM ( Sales[value] )
Orders = DISTINCTCOUNT ( Sales[order_number] )
Avg Order Value = DIVIDE ( [Sales], [Orders] )
Sales LY = CALCULATE ( [Sales], SAMEPERIODLASTYEAR ( 'Date'[Date] ) )
Sales YoY % = DIVIDE ( [Sales] - [Sales LY], [Sales LY] )
Sales 3M Avg = AVERAGEX ( DATESINPERIOD ( 'Date'[Date], MAX ( 'Date'[Date] ), -3, MONTH ), [Sales] ) * 30

Gross Margin =
SUMX ( Sales, Sales[qty] * ( Sales[price] - RELATED ( Products[unit_cost] ) ) )
Gross Margin % = DIVIDE ( [Gross Margin], [Sales] )

Receivable = SUM ( Invoices[balance] )
Overdue =
CALCULATE ( SUM ( Invoices[balance] ), Invoices[due_date] < DATE ( 2026, 11, 12 ), Invoices[balance] > 1 )
Overdue % = DIVIDE ( [Overdue], [Receivable] )

Units Made = CALCULATE ( SUM ( Stock[qty] ), Stock[reason] = "production" )
Units Sold = - CALCULATE ( SUM ( Stock[qty] ), Stock[reason] = "sale" )

Forecast Sales = CALCULATE ( SUM ( Forecast[value] ), Forecast[kind] = "Forecast" )
Actual Sales (monthly) = CALCULATE ( SUM ( Forecast[value] ), Forecast[kind] = "Actual" )
```

Format: Sales and money measures as **₹ Currency, 0 decimals**; % measures as **Percentage, 1 decimal**.

## 5. Pages to build (2 hours)

Keep the app's look: light grey page background `#F0F0F3`, white cards with rounded corners, one blue accent `#0071E3`. Category colours (same as the app): Fabric `#2A78D6`, Uniforms `#EB6834`, Sarees `#1BAF7A`, Flags `#EDA100`, Dhoti & Safi `#E87BA4`.

**Page 1: Overview**
- 4 cards: Sales, Sales YoY %, Gross Margin %, Receivable
- Stacked column: `Date[Month]` × `Sales`, legend `Sales[category]`
- Slicers: Year, category, customer type

**Page 2: Seasonality**
- Line chart: `Date[MonthNo]` × `Sales`, legend `Date[Year]` (shows the school-season and festival peaks repeating)
- Matrix: rows category, columns month, values Sales with conditional formatting (heatmap)
- Text box explaining the three seasons in one line each

**Page 3: Customers and money**
- Bar: top 10 customers by Sales
- Donut or bar: Sales by customer type (School, Retailer, Government, Wholesaler)
- Table: customers with Receivable and Overdue, sorted by Overdue

**Page 4: Operations**
- Column: Units Made vs Units Sold by month
- Table: products with Sales, Gross Margin %, sorted by margin
- Card: Gross Margin %

**Page 5: Forecast vs actual**
- Line chart from the `Forecast` table: month × value, legend `kind`
- Small multiples by category
- A text box: "Forecast from the app's calendar regression; see the Forecast page in the app for the backtest."

## 6. Finish (20 min)

- Add a title text box on each page and the data date ("Data to 12 Nov 2026").
- **File → Publish to web** is NOT needed. Export **PDF** of the report (File → Export → PDF) and take PNG screenshots for the README.
- Write 3 insights you found on the Overview page as text boxes (for example: which category grew most YoY, which customer type is slowest to pay).

## Interview talking points from this report

- Why a separate Date table (time intelligence like `SAMEPERIODLASTYEAR` needs a continuous, marked date table).
- Why measures, not calculated columns, for Sales (they respond to filters; columns are fixed per row).
- What a star schema is and why it keeps DAX simple.
