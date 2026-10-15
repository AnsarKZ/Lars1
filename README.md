# Marketplace Performance Review: Amazon DE · FR · IT · UK

A weekly performance dashboard built from five separate exports (Business Report, Advertising,
FBA stock, controlling product master, FX rates). It shows management in one minute how the
business runs down to contribution margin, and marketplace managers which product in which
marketplace needs attention now.

```bash
pip install pandas openpyxl pytest   # Python >= 3.11
python -m perfdash                   # -> site/index.html (+ model tables in out/model/)
python -m pytest                     # 10 tests
```

Open `site/index.html` in a browser. It is a single self-contained file: the numbers are computed
in Python and embedded, and the page only displays and filters them.

**Every figure is shown with its comparison, and € and % carry equal weight:**
- KPI tiles: € and % of net revenue side by side, each with its own change.
- **Margin statement:** net revenue → landed cost → Amazon fees → CM1 → ads → CM2 → storage → CM3,
  as € per week and % of net revenue, now vs before, with Δ % and Δ pp.
- **Why CM2 % moved:** a bridge in percentage points, from CM2 % before through the change in each
  cost ratio to CM2 % now. The steps add up exactly.
- Trends in € and in %, with the selected and the comparison period shaded; marketplaces compared
  side by side.

**Periods: 1W · 4W · 8W · 16W · 24W.** Each is compared with the same number of weeks before it.
The data only covers 26 weeks, so 16W is compared with the 10 earlier weeks and 24W with the 2
earlier weeks. That is why € changes are always **per week** and margins always **% of net
revenue**: both stay comparable when the two periods differ in length. The page labels partial
comparisons.

---

## 1. The three actions for next week

Reporting week **KW 39 (21.–27.09.2026)**. The actions are ranked by **what one more week of
waiting costs in CM2**, so a stock-out, a loss-making campaign and a lost buy box can be
compared on one scale.

| | **1 · Reorder Isolierflasche 750 ml Anthrazit (EU) today** | **2 · Cut ad budgets for the Glaskaraffe 1,8 l** | **3 · Win back the buy box for the Brotkasten in FR** |
|---|---|---|---|
| **Number** | **511 units** left in the EU pool, selling **378/week**, so out of stock in **~9 days**. Nothing inbound; reorder time **45 days**. | CM2 **−€2,448/week**; ads **€7,535/week**. ACoS (net) DE 69 %, FR 69 %, **IT 111 %**, UK 64 % vs break-even ~34 %. | Buy box **98 % → 42 %** since 24.08. Visitors unchanged (289 → 303/week) but units **28 → 10/week**. |
| **Cause** | No purchase order after the last delivery (20.07.); cover fell below the reorder time. The SKU is the top seller: **43 % of all CM2**. | Launch budgets run at ~8× the other products and efficiency isn't improving after 4 months; every ad-driven sale costs more than it earns. | Another seller wins the basket button on our listing. Only FR is affected and our price is unchanged, so it's a reseller, competitor offer or hijacker. |
| **Action** | Order now (MOQ 1,000; previous orders were 3,000), expedite part of it. Cut ads on this SKU in the EU to stretch stock and move that budget to the coral variant (168 weeks of stock) as a substitute. | Bring ACoS under break-even, starting with IT. Keep the converting exact-match campaigns, pause the weakest auto campaigns. | Check the offer list in Seller Central, report unauthorised sellers via Brand Registry, pause FR ads on this listing until the buy box is back. |
| **Expected effect** | Avoids ~5.1 weeks out of stock: **~1,900 units / €13.9k CM2**, plus the lost ranking just before Q4. Each week of delay costs **~€2.7k**. | Spend at break-even ACoS ≈ €3.6k/week, so **≈ €3.9k/week less ad cost**, stopping most of the **€2.4k/week** loss. | **≈ 18 units/week** back: ≈ €750/week net revenue, ≈ €180/week CM2. |

**Watch list (no action this week):** the coral bottle ties up **€33k** at 168 weeks of cover
(EU) and 76 weeks (UK), about €790/month storage. The SPS-2 price rise on 03.08. (€24.99 → €27.99)
lifted margin, while conversion dipped slightly in DE/IT.

## 2. Value handling (agreed conventions)

- **Everything in net EUR.** UK is first converted with the **monthly average rate of the transaction
  month** (file 05), then VAT is removed: `net = gross ÷ (1 + VAT)` with DE 19 %, FR 20 %, IT 22 %, UK 20 %.
  This applies to sales (01) and ad sales (02).
- **Ad spend** is already net; only UK is converted.
- **Amazon commission** is computed on the gross price, because that's how Amazon charges it
  (15 % of what the customer pays), and then carried as a net cost.
- **Landed cost** = purchase + freight & customs (checked for all 8 SKUs), so freight and customs
  are in CM1. **Storage** is the separate monthly fee per unit and goes into CM3.
- **Historic prices** come from actual sales, never from list prices (the product master is "current state").
- **Weeks** run Monday–Sunday. A Monday stock count is the stock after Sunday, so week W is
  bracketed by the counts on W and W+7.
- **Launch products are judged like everything else** (decision). The carafe shows red because it loses money.

## 3. Data model

```
dim_product (04)      dim_marketplace (VAT, currency, region)      FX rates (05)
      │                          │                                      │
      ├──────────────┬───────────┴──────────────┬───────────────────────┘
fact_sales_day (01)   fact_ads_day (02)          fact_stock_week (03)
day × mkt × SKU       day × campaign             Monday count × region × SKU
net revenue, costs    spend, net ad sales        available, inbound, value
      └──────────────┬───────────┘                        │ storage cost (split EU pool by units)
                fact_week  ◄──────────────────────────────┘
          week × marketplace × SKU: every additive measure
                     │
          kpis.summarize(any grouping, any window) → all ratio KPIs
```

All KPIs come from **one weekly fact table** through **one function** (`perfdash/kpis.py`), so a
KPI means the same thing in the tiles, the grid, the rules and the tests. `python -m perfdash`
also writes every table to `out/model/*.csv`: the shape the warehouse tables would have.

## 4. KPI definitions

| KPI | Definition |
|---|---|
| Net revenue | Customer price in EUR ÷ (1 + VAT) |
| Landed cost | Units × (purchase + freight & customs) |
| Amazon fees | 15 % commission on the gross price + FBA fee per unit |
| **CM1** | Net revenue − landed cost − Amazon fees |
| Ad spend | Sponsored Products spend in EUR (net) |
| **CM2** (headline) | CM1 − ad spend |
| Storage (est.) | Fee per unit and month × average stock of the week; EU pool split by units sold |
| **CM3** | CM2 − storage |
| CM2 %, CM2/unit | CM2 ÷ net revenue, CM2 ÷ units |
| TACoS | Ad spend ÷ total net revenue |
| ACoS (net) | Ad spend ÷ net ad sales (≈ Amazon console figure × (1 + VAT)) |
| Break-even ACoS | CM1 ÷ net revenue; above it, every ad-driven sale loses money |
| Conversion | Units ÷ sessions |
| Buy box | Session-weighted average of `buy_box_pct` |
| Weeks of cover | Available stock ÷ average units per week of the last 4 weeks, per stock region |
| Reorder time | Lead time (days) ÷ 7 |

**Deliberately left out of the main screens:** impressions, CTR and CPC (ad-console detail; ACoS vs
break-even drives the decision), page views (sessions suffice), reserved stock (not sellable),
daily charts (too noisy for a weekly review) and gross values.

## 5. When is something critical?

Rules run on **fixed windows**, independent of the period selector, so a status doesn't flip when
someone clicks 1W vs 16W. All thresholds are in `perfdash/config.py`.

| Signal | 🔴 Critical | 🟡 Watch |
|---|---|---|
| Stock (per region) | cover < reorder time **and** nothing inbound | cover incl. inbound < reorder time + 2 weeks, or cover > 26 weeks |
| Buy box | < 80 % in **both** of the last 2 weeks | < 90 % last week |
| CM2 | negative over the last 4 weeks | — |
| ACoS (net) | — | > break-even × 1.15, over the 4 weeks **before** the reporting week |
| Conversion | — | −25 % vs own 4-week average (≥ 100 sessions) |
| Net revenue | — | −30 % vs own 4-week average (≥ €300/week) |

**Against false alarms**
- Weekly values, never daily. The coral bottle has 0 sales on 112 days in IT and is simply a slow seller.
- Minimum volumes before anything is judged (sessions, revenue, ad spend).
- **The ad credit window:** ad sales are credited up to 7 days after the click, and the export ran on
  28.09. The last week's ACoS therefore reads too high (46 % → 59 % week on week, purely an
  artefact). Ad status uses the 4 weeks before the reporting week; the page marks the reporting
  week's ACoS with a note.
- Buy box needs two weeks in a row; ACoS needs a 15 % margin over break-even (without it, 13 cells
  went amber for differences of 1–2 points).
- Result: of 32 product × marketplace cells, **8 are critical** (exactly the three actions), 10 are on watch and 14 are OK.

## 6. Data problems found

| Problem | Handling |
|---|---|
| **56 duplicate rows** in sales (IT, 13.–19.07.), which would double that week's revenue | Removed, logged |
| **Lower-case SKUs** in all IT ad campaigns (2,786 rows) | Upper-cased; safe because the ASIN confirms the product on every row |
| **German format** in the stock file: `;`, `13.875,00`, `30.03.2026` | Parsed explicitly; a global `thousands='.'` would also corrupt the dates |
| UK sales and ad spend in **GBP** | Converted with the monthly rate before VAT |
| Ad sales gross, ad spend net | Both brought to net before ratios |
| **List prices are current**, not historic (SPS-2 was €24.99 until 02.08.) | Actual prices from sales |
| Carafe launched 11.05. (DE) / 01.06. (FR, IT, UK) | Not a gap; rows start at launch |
| One unannounced stock receipt (+140 units, carafe EU, count 07.09.) | Logged; all other weeks reconcile (median gap 12 units) |

## 7. Assumptions

- Amazon fees as in the product master: 15 % on gross plus FBA fee in EUR for all marketplaces, UK included.
- Storage cost is an estimate (fee × average stock); the real billing is not in the data.
- Ad sales are Amazon's 7-day attribution and are not added to revenue (they're part of it).
- Cover uses the last 4 weeks' sales rate; seasonality (Q4) would shorten it further.
- Cost of delay for the stock-out assumes an order placed now arrives after the full lead time.

## 8. Open points

- Is an ANT purchase order already placed but not yet visible as "inbound"?
- Who holds the FR buy box for the bread box, and at what price?
- What is the planned launch budget and target ACoS for the carafe, and when does the launch phase end?
- Are the 6,000 inbound carafes still needed at the current sales rate?
- Real storage invoices, to replace the estimate in CM3.

## 9. Production sketch (Azure)

| Concern | Proposal |
|---|---|
| **Ingest** | Daily Azure Data Factory (or Function) pulls the Amazon reports via SP-API (Business Report, Sponsored Products, FBA inventory) into raw tables in the Azure data warehouse; product master from the ERP/controlling export; FX from finance. Raw data kept unchanged for audit. |
| **Data-quality checks** | The checks in `perfdash/load.py` and `model.py` run as a gate after each load: duplicates, SKU/ASIN consistency, FX coverage, landed-cost formula, stock reconciliation. A failed check marks the dashboard "data stale" instead of showing wrong numbers. |
| **Central KPIs** | `fact_week` and the KPI formulas become warehouse views (or a dbt project) so Power BI, this page and ad-hoc analyses use the same definitions. Thresholds live in one config table. |
| **Refresh** | Daily after the Amazon reports are final (~06:00); the weekly review uses the last complete week. Ad KPIs for the last 7 days are flagged as provisional. |
| **Delivery** | Static page or Power BI report from the same views; a short Monday e-mail/Teams post with the three actions and links. |
| **Monitoring** | Job runs and DQ results logged to Application Insights; an alert if the daily load fails or is late. Secrets (SP-API tokens) in Key Vault, accessed via Managed Identity. |

## 10. How AI tools were used

Built with **Claude Code**: data profiling, root-cause checks against the raw files, KPI and
threshold design (agreed step by step), implementation, tests and this README. See
[`CLAUDE.md`](CLAUDE.md) for the agent's working rules and [`PROMPTS.md`](PROMPTS.md) for the key prompts.
