"""The data-source contract.

The engine only ever talks to this interface. The CSV replay implements it
today; a production implementation would call the marketplace APIs and the
data warehouse instead (see marketplace_api.py).
"""
from __future__ import annotations

from datetime import datetime
from typing import Protocol

from ..models import Batch, MasterData


class DataSource(Protocol):
    def master_data(self) -> MasterData:
        """SKU mapping, prices and channel rules."""
        ...

    def fetch(self, start: datetime, end: datetime) -> Batch:
        """All events that became visible in the half-open window (start, end].

        "Visible" means: a live system could have known it at `end`. For
        processing results that is the processing time, not the push time.
        """
        ...
