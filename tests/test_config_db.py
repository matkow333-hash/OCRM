"""Testy walidacji config.yaml i warstwy SQLite.

Zwraca zielone, gdy zły config nie przechodzi po cichu i gdy migracja jest idempotentna.
"""

import pytest
import yaml

from ocrm import db
from ocrm.config import ConfigError, load_config, parse_config
from ocrm.models import Listing
from ocrm.normalize import utc_now

VALID = {
    "area": {"cities": ["Gdańsk"], "districts": []},
    "search": {
        "deal_types": ["sale", "rent"],
        "sale": {"price_min": 250000, "price_max": 1800000, "area_min": 20, "area_max": 140},
        "rent": {"price_min": 1500, "price_max": 8000, "area_min": 18, "area_max": 120},
    },
    "scan": {
        "interval_minutes": 45,
        "max_pages_per_source": 5,
        "delay_seconds": [3, 8],
        "sources": ["olx"],
    },
    "classify": {
        "agency_threshold": 0.6,
        "private_threshold": 0.3,
        "phone_listings_agency_cutoff": 3,
        "keywords_agency": ["Prowizja"],
    },
    "list": {"size": 15, "daily_call_target": 10},
    "notify": {"time": "08:00", "channel": "email"},
}


def test_example_config_is_valid():
    with open("config.example.yaml", encoding="utf-8") as handle:
        cfg = parse_config(yaml.safe_load(handle))
    assert cfg.area.cities == ["Gdańsk", "Sopot", "Gdynia"]
    assert cfg.scan.delay_seconds == (3.0, 8.0)
    assert cfg.classify.keywords_agency[0] == "prowizja"


def test_search_config_carries_only_adapter_fields():
    search = parse_config(VALID).search_config()
    assert search.cities == ["Gdańsk"]
    assert search.filter_for("rent").price_max == 8000
    assert search.max_pages == 5


def test_load_config_missing_file(tmp_path):
    with pytest.raises(ConfigError, match="Brak pliku konfiguracji"):
        load_config(tmp_path / "nie-ma.yaml")


@pytest.mark.parametrize(
    "section, patch, message",
    [
        ("area", {"cities": []}, "area.cities"),
        ("search", {"deal_types": ["lease"]}, "deal_types"),
        ("search", {"sale": {"price_min": 9, "price_max": 5, "area_min": 20, "area_max": 40}}, "price_min > price_max"),
        ("scan", {"interval_minutes": 5}, "interval_minutes"),
        ("scan", {"delay_seconds": [0.2, 1]}, "delay_seconds"),
        ("scan", {"max_pages_per_source": 99}, "max_pages_per_source"),
        ("classify", {"agency_threshold": 0.2}, "private_threshold"),
        ("notify", {"channel": "sms"}, "notify.channel"),
        ("notify", {"time": "8 rano"}, "notify.time"),
    ],
)
def test_invalid_config_rejected(section, patch, message):
    data = {key: dict(value) for key, value in VALID.items()}
    data[section] = {**VALID[section], **patch}
    with pytest.raises(ConfigError, match=message):
        parse_config(data)


def test_init_db_is_idempotent(tmp_path):
    path = tmp_path / "nested" / "ocrm.db"
    conn = db.connect(path)
    db.init_db(conn)
    db.init_db(conn)

    tables = {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    assert {"listings", "contacts", "leads", "call_log", "daily_stats", "scan_log"} <= tables
    conn.close()


def test_upsert_listing_inserts_then_refreshes(tmp_path):
    conn = db.connect(tmp_path / "ocrm.db")
    db.init_db(conn)
    stamp = utc_now()
    listing = Listing(
        source="olx",
        source_id="ID1",
        url="https://www.olx.pl/d/oferta/a-ID1.html",
        deal_type="sale",
        city="Gdańsk",
        price=500000,
        first_seen_at=stamp,
        last_seen_at=stamp,
    )

    listing_id, is_new = db.upsert_listing(conn, listing)
    assert is_new

    listing.price = 480000
    listing.phone_e164 = "+48501234567"
    listing.last_seen_at = "2026-09-05T06:00:00Z"
    same_id, is_new_again = db.upsert_listing(conn, listing)

    assert same_id == listing_id
    assert not is_new_again
    row = conn.execute("SELECT * FROM listings WHERE id = ?", (listing_id,)).fetchone()
    assert row["price"] == 480000
    assert row["phone_e164"] == "+48501234567"
    assert row["first_seen_at"] == stamp
    assert row["last_seen_at"] == "2026-09-05T06:00:00Z"
    conn.close()


def test_blocked_until_expires_after_cooldown(tmp_path):
    conn = db.connect(tmp_path / "ocrm.db")
    db.init_db(conn)
    scan_id = db.start_scan(conn, "olx")
    db.finish_scan(conn, scan_id, "blocked", detail="status 429")

    assert db.blocked_until(conn, "olx", 60) is not None
    conn.execute("UPDATE scan_log SET started_at = ? WHERE id = ?", ("2020-01-01T00:00:00Z", scan_id))
    assert db.blocked_until(conn, "olx", 60) is None
    conn.close()
