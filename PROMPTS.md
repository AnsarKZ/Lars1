# Key prompts

The prompts from the Claude Code session that shaped this dashboard, in order, with what each
step produced. Quoted as typed, lightly shortened.

## 1. Understand before building
> *"Now let's analyse this case like we did with the previous one, with simplified language for
> better understanding."*

The result: a file-by-file profile of the five sources, plus a plain-language margin walkthrough
for one bottle (gross €29.99 → CM2 €7.49) and the launch carafe in IT (CM2 −€10.74 per unit). It
also sorted the anomalies into data traps (duplicates, lower-case SKUs, German number format,
ad credit window) and real problems (EU stock-out, carafe ads, FR buy box).

## 2. Agree the money rules and KPIs first
> *"Before you build the reporting dashboard, let's agree how we handle the performance values
> (I prefer converting to NET values) and list what KPIs you will include so I can double check."*

The result: the net-EUR conventions (FX first, then VAT; commission on gross; ACoS labelled as net),
the KPI list for management and for marketplace managers, the draft thresholds, and what to
leave out on purpose.

## 3. Decisions
> *"1. Uniform net values everywhere. 2. CM3 with storage, but are you using freight/customs for
> this? 3. Reporting week vs last week, with options for older periods (7D, 1M, 6M, 1Y).
> 4. Judge the launch product like everything else."*

The result:
- Freight & customs sit in landed cost (CM1); storage is the separate fee (CM3). A data-quality
  check verifies landed = purchase + freight for every SKU.
- The period selector became 1W/4W/13W/26W, because 1 year isn't in the data.
- The carafe gets no special treatment.

## 4. Build
The result:
- the `perfdash` package (load → model → central KPIs → rules → actions → page);
- tests;
- a self-contained HTML dashboard;
- this README.

Tuning after the first run:
- ACoS watch needs a 15 % margin over break-even (13 amber cells → 8).
- Actions are ranked by the CM2 cost of one week's delay instead of a fixed horizon.
- Phone-width labels were shortened.
