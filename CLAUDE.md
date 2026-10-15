# CLAUDE.md: working rules for this repository

Stock reconciliation prototype (warehouse ↔ Amazon DE/FR/IT/UK, Shopify). See README.md for the domain.

## Commands
- Run the replay: `PYTHONPATH=src python -m stockrecon` (options: `--pause`, `--until`, `--min-severity`)
- Tests: `python -m pytest` (includes a full-week replay that pins the expected incidents)

## Domain rules you must not break
- **Time:** files 01/02 are Vienna local time, everything else UTC. Convert once, in the data
  source, with `Europe/Vienna` (never a fixed offset). Inside the engine everything is UTC.
- **No look-ahead:** the engine may only use data with a timestamp ≤ the current round. Processing
  results become visible at `verarbeitet_utc`, not at push time.
- **Target** = `clamp(stock − buffer, 0, max_qty)` per file 07, minus own-channel orders since the push.
- **HTTP 202 is not success** for Amazon; the result is in file 04. Shopify (200) is synchronous.
- **SKU matching is exact** on (channel, channel_sku) via file 06. Never case-fold or fuzzy-match;
  unknown listings must surface as `UNMAPPED_LISTING`.
- **FBA rows are out of scope**; a `TIMEOUT` readback means *unknown*, not 0.
- **Root cause before symptoms:** a new check must say which existing alerts explain it (see
  `run_all` in `checks.py`) so one incident produces one alert.

## Code conventions
- The engine depends only on the `DataSource` protocol (`sources/base.py`). Source-specific
  cleaning (dedupe, parsing, time zones) stays in the source.
- Thresholds, routing and channel behaviour live in `config.py`, not in checks.
- Checks return `Finding`s and `holds`; they never send notifications themselves.
- Every new alert type needs a test. If replay numbers change, update `tests/test_replay.py` and
  the README tables together, after verifying against the raw CSVs.
- Alert texts are for business users: say what is wrong, since when, the likely cause and who should act.
