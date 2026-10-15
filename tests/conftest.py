from pathlib import Path

import pytest

DATA = Path(__file__).resolve().parent.parent / "data"
REQUIRED = [f"0{i}_{n}.csv" for i, n in enumerate(
    ["lagerbestand", "bestellungen", "push_protokoll", "verarbeitungsstatus",
     "kanalbestand_abfragen", "sku_zuordnung", "kanalregeln"], start=1)]


def pytest_collection_modifyitems(config, items):
    missing = [f for f in REQUIRED if not (DATA / f).exists()]
    if missing:
        skip = pytest.mark.skip(reason=f"case data not in data/ (missing {', '.join(missing)})")
        for item in items:
            item.add_marker(skip)
