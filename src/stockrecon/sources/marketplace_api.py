"""Production data source (skeleton, not implemented in the prototype).

Shows how the CSV replay is swapped for live systems without touching the
engine. Each method maps to a concrete upstream call:

* stock         -> Azure Data Warehouse (SQL view of free stock per SKU)
* orders        -> order management system / data warehouse
* pushes        -> the push job's own log table (it already writes file 03)
* processing    -> Amazon SP-API: Feeds/Listings submission status;
                   Shopify: synchronous, taken from the push response
* readbacks     -> Amazon SP-API Listings Items (fulfillment_availability,
                   status) per marketplace; Shopify Admin API inventory levels
* master data   -> ERP/PIM export (mapping, prices) and channel rule table

Credentials are never read from code or files: the job runs with an Azure
Managed Identity that may read the secrets from Azure Key Vault (Amazon LWA
refresh token, Shopify admin token). See README, "Production".
"""
from __future__ import annotations

from datetime import datetime

from ..models import Batch, MasterData


class MarketplaceApiSource:
    def __init__(self, key_vault_url: str, warehouse_dsn: str):
        self.key_vault_url = key_vault_url
        self.warehouse_dsn = warehouse_dsn

    def master_data(self) -> MasterData:
        raise NotImplementedError("Read mapping and channel rules from ERP/PIM.")

    def fetch(self, start: datetime, end: datetime) -> Batch:
        raise NotImplementedError(
            "Query warehouse, push log and marketplace APIs for (start, end].")
