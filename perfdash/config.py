"""Business rules and thresholds, defined once. Everything else reads from here."""
from __future__ import annotations

from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# Marketplace master data (from 00_Datenbeschreibung.md)
MARKETPLACES = {
    #      VAT    currency  stock region
    "DE": (0.19, "EUR", "EU"),
    "FR": (0.20, "EUR", "EU"),
    "IT": (0.22, "EUR", "EU"),
    "UK": (0.20, "GBP", "UK"),
}

WEEKS_PER_MONTH = 52 / 12          # storage fee is per unit and month
ATTRIBUTION_DAYS = 7               # ad sales are credited up to 7 days after the click

# Comparison periods offered in the dashboard: label -> number of weeks
PERIODS = {"1W": 1, "4W": 4, "13W": 13, "26W": 26}

# ---- status rules ("when does a cell turn red") ----
RULES = {
    # stock
    "cover_watch_buffer_weeks": 2,      # watch if cover incl. inbound < lead time + 2 weeks
    "overstock_weeks": 26,              # watch if more than half a year of stock
    "rate_weeks": 4,                    # sales rate = average of the last 4 weeks
    # buy box
    "buybox_critical": 80.0,            # both of the last 2 weeks below -> critical
    "buybox_watch": 90.0,               # last week below -> watch
    # profit and ads
    "cm2_window_weeks": 4,              # CM2 judged over the last 4 weeks
    "acos_window_weeks": 4,             # ending the week BEFORE the reporting week
    "acos_margin": 1.15,                # amber only if ACoS > break-even x 1.15 (ignore noise)
    # change vs own history
    "cvr_drop": 0.25,                   # conversion -25 % vs own 4-week average
    "revenue_drop": 0.30,               # net revenue -30 % vs own 4-week average
    # minimum volume before anything is judged
    "min_sessions_week": 20,
    "min_sessions_cvr": 100,
    "min_net_revenue_4w": 200.0,
    "min_ad_spend_4w": 50.0,
    "min_revenue_week_avg": 300.0,
}
