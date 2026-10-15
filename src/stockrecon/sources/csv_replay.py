"""Replays the case data package as if it arrived live.

Responsibilities that belong here (and nowhere else):
* convert local Vienna timestamps (files 01, 02) to UTC,
* parse empty cells into None,
* drop exact duplicate readback rows and report them as data-quality notes,
* hand out only the rows whose timestamp falls into the requested window.
"""
from __future__ import annotations

import bisect
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from ..models import (Batch, ChannelRule, DataQualityNote, Listing, MasterData,
                      Order, ProcessingResult, PushAttempt, Readback, StockLevel)

LOCAL_TZ = "Europe/Vienna"


def _local_to_utc(series: pd.Series) -> pd.Series:
    # A real zone, not a fixed +2h: the same code must survive the switch to
    # winter time. 'raise' makes ambiguous DST timestamps fail loudly.
    return (pd.to_datetime(series)
            .dt.tz_localize(LOCAL_TZ, ambiguous="raise", nonexistent="raise")
            .dt.tz_convert("UTC"))


def _utc(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, utc=True)


def _none(value):
    return None if pd.isna(value) else value


class _Timeline:
    """Records sorted by timestamp with O(log n) window lookup."""

    def __init__(self, records: list, key=lambda r: r.ts):
        self.records = sorted(records, key=key)
        self.stamps = [key(r) for r in self.records]

    def window(self, start: datetime, end: datetime) -> list:
        lo = bisect.bisect_right(self.stamps, start)
        hi = bisect.bisect_right(self.stamps, end)
        return self.records[lo:hi]


class CsvReplaySource:
    def __init__(self, data_dir: str | Path = "data"):
        d = Path(data_dir)
        read = lambda name: pd.read_csv(d / name, encoding="utf-8", dtype=str)

        stock = read("01_lagerbestand.csv")
        stock["ts"] = _local_to_utc(stock.zeitpunkt)
        self._stock = _Timeline([
            StockLevel(r.ts.to_pydatetime(), r.sku, int(r.verfuegbar))
            for r in stock.itertuples()])

        orders = read("02_bestellungen.csv")
        orders["ts"] = _local_to_utc(orders.bestellzeit)
        self._orders = _Timeline([
            Order(r.ts.to_pydatetime(), r.kanal, r.kanal_sku, int(r.menge), r.bestell_id)
            for r in orders.itertuples()])

        pushes = read("03_push_protokoll.csv")
        pushes["ts"] = _utc(pushes.gesendet_utc)
        self._pushes = _Timeline([
            PushAttempt(r.push_lauf_id, r.ts.to_pydatetime(), r.kanal, r.kanal_sku,
                        int(r.menge_gesendet), int(r.versuch), int(r.http_status),
                        r.antwort, _none(r.submission_id))
            for r in pushes.itertuples()])

        proc = read("04_verarbeitungsstatus.csv")
        proc["ts"] = _utc(proc.verarbeitet_utc)
        self._processing = _Timeline([
            ProcessingResult(r.submission_id, r.kanal, r.kanal_sku, r.ts.to_pydatetime(),
                             r.ergebnis == "SUCCESS", _none(r.meldung))
            for r in proc.itertuples()])

        reads = read("05_kanalbestand_abfragen.csv")
        dup_mask = reads.duplicated(keep="first")
        reads["ts"] = _utc(reads.abgefragt_utc)
        dups = reads[dup_mask].groupby("ts").size()
        self._quality = _Timeline([
            DataQualityNote(ts.to_pydatetime(), "readback",
                            f"{n} exact duplicate readback rows dropped")
            for ts, n in dups.items()])
        reads = reads[~dup_mask]
        self._readbacks = _Timeline([
            Readback(r.ts.to_pydatetime(), r.kanal, r.kanal_sku, r.fulfillment,
                     None if pd.isna(r.menge_angezeigt) else int(float(r.menge_angezeigt)),
                     _none(r.listing_status), r.abfrage_status)
            for r in reads.itertuples()])

        mapping = read("06_sku_zuordnung.csv")
        rules = read("07_kanalregeln.csv")
        self._master = MasterData(
            listings=[Listing(r.sku, r.produkt, float(r.vk_brutto_eur), r.kanal, r.kanal_sku)
                      for r in mapping.itertuples()],
            rules={r.kanal: ChannelRule(r.kanal, int(r.puffer_stk),
                                        None if pd.isna(r.max_menge) else int(r.max_menge))
                   for r in rules.itertuples()})

    # ------------------------------------------------------------ interface

    def master_data(self) -> MasterData:
        return self._master

    def fetch(self, start: datetime, end: datetime) -> Batch:
        return Batch(
            stock=self._stock.window(start, end),
            orders=self._orders.window(start, end),
            pushes=self._pushes.window(start, end),
            processing=self._processing.window(start, end),
            readbacks=self._readbacks.window(start, end),
            quality=self._quality.window(start, end),
        )

    # ------------------------------------------------------- replay helpers

    def time_bounds(self) -> tuple[datetime, datetime]:
        """(first data timestamp, last data timestamp) for the replay clock."""
        first = min(self._stock.stamps[0], self._pushes.stamps[0])
        last = max(self._readbacks.stamps[-1], self._processing.stamps[-1])
        return first - timedelta(seconds=1), last
