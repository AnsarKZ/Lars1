# Key prompts

The most important prompts from the Claude Code session that produced this repository, in order,
with what each step contributed. Prompts are quoted as typed (lightly shortened).

## 1. Framing the task
> *"Here is the task [case PDF]. Where do we start and what can be the possible pitfalls?"*

The result: a reading of the briefing, a work plan (profile the data before building), and a
first list of pitfalls (async processing, FBA, time zones, alert floods, look-ahead in the replay).

## 2. Understanding the data before solving
> *"Before we get into solving the case, can we go file by file and do basic analysis on the
> contents: what stands out, what the fields mean and what is it used for?"*

The result: a profile per file (row counts, gaps, duplicates, value distributions) and how the
files join (`submission_id`, SKU mapping). This surfaced the missing push runs, the duplicate
readbacks, the unmapped `-ALT` listing and the two rejection streams in file 04.

## 3. Making the mechanics understandable
> *"I'm still confused with how the logic works with regards to push and responses, what are
> buffers used for and why they are set at the level they are set. Use simple language, ELI5 style."*

> *"Can you do the confirmed facts section in the same manner?"*

The result: plain-language explanations of 200 vs 202 vs 429 vs 403, asynchronous processing, and
why buffers exist (Amazon 2 = slow and shared across 4 marketplaces; Shopify 0 + cap 50). These
became the "not every deviation is an error" rules.

## 4. Root cause, not just symptoms
> *"With problem number 1, what does the error 'lead_time_to_ship_max_days ungültig' mean, where
> do the values come from?"*

> *"Let's say this is a master data issue. Where would the master data come from, who would have
> control over editing it?"*

The result: the insight that the quantity was correct (47 before and after) and the *handling-time*
field in the same payload sank it. This led to routing alerts by error message to the team that can
fix them (Content/PIM vs. Marketplace management vs. IT).

## 5. Designing the monitoring
> *"In the 'what the monitoring will do' section, add the two infrastructure problems in addition
> to the main 3, and include possible solutions for the monitoring robot (30 min interval)."*

The result: the five questions in root-cause order (alive → delivered → accepted → buyable →
truthful), the heartbeat and dead man's switch, and channel-level grouping for the expired UK token.

## 6. Asking for missing information
> *"There is a chance to ask for additional info like log data, so draft an email in German where
> we ask for additional input regarding problem 1, the missing weight in problem 3, and the reason
> for the inactive listing in problem 2. And other issues where logs are useful."*

The result: a prioritised question list (payloads by submission ID, change history, scheduler logs),
which is mirrored in README "Open points".

## 7. Challenging the design
> *"Does the robot fit the case requirements in the PDF? And here are my suggestions, tell me if
> they are good ideas: (1) alert if 429 and versuch > 2, (2) low stock prevention, (3) push not sent,
> (4) ignore capitalisation of SKUs, (5) UTC uniformity, (6) Amazon-specific alerts, (7) a visible
> list of all SKUs showing newly added or removed ones."*

The result:
- **(1)** became "alert on the *final* failed attempt, whatever the code" (`versuch` never exceeds 2).
- **(2)** became days of cover in the digest and stock-aware severity.
- **(4)** was rejected in favour of exact mapping plus an `UNMAPPED_LISTING` alert, because
  case-folding would have hidden the `-ALT` listing.
- **(5)** was refined to the `Europe/Vienna` zone instead of a fixed +2h.
- **(6)** became channel profiles in config.
- **(7)** became the catalog drift check.

## 8. Build
> *"Yes, let's build."*

The result: the `stockrecon` package, tests (including the full-week replay pinned to the expected
incidents), README, and this file. Thresholds were tuned against the replay. Two first-run issues
were fixed: CRITICAL fired too early, and a burst of stale warnings appeared after the push-job
recovery.
