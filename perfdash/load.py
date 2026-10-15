"""Read the five sources and clean them. Every fix is recorded as a data-quality
note so the dashboard can show what was changed and why."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from .config import DATA_DIR


@dataclass
class DataQuality:
    notes: list[dict] = field(default_factory=list)

    def add(self, source: str, check: str, status: str, detail: str) -> None:
        # status: ok | fixed | info | warn
        self.notes.append({"source": source, "check": check, "status": status, "detail": detail})


PRODUCT_COLUMNS = {
    "SKU": "sku", "ASIN": "asin", "Produktname": "product", "Produktgruppe": "group",
    "Lebenszyklus": "lifecycle", "Launch-Datum": "launch_date",
    "EK je Einheit (EUR)": "purchase_eur", "Fracht & Zoll je Einheit (EUR)": "freight_eur",
    "Landed Cost je Einheit (EUR)": "landed_eur", "FBA-Gebühr je Einheit (EUR)": "fba_fee_eur",
    "Verkaufsgebühr (% vom Bruttopreis)": "referral_rate",
    "Lagergebühr je Einheit & Monat (EUR)": "storage_eur_month",
    "Wiederbeschaffungszeit (Tage)": "lead_time_days", "Mindestbestellmenge (Stk.)": "moq",
    "Listenpreis brutto (EUR)": "list_price_eur", "Listenpreis brutto (GBP)": "list_price_gbp",
}


def load_products(dq: DataQuality, data_dir: Path = DATA_DIR) -> pd.DataFrame:
    p = pd.read_excel(data_dir / "04_produktstamm_controlling.xlsx", sheet_name="Produktstamm")
    p = p.rename(columns=PRODUCT_COLUMNS)
    off = (p.purchase_eur + p.freight_eur - p.landed_eur).abs() > 0.005
    if off.any():
        dq.add("04 product master", "Landed cost = purchase + freight & customs", "warn",
               f"Mismatch for {', '.join(p.sku[off])}; landed cost used as given.")
    else:
        dq.add("04 product master", "Landed cost = purchase + freight & customs", "ok",
               "Holds for all 8 products, so freight and customs are inside COGS.")
    dq.add("04 product master", "List prices are 'current state' (15.09.)", "info",
           "History uses actual selling prices from file 01, never the list price.")
    return p


def load_sales(dq: DataQuality, data_dir: Path = DATA_DIR) -> pd.DataFrame:
    s = pd.read_csv(data_dir / "01_amazon_sales_traffic_2026.csv")
    dup = s.duplicated()
    if dup.any():
        d = s[dup]
        dq.add("01 sales & traffic", "Exact duplicate rows", "fixed",
               f"{dup.sum()} rows removed ({', '.join(sorted(d.marketplace.unique()))} "
               f"{d.date.min()} to {d.date.max()}); they would double that week's revenue.")
        s = s[~dup]
    clash = s.duplicated(["date", "marketplace", "sku"])
    if clash.any():
        raise ValueError(f"{clash.sum()} conflicting rows for the same day/marketplace/SKU")
    s["date"] = pd.to_datetime(s.date)
    return s.reset_index(drop=True)


def load_ads(dq: DataQuality, products: pd.DataFrame, data_dir: Path = DATA_DIR) -> pd.DataFrame:
    a = pd.read_csv(data_dir / "02_amazon_ads_sponsored_products_2026.csv")
    lower = a.advertised_sku != a.advertised_sku.str.upper()
    a["sku"] = a.advertised_sku.str.upper()
    # Upper-casing is only safe because the ASIN independently confirms the product.
    asin_of = dict(zip(products.sku, products.asin))
    wrong = a.sku.map(asin_of) != a.advertised_asin
    if wrong.any():
        raise ValueError(f"{wrong.sum()} ad rows whose SKU and ASIN disagree")
    if lower.any():
        mps = ", ".join(sorted(a[lower].marketplace.unique()))
        dq.add("02 ads", "SKU spelling", "fixed",
               f"{lower.sum()} rows in {mps} use lower-case SKUs; matched to the product "
               "via upper-case SKU, confirmed by ASIN for every row.")
    a["date"] = pd.to_datetime(a.date)
    return a


def load_stock(dq: DataQuality, data_dir: Path = DATA_DIR) -> pd.DataFrame:
    # German export: ';' separator, '.' thousands, ',' decimals, dd.mm.yyyy dates.
    # Read as text first: a global thousands='.' would also mangle the dates.
    f = pd.read_csv(data_dir / "03_fba_bestand_wochenstichtag.csv", sep=";", dtype=str)
    f = f.rename(columns={"Stichtag": "count_date", "Region": "region", "SKU": "sku",
                          "Verfuegbar": "available", "Reserviert": "reserved",
                          "Eingehend": "inbound", "Bestandswert_EUR": "stock_value_eur"})
    f["count_date"] = pd.to_datetime(f.count_date, format="%d.%m.%Y")
    for c in ("available", "reserved", "inbound"):
        f[c] = f[c].astype(int)
    f["stock_value_eur"] = (f.stock_value_eur.str.replace(".", "", regex=False)
                            .str.replace(",", ".", regex=False).astype(float))
    dq.add("03 FBA stock", "German number and date format", "fixed",
           "Parsed ';' separator, '13.875,00' amounts and 'dd.mm.yyyy' dates explicitly.")
    return f


def load_fx(dq: DataQuality, months: set[str], data_dir: Path = DATA_DIR) -> dict[str, float]:
    fx = pd.read_csv(data_dir / "05_fx_monatskurse.csv")
    rates = dict(zip(fx.month, fx.avg_rate))
    missing = sorted(months - set(rates))
    if missing:
        raise ValueError(f"No GBP/EUR rate for {missing}")
    dq.add("05 FX", "Rate for every month with UK data", "ok",
           f"{len(rates)} monthly rates, {min(rates.values()):.3f}–{max(rates.values()):.3f} EUR per GBP.")
    return rates
