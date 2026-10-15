# Stock reconciliation: warehouse ↔ sales channels

A prototype that checks every 30 minutes whether each sales channel (Amazon DE/FR/IT/UK, Shopify)
shows the stock it should, and raises alerts when it doesn't. It replays the case data package
run by run in time order, as if the data were arriving live.

```bash
pip install pandas pytest          # Python ≥ 3.11
python -m stockrecon               # needs PYTHONPATH=src, or: pip install -e .
python -m stockrecon --pause 0.05  # slower, for the live demo
python -m stockrecon --until 2026-09-25T12:00 --min-severity INFO
python -m pytest                   # 13 tests, incl. a full-week replay
```

Output: alerts on the console, plus `out/alerts.jsonl` (every alert event), `out/rounds.jsonl`
(one structured log line per round) and `out/summary.md` (alert table + days of cover).

---

## 1. The three most important problems

| | **1 · Amazon DE rejects every stock update for LN-IF750-ANT** | **2 · Amazon IT listing LN-SPM-SET inactive** | **3 · Amazon FR rejects every stock update for LN-BK-BAM-L** |
|---|---|---|---|
| **When** | From **25.09. 10:08 UTC** (12:08 Vienna), push run L00169, until the end of the data | From **25.09. 07:15 UTC** (09:15 Vienna) until the end | From **24.09. 06:03 UTC** (08:03 Vienna), push run L00113, until the end |
| **Cause** | Asynchronous rejection in file 04: *"Attribut fulfillment_availability: Wert für lead_time_to_ship_max_days ungültig"*. The quantity is fine: 47 units were sent both right before (S0006681 → SUCCESS) and right after (S0006721 → ERROR) the switch. So the **handling time** sent in the same object became invalid, probably after a master-data or listing change for this offer on DE only (FR/IT/UK unaffected). The HTTP answer stayed `202 ACCEPTED`, so file 03 looks healthy. | Listing switched to INACTIVE while pushes keep succeeding. The reason is not in the data (Seller Central: suppression, compliance, manual?). | Rejection *"Pflichtattribut item_package_weight fehlt für Produkttyp BREAD_BOX"*. Only FR is affected; the same product works on DE, IT and UK. So it's an FR-specific master-data or template gap. |
| **Impact** | DE froze at its old value and only deducted its own orders (31 more units sold on DE). The warehouse hit **0 on 27.09. 16:30 UTC** and went **negative from 17:30 UTC**, ending at **−13** while DE still showed **16**. That's about **13 orders (~€450) that can't be fulfilled**, plus cancellation-rate damage on the Amazon account. | Shows 0 instead of ~60 for 3.5 days. IT sold ~1.8 sets/day before, then none: **~€50/day of lost sales**, open-ended. | FR stuck at 19–20 while the target dropped to 11. FR shows **more than the warehouse holds** (19 vs 13 at the end). Only 1 FR order so far, so no damage yet, but a slow-moving item is drifting towards overselling. |
| **Action** | *Now:* correct the handling time for this offer on Amazon DE (find the change in the PIM/Seller Central history), resend the stock, handle the ~13 unfulfillable orders. *Prevent:* alert on file-04 rejections (built), validate the payload before sending, optionally send quantity-only updates. | *Now:* check in Seller Central why the listing is inactive and reactivate it. *Prevent:* "inactive although in stock" alert (built). | *Now:* add the package weight for FR and resend. *Prevent:* rejection alert routed to Content/PIM (built); required-attribute check before sending. |
| **Prototype alert** | `LISTING_REJECTED` at **25.09. 10:50 UTC**, 42 min after the first rejection and **2.5 days before the first unit was oversold**. `SHOWN_TOO_HIGH` at 14:20 UTC, escalated to CRITICAL on 26.09. 12:20 UTC; `STOCK_NEGATIVE` at 27.09. 17:50 UTC. | `LISTING_INACTIVE` at **25.09. 07:50 UTC** | `LISTING_REJECTED` at **24.09. 06:50 UTC**, `SHOWN_TOO_HIGH` at 26.09. 08:20 UTC |

Why these three: problem 1 is the only one with real customer damage. Problem 2 loses money
silently and indefinitely. Problem 3 is the earliest signal in the data and is heading the same way
as problem 1. The two infrastructure incidents below were short and cheap this week; they matter
because of what they say about monitoring, not because of their impact.

## 2. Further findings

**Infrastructure**
- **Amazon UK access token expired:** 28.09. 06:00–10:30 UTC (runs L00294–L00303). 80 pushes got
  `403 Unauthorized`, **without retry**. UK received no updates for 4.5 h (impact: 1 UK order in that window).
  Alert `CHANNEL_PUSH_FAILING` at 06:20 UTC: **one** channel alert instead of 80 SKU alerts.
- **Push job did not run:** 26.09. 23:00 – 27.09. 04:00 UTC, 11 runs missing; the readback job kept
  running. Alert `PUSH_JOB_DOWN` at 23:50 UTC. Impact was small (4 night orders absorbed by buffers).

**Data quality** (handled, not alerted as stock errors)

| Finding | Handling |
|---|---|
| `LN-TB-350-ALT` on AMZ-DE: a listing missing from the SKU mapping. 7 orders on 22.09. that were **never deducted from warehouse stock** (TB-350's stock decline matches only the mapped orders), then INACTIVE. | `UNMAPPED_LISTING` alert in the first round, to master data |
| 540 exact duplicate readback rows (25.09. 10:15–15:45 UTC) | Dropped on ingest, INFO alert for the digest |
| Shopify readback `TIMEOUT` (26.09. 03:15–04:15 UTC), quantity empty | Treated as *unknown*, not 0. Checks hold; `READBACK_FAILED` warning |
| GK-18 shows 0 once on AMZ-DE and AMZ-IT (23.09. 12:45 / 13:15 UTC), right after a restock at 12:30 UTC | One-off; filtered by persistence, no alert |
| Channel SKUs differ: Shopify lowercase, UK codes `LNBKBAML-UK` / `LN-KMSET-UK`, FBA `-FBA` | Exact join on (channel, channel SKU) via file 06. **No case-folding**, because guessing would have hidden `-ALT` |
| FBA offers (`AMAZON_EU/UK`) in readbacks | Excluded: Amazon's stock, never pushed by us |
| Files 01/02 in Vienna local time, 03–05 in UTC | Converted with the `Europe/Vienna` zone (not a fixed +2h; DST ends 25.10.2026) |
| 118 × `429 QuotaExceeded` | All retried successfully, so no alert by design |
| ~19 % of Amazon submissions are processed *after* the readback 15 min later (max 55 min) | The readback is not judged until our latest push is processed |
| Push rule check: all 13,118 sent quantities equal `clamp(stock − buffer, 0, max)` | Push calculation is correct; the problems are downstream |

## 3. Definitions: target (Soll), actual (Ist), deviation

- **Target (Soll):** what a channel should display =
  `min(max(warehouse_available − buffer, 0), max_qty)` (file 07), using the warehouse stock of the
  push slot, **minus the channel's own orders between the push and the readback** (channels deduct
  orders themselves).
- **Actual (Ist):** `menge_angezeigt` from the readback (file 05), only for own-shipped offers
  (`fulfillment = DEFAULT`), only if the query succeeded.
- **Deviation:** `actual − target`. Positive = channel promises too much (**oversell risk**).
  Negative = channel hides stock (**lost sales**).

**Not every deviation is an error.** A readback is *not judged* (held) when:
- our latest push for that listing has not been processed yet by readback time (Amazon async);
- the query failed (TIMEOUT), since unknown ≠ 0;
- the offer is FBA.

A judged deviation of ±2 units is treated as timing noise.

Beyond comparing numbers, the robot checks the **process** that produces them. That's where the
causes become visible:

```
① push job alive?  → ② push delivered?  → ③ push accepted (file 04)?  → ④ listing buyable?  → ⑤ shown = target?
   heartbeat          final HTTP attempt     SUCCESS / ERROR / pending     ACTIVE vs INACTIVE     deviation
```

## 4. Alert rules and thresholds

| Alert | Rule | Severity | Persistence | Team |
|---|---|---|---|---|
| `PUSH_JOB_DOWN` | no push for > 65 min (2 runs) | CRITICAL | 1 | IT / Data |
| `PUSH_RUN_INCOMPLETE` | run covers fewer than all 40 listings | HIGH | 1 | IT / Data |
| `CHANNEL_PUSH_FAILING` | final attempt failed for ≥ 3 listings of one channel | CRITICAL if 401/403, else HIGH | 1 if auth, else 2 | IT / Data |
| `PUSH_FAILED` | final attempt failed (any code; a successful 429 retry is silent) | HIGH | 2 (1 if auth) | IT / Data |
| `LISTING_REJECTED` | ≥ 2 consecutive ERRORs in file 04 | HIGH | 1 | by message: *missing attribute* → Content/PIM, *invalid value* → Marketplace mgmt, else IT |
| `PROCESSING_OVERDUE` | Amazon submission without result > 60 min | WARNING | 1 | IT / Data |
| `STALE_LISTING` | no successful update for > 2 h and **no other alert explains it** | WARNING | 1 | IT / Data |
| `LISTING_INACTIVE` | INACTIVE while target > 0 | WARNING | 2 | Marketplace mgmt |
| `SHOWN_TOO_HIGH` | deviation > +2 | HIGH; CRITICAL if warehouse ≤ 0, or channel shows more than exists **and** stock < 1 day of sales | 3 (1 if critical) | Marketplace mgmt |
| `SHOWN_TOO_LOW` | deviation < −2 | WARNING | 3 | Marketplace mgmt |
| `STOCK_NEGATIVE` | warehouse available < 0 | CRITICAL | 1 | Operations / Customer service |
| `UNMAPPED_LISTING` | listing in readbacks/orders but not in mapping | WARNING | 1 | Master data |
| `READBACK_FAILED` / `READBACK_JOB_DOWN` / `READBACK_MISSING` | readback errors / no data / mapped listing missing | WARNING / HIGH / INFO | 2 | IT / Master data |

**Why these numbers**
- **±2 units:** typical noise is 1–2 units (orders between push and readback, Amazon lag). 2 also equals
  the Amazon buffer: a bigger gap means the buffer is used up.
- **3 rounds (1.5 h):** long enough to absorb late processing (max 55 min) and one-off glitches (GK-18),
  short enough to beat damage by days.
- **2 rejections:** one rejection can be a hiccup; two in a row with the same message is a pattern.
- **65 min heartbeat:** one late or missed run is tolerated; two is an outage.
- **Direction matters:** overselling causes cancellations and Amazon account penalties, so it's
  HIGH/CRITICAL. Hiding stock "only" loses sales, so it's WARNING. Price (`vk_brutto_eur`) gives € at risk.

**Notification routes:** CRITICAL → on-call phone + Teams + e-mail · HIGH → Teams + e-mail ·
WARNING → Teams · INFO → daily digest (08:00 Vienna, also lists SKUs with < 2 days of cover).

**Against false alarms and floods**
1. **Lifecycle per problem:** NEW → (WORSE) → (STILL reminder: CRITICAL every 4 h, HIGH every 24 h) → FIXED.
   It isn't re-sent every 30 minutes.
2. **Root cause first:** channel-wide failures become one channel alert, and staleness is only
   reported if nothing else explains it.
3. **Holds:** "can't judge right now" neither confirms nor resolves an alert.
4. **Resolution needs 2 clean rounds**, so alerts don't flap.

Result for the week: **11 alerts**: 8 for the incidents above, 1 unmapped listing, and 2 short
data-quality notices (duplicate rows, Shopify timeouts). No false lost-sales alarms, and no alert
for the 118 retried 429s.

## 5. Architecture

```
src/stockrecon/
  sources/base.py          DataSource protocol: master_data(), fetch(start, end] → Batch
  sources/csv_replay.py    replays the CSVs (UTC conversion, dedupe, windowing; no look-ahead)
  sources/marketplace_api.py  production skeleton (SP-API, Shopify Admin API, warehouse)
  state.py                 rolling knowledge built only from data already seen
  checks.py                the five questions + catalog drift + data quality
  alerting.py              findings → alerts (persistence, holds, escalation, resolve)
  notify.py                console / JSONL sinks (Teams, mail, pager go here)
  report.py                daily digest, end-of-run summary, days of cover
  engine.py                the 30-minute loop (runs at :20/:50, after the readback at :15/:45)
  config.py                all thresholds, channel profiles, routing
```

**Swapping the data source:** the engine depends only on `DataSource`. A live implementation returns
the same records from the APIs for the window `(last_run, now]`. Channel differences (Amazon async,
Shopify sync) live in `ChannelProfile`, so adding Otto or Zalando is configuration, not code.

## 6. Production sketch (Azure)

| Concern | Proposal |
|---|---|
| **Scheduling** | Azure Container Apps **Job** (or Function, timer trigger) with cron `20,50 * * * *`. One container image, same code as the prototype. |
| **Data** | `MarketplaceApiSource`: warehouse via SQL view in the Azure data warehouse; push log from the push job's table; Amazon SP-API (listing status, `fulfillment_availability`, feed/submission results); Shopify Admin API (inventory levels). |
| **State** | Alert tracks and per-listing state persisted between runs (Azure Table Storage or a small SQL table) instead of in memory. Runs are idempotent per round. |
| **Credentials** | No secrets in code, config or repo. The job uses a **Managed Identity** with read access to **Azure Key Vault** (Amazon LWA refresh token, Shopify token, Teams webhook). Proactive check: alert 24 h before a token or secret expires. |
| **Logging** | Structured JSON per round (`rounds.jsonl` in the prototype) → Application Insights / Log Analytics. Every alert event also stored, for audit and for tuning thresholds. |
| **Monitoring the job itself** | Dead man's switch: each run writes a heartbeat; an **Azure Monitor alert** fires if there's no successful run for 45 min, or if a run fails or exceeds its duration. The robot can't report its own death, so something outside it has to. |
| **Notifications** | Teams webhook per team channel, e-mail, on-call pager for CRITICAL (e.g. Opsgenie/PagerDuty). Quiet hours for WARNING. |
| **Delivery** | GitHub Actions: tests (incl. full-week replay as a regression test) → build image → deploy. Threshold changes via `config.py` with review. |

## 7. Assumptions

- The warehouse value of slot *t* is what the push at *t* used (confirmed: all 13,118 pushes match the rule).
- Channel order deduction is immediate; orders between push and readback explain lower readbacks.
- The case is only about own-shipped stock; FBA is out of scope.
- Problem 1's root cause (a changed handling-time value on the DE offer) is inferred, since the push
  payload is not in the data. The same applies to the cause of the IT deactivation.
- Teams and on-call routes are placeholders; the real channels and owners need confirming.

## 8. Open points and what was left out

- **Not built:** real API adapters and notifier integrations (only skeleton/console), persistent
  state store, 429 rate trend alert, proactive token-expiry check, payload validation in the push
  job. These are described above but out of the 4–5 h scope.
- **Questions for the business** (drafted as an e-mail): push payloads and change history for problem 1,
  reason for the IT deactivation, why FR lacks the weight, token renewal process (why no retry on 403?),
  cause of the push outage, whether the 7 `-ALT` orders were shipped.
- **Tuning:** thresholds are set from one week of data. In production they should be reviewed after
  a few weeks of alert history (false positive rate per alert type).
- **Recommendations beyond monitoring:** quantity-only stock updates (so a bad attribute can't block
  stock), retry with token refresh on 401/403, dynamic buffers for bestsellers or low stock.

## 9. How AI tools were used

Built with **Claude Code**: data profiling, root-cause analysis, design discussion (what to ignore,
which thresholds, how to avoid floods), implementation and tests. The working rules for the agent
are in [`CLAUDE.md`](CLAUDE.md), and the key prompts in [`PROMPTS.md`](PROMPTS.md). All findings were
verified against the raw CSVs with independent pandas queries before going into this README.
