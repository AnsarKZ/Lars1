"""Command line entry point: python -m stockrecon [options]"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from .config import Settings
from .engine import Engine
from .models import Severity
from .notify import ConsoleNotifier, FanOut, JsonlNotifier
from .report import summary_markdown
from .sources.csv_replay import CsvReplaySource


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Replay the stock data run by run and raise alerts.")
    p.add_argument("--data", default="data", help="folder with the case CSV files")
    p.add_argument("--out", default="out", help="folder for alerts.jsonl, rounds.jsonl, summary.md")
    p.add_argument("--pause", type=float, default=0.0,
                   help="seconds to wait between rounds (e.g. 0.05 for a live demo)")
    p.add_argument("--until", help="stop after this UTC time, e.g. 2026-09-25T12:00")
    p.add_argument("--min-severity", default="WARNING", choices=[s.name for s in Severity],
                   help="lowest severity printed to the console (all go to alerts.jsonl)")
    args = p.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    out = Path(args.out)
    source = CsvReplaySource(args.data)
    first, last = source.time_bounds()
    until = (datetime.fromisoformat(args.until).replace(tzinfo=timezone.utc)
             if args.until else None)

    notifier = FanOut(ConsoleNotifier(Severity[args.min_severity]),
                      JsonlNotifier(out / "alerts.jsonl"))
    engine = Engine(source, Settings(), notifier, run_log=out / "rounds.jsonl", pause_s=args.pause)
    result = engine.run(first, last, until)

    summary = summary_markdown(result, source.master_data(), until or last)
    (out / "summary.md").write_text(summary, encoding="utf-8")
    print("\n" + summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
