"""Warstwa SQLite: schema, idempotentna migracja, połączenie, zapis ogłoszeń i logu skanów.

Zwraca połączenia sqlite3 z row_factory=sqlite3.Row. init_db() można wołać wielokrotnie.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .models import Listing
from .normalize import utc_now

SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
  id                INTEGER PRIMARY KEY,
  source            TEXT NOT NULL,
  source_id         TEXT NOT NULL,
  url               TEXT NOT NULL,
  deal_type         TEXT NOT NULL,
  city              TEXT,
  district          TEXT,
  street            TEXT,
  price             INTEGER,
  area_m2           REAL,
  rooms             INTEGER,
  floor             INTEGER,
  title             TEXT,
  description       TEXT,
  content_hash      TEXT,
  phone_e164        TEXT,
  seller_type       TEXT NOT NULL DEFAULT 'unknown',
  agency_score      REAL NOT NULL DEFAULT 0.0,
  dedup_group       TEXT,
  first_seen_at     TEXT NOT NULL,
  last_seen_at      TEXT NOT NULL,
  is_active         INTEGER NOT NULL DEFAULT 1,
  UNIQUE (source, source_id)
);

CREATE TABLE IF NOT EXISTS contacts (
  id                INTEGER PRIMARY KEY,
  phone_e164        TEXT NOT NULL UNIQUE,
  name              TEXT,
  do_not_call       INTEGER NOT NULL DEFAULT 0,
  do_not_call_at    TEXT,
  note              TEXT,
  created_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS leads (
  id                INTEGER PRIMARY KEY,
  contact_id        INTEGER NOT NULL REFERENCES contacts(id),
  listing_id        INTEGER REFERENCES listings(id),
  status            TEXT NOT NULL,
  next_step         TEXT,
  next_step_at      TEXT,
  lost_reason       TEXT,
  contract_ends_at  TEXT,
  created_at        TEXT NOT NULL,
  updated_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS call_log (
  id                INTEGER PRIMARY KEY,
  lead_id           INTEGER NOT NULL REFERENCES leads(id),
  called_at         TEXT NOT NULL,
  outcome           TEXT NOT NULL,
  opener_used       TEXT,
  objection         TEXT,
  note              TEXT
);

CREATE TABLE IF NOT EXISTS daily_stats (
  day               TEXT PRIMARY KEY,
  calls_made        INTEGER NOT NULL DEFAULT 0,
  target            INTEGER NOT NULL DEFAULT 10,
  meetings_booked   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS scan_log (
  id                INTEGER PRIMARY KEY,
  source            TEXT NOT NULL,
  started_at        TEXT NOT NULL,
  finished_at       TEXT,
  pages             INTEGER,
  found             INTEGER,
  new               INTEGER,
  status            TEXT NOT NULL,
  detail            TEXT
);

CREATE INDEX IF NOT EXISTS idx_listings_phone ON listings (phone_e164);
CREATE INDEX IF NOT EXISTS idx_listings_active ON listings (is_active, seller_type);
CREATE INDEX IF NOT EXISTS idx_listings_seen ON listings (first_seen_at);
CREATE INDEX IF NOT EXISTS idx_listings_dedup ON listings (dedup_group);
CREATE INDEX IF NOT EXISTS idx_leads_next_step ON leads (next_step_at);
CREATE INDEX IF NOT EXISTS idx_call_log_lead ON call_log (lead_id, called_at);
CREATE INDEX IF NOT EXISTS idx_scan_log_source ON scan_log (source, started_at);
"""

_UPDATABLE = (
    "url",
    "city",
    "district",
    "street",
    "price",
    "area_m2",
    "rooms",
    "floor",
    "title",
    "description",
    "content_hash",
    "phone_e164",
)


def connect(path: str | Path) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def upsert_listing(conn: sqlite3.Connection, listing: Listing) -> tuple[int, bool]:
    """Wstawia lub odświeża ogłoszenie. Zwraca (id, czy_nowe)."""
    existing = conn.execute(
        "SELECT * FROM listings WHERE source = ? AND source_id = ?",
        (listing.source, listing.source_id),
    ).fetchone()
    stamp = listing.last_seen_at or utc_now()
    if existing is None:
        cursor = conn.execute(
            """
            INSERT INTO listings (
                source, source_id, url, deal_type, city, district, street, price,
                area_m2, rooms, floor, title, description, content_hash, phone_e164,
                seller_type, agency_score, dedup_group, first_seen_at, last_seen_at, is_active
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                listing.source,
                listing.source_id,
                listing.url,
                listing.deal_type,
                listing.city,
                listing.district,
                listing.street,
                listing.price,
                listing.area_m2,
                listing.rooms,
                listing.floor,
                listing.title,
                listing.description,
                listing.content_hash,
                listing.phone_e164,
                listing.seller_type,
                listing.agency_score,
                listing.dedup_group,
                listing.first_seen_at or stamp,
                stamp,
                listing.is_active,
            ),
        )
        conn.commit()
        return int(cursor.lastrowid), True

    updates: dict[str, object] = {"last_seen_at": stamp, "is_active": 1}
    for column in _UPDATABLE:
        value = getattr(listing, column)
        if value is not None and value != existing[column]:
            updates[column] = value
    if listing.seller_type != "unknown" and listing.seller_type != existing["seller_type"]:
        updates["seller_type"] = listing.seller_type
        updates["agency_score"] = listing.agency_score
    assignment = ", ".join(f"{key} = ?" for key in updates)
    conn.execute(
        f"UPDATE listings SET {assignment} WHERE id = ?",
        (*updates.values(), existing["id"]),
    )
    conn.commit()
    return int(existing["id"]), False


def start_scan(conn: sqlite3.Connection, source: str) -> int:
    cursor = conn.execute(
        "INSERT INTO scan_log (source, started_at, status) VALUES (?, ?, 'running')",
        (source, utc_now()),
    )
    conn.commit()
    return int(cursor.lastrowid)


def finish_scan(
    conn: sqlite3.Connection,
    scan_id: int,
    status: str,
    pages: int = 0,
    found: int = 0,
    new: int = 0,
    detail: str | None = None,
) -> None:
    conn.execute(
        """
        UPDATE scan_log
           SET finished_at = ?, status = ?, pages = ?, found = ?, new = ?, detail = ?
         WHERE id = ?
        """,
        (utc_now(), status, pages, found, new, detail, scan_id),
    )
    conn.commit()


def blocked_until(conn: sqlite3.Connection, source: str, cooldown_minutes: int) -> str | None:
    """Zwraca moment końca karencji, jeśli źródło było ostatnio zablokowane."""
    row = conn.execute(
        """
        SELECT started_at FROM scan_log
         WHERE source = ? AND status = 'blocked'
         ORDER BY id DESC LIMIT 1
        """,
        (source,),
    ).fetchone()
    if row is None:
        return None
    blocked_at = datetime.fromisoformat(row["started_at"].replace("Z", "+00:00"))
    until = blocked_at + timedelta(minutes=cooldown_minutes)
    if until <= datetime.now(timezone.utc):
        return None
    return until.isoformat(timespec="seconds").replace("+00:00", "Z")


def consecutive_empty_scans(conn: sqlite3.Connection, source: str, limit: int = 2) -> int:
    rows = conn.execute(
        """
        SELECT found FROM scan_log
         WHERE source = ? AND status = 'ok'
         ORDER BY id DESC LIMIT ?
        """,
        (source, limit),
    ).fetchall()
    count = 0
    for row in rows:
        if (row["found"] or 0) == 0:
            count += 1
        else:
            break
    return count
