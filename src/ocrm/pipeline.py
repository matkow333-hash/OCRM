"""Przebieg skanera: adapter -> normalize -> classify -> dedup -> zapis do SQLite.

Zwraca ScanResult (znalezione / nowe / strony / status) i zapisuje przebieg w scan_log.
Flaga sprzedawcy z portalu wchodzi do classify jako jeden z sygnałów, nie jako werdykt.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from . import classify, db, dedup
from .adapters import get_adapter
from .adapters.base import Blocked
from .config import Config
from .models import RawListing
from .normalize import fold, normalize_listing, utc_now

PRIVATE_LABELS = ("osoba prywatna", "prywatne", "private", "wlasciciel", "properta")
AGENCY_LABELS = ("firma", "business", "biuro", "deweloper", "agencja")


@dataclass
class ScanResult:
    source: str
    status: str
    found: int = 0
    new: int = 0
    pages: int = 0
    detail: str | None = None


def seller_type_from_label(label: str | None) -> tuple[str, float]:
    if not label:
        return "unknown", 0.0
    key = fold(label)
    if any(marker in key for marker in AGENCY_LABELS):
        return "agency", 1.0
    if any(marker in key for marker in PRIVATE_LABELS):
        return "private", 0.0
    return "unknown", 0.0


def in_scope(city: str | None, district: str | None, cfg: Config) -> bool:
    if city is not None:
        allowed_cities = {fold(c) for c in cfg.area.cities}
        if fold(city) not in allowed_cities:
            return False
    if cfg.area.districts and district is not None:
        allowed = {fold(d) for d in cfg.area.districts}
        if fold(district) not in allowed:
            return False
    return True


def scan_source(conn: sqlite3.Connection, cfg: Config, source: str) -> ScanResult:
    cooldown = db.blocked_until(conn, source, cfg.scan.block_cooldown_minutes)
    if cooldown:
        return ScanResult(source=source, status="cooldown", detail=f"karencja do {cooldown}")

    adapter = get_adapter(source)
    scan_id = db.start_scan(conn, source)
    search_cfg = cfg.search_config()
    found = 0
    new = 0
    stamp = utc_now()
    try:
        for raw in adapter.search(search_cfg):
            found += 1
            if not _store(conn, cfg, raw, stamp):
                continue
            new += 1
    except Blocked as exc:
        pages = _pages_fetched(adapter)
        db.finish_scan(conn, scan_id, "blocked", pages=pages, found=found, new=new, detail=str(exc))
        return ScanResult(
            source=source, status="blocked", found=found, new=new, pages=pages, detail=str(exc)
        )
    except Exception as exc:
        pages = _pages_fetched(adapter)
        db.finish_scan(conn, scan_id, "error", pages=pages, found=found, new=new, detail=repr(exc))
        return ScanResult(
            source=source, status="error", found=found, new=new, pages=pages, detail=repr(exc)
        )

    pages = _pages_fetched(adapter)
    detail = None
    if found == 0 and db.consecutive_empty_scans(conn, source, limit=1) >= 1:
        detail = "drugi przebieg z rzędu bez wyników - sprawdź parser"
    db.finish_scan(conn, scan_id, "ok", pages=pages, found=found, new=new, detail=detail)
    return ScanResult(source=source, status="ok", found=found, new=new, pages=pages, detail=detail)


def _pages_fetched(adapter) -> int:
    return int(getattr(adapter, "pages_fetched", 0))


def _store(conn: sqlite3.Connection, cfg: Config, raw: RawListing, stamp: str) -> bool:
    listing = normalize_listing(raw, seen_at=stamp)
    if not in_scope(listing.city, listing.district, cfg):
        return False
    listing.seller_type, listing.agency_score = seller_type_from_label(raw.seller_label)
    listing.content_hash = dedup.content_hash(listing.description)
    context = classify.phone_context(conn, listing.phone_e164)
    classify.classify(listing, cfg.classify, context)
    listing.dedup_group = dedup.assign_group(conn, listing)
    _, is_new = db.upsert_listing(conn, listing)
    return is_new


def scan_all(conn: sqlite3.Connection, cfg: Config, sources: list[str] | None = None) -> list[ScanResult]:
    targets = sources or cfg.scan.sources
    return [scan_source(conn, cfg, source) for source in targets]
