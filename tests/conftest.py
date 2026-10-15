from pathlib import Path

import pytest

DATA = Path(__file__).resolve().parent.parent / "data"
REQUIRED = ["01_amazon_sales_traffic_2026.csv", "02_amazon_ads_sponsored_products_2026.csv",
            "03_fba_bestand_wochenstichtag.csv", "04_produktstamm_controlling.xlsx", "05_fx_monatskurse.csv"]


def pytest_collection_modifyitems(config, items):
    missing = [f for f in REQUIRED if not (DATA / f).exists()]
    if missing:
        skip = pytest.mark.skip(reason=f"case data not in data/ (missing {', '.join(missing)})")
        for item in items:
            item.add_marker(skip)
