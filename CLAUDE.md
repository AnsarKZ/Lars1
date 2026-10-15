# CLAUDE.md: working rules for this repository

Performance dashboard prototype: Amazon DE/FR/IT/UK, 8 products, 26 weeks. See README.md for
the business context.

## Commands
- Build: `python -m perfdash` → `site/index.html` (standalone), `out/artifact.html` (fragment), `out/model/*.csv`
- Tests: `python -m pytest`

## Money rules you must not break
- **Everything is net EUR.** UK: convert with the monthly average rate of the transaction month,
  then remove VAT (DE 19 %, FR 20 %, IT 22 %, UK 20 %). Applies to sales and ad sales.
- Ad spend is already net (convert UK only). The Amazon commission is 15 % of the **gross** price.
- Landed cost already contains freight & customs (CM1). Storage fee is separate (CM3, estimated).
- Never use list prices for history; they are "current state". Use actual sales prices.

## Data rules
- File 01 has exact duplicate rows (IT, July): drop them; a conflicting duplicate key must raise.
- File 02: IT uses lower-case SKUs. Upper-casing is allowed **only** because the ASIN is checked
  on every row; a SKU/ASIN mismatch must raise.
- File 03 is German formatted: parse dates and amounts explicitly, never with a global `thousands='.'`.
- Weeks are Monday–Sunday; a Monday stock count is the stock after Sunday.
- Ad sales of the last 7 days are incomplete (attribution window). Ad status rules use the 4 weeks
  before the reporting week.

## Code conventions
- `perfdash/kpis.py` is the only place KPIs are defined; `summarize()` derives every ratio from
  the additive measures in `fact_week`. Don't compute KPIs in the page or the rules ad hoc.
- Thresholds live in `perfdash/config.py` (`RULES`), not in the rule code.
- The HTML template only displays the embedded payload; all numbers come from Python.
- Every status rule needs a minimum volume. Every new rule needs a test; if the critical set
  changes, update `tests/test_dashboard.py` and the README together, after checking the raw CSVs.
- Copy in the page and the actions is for business users: number, cause, action, effect.
