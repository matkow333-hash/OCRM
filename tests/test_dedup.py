"""Testy deduplikacji: trzy reguły, grupowanie i wybór rekordu na poranną listę.

Zwraca zielone, gdy to samo mieszkanie z dwóch portali trafia do jednej grupy,
a dwa różne mieszkania nie zlepiają się w jedno.
"""

import pytest

from ocrm import db
from ocrm.dedup import (
    assign_group,
    content_hash,
    hamming,
    pick_primary,
    same_object,
    simhash,
)
from ocrm.models import Listing
from ocrm.normalize import utc_now

OPIS = (
    "Sprzedam przestronne mieszkanie trzypokojowe we Wrzeszczu Górnym, druga linia zabudowy, "
    "dwa balkony od strony południowej, piwnica w cenie, cicha i zielona okolica, blisko "
    "przystanek tramwajowy oraz stacja SKM. Mieszkanie po remoncie w 2021 roku, nowa instalacja "
    "elektryczna, okna wymienione na trzyszybowe, kuchnia w zabudowie zostaje. Budynek z 1998 "
    "roku, winda, zamknięte podwórko z placem zabaw. W okolicy szkoła, przedszkole, sklepy i park."
)
KROTKI_OPIS = "Sprzedam mieszkanie, Wrzeszcz, trzy pokoje. Dzwonić po 16."


def listing(**fields) -> Listing:
    base = dict(
        source="olx",
        source_id="1",
        url="https://example.test/1",
        deal_type="sale",
        city="Gdańsk",
        district="Wrzeszcz",
        street=None,
        price=649000,
        area_m2=52.3,
        description=OPIS,
        phone_e164="+48501234567",
        first_seen_at=utc_now(),
        last_seen_at=utc_now(),
    )
    base.update(fields)
    item = Listing(**base)
    item.content_hash = content_hash(item.description)
    return item


@pytest.fixture()
def conn(tmp_path):
    connection = db.connect(tmp_path / "ocrm.db")
    db.init_db(connection)
    yield connection
    connection.close()


def test_simhash_is_stable_and_close_for_edited_text():
    original = simhash(OPIS)
    edited = simhash(OPIS.replace("cicha okolica", "spokojna okolica"))
    unrelated = simhash(
        "Wynajmę garaż na Zaspie, murowany, miejsce postojowe w hali podziemnej, monitoring, "
        "brama na pilota, dostępny od października, faktura VAT, długoterminowo."
    )

    assert original == simhash(OPIS)
    assert hamming(f"{original:016x}", f"{edited:016x}") <= 3
    assert hamming(f"{original:016x}", f"{unrelated:016x}") > 3


def test_simhash_none_for_empty_text():
    assert simhash("") is None
    assert content_hash(None) is None
    assert hamming(None, "abc") is None


def test_short_descriptions_get_no_fingerprint():
    assert content_hash(KROTKI_OPIS) is None


def test_rule_three_stays_silent_for_short_descriptions(conn):
    db.upsert_listing(
        conn, listing(source_id="A", phone_e164=None, street=None, description=KROTKI_OPIS)
    )
    other = listing(
        source="otodom",
        source_id="B",
        phone_e164=None,
        street=None,
        area_m2=31.0,
        price=380000,
        description="Sprzedam mieszkanie, Przymorze, dwa pokoje. Dzwonić po 18.",
    )
    assert not same_object(other, _candidate(conn))


def test_rule_one_phone_plus_area_plus_price(conn):
    first = listing(source="olx", source_id="A")
    db.upsert_listing(conn, first)
    first_group = assign_group(conn, first)

    twin = listing(source="otodom", source_id="B", area_m2=53.0, price=655000, description="Inny opis.")
    assert same_object(twin, _candidate(conn))
    assert assign_group(conn, twin) is not None


def test_rule_one_rejects_different_area(conn):
    db.upsert_listing(conn, listing(source_id="A"))
    far = listing(source="otodom", source_id="B", area_m2=61.0, description="Zupełnie inny tekst opisu.")
    assert not same_object(far, _candidate(conn))


def test_rule_two_street_when_phone_missing(conn):
    db.upsert_listing(conn, listing(source_id="A", phone_e164=None, street="Grunwaldzka"))
    twin = listing(
        source="gratka",
        source_id="B",
        phone_e164=None,
        street="grunwaldzka",
        area_m2=52.9,
        price=660000,
        description="Zupełnie inaczej napisane ogłoszenie o tym samym lokalu.",
    )
    assert same_object(twin, _candidate(conn))


def test_rule_three_copied_description(conn):
    db.upsert_listing(conn, listing(source_id="A", phone_e164=None, street=None))
    copied = listing(
        source="morizon",
        source_id="B",
        phone_e164=None,
        street=None,
        area_m2=99.0,
        price=1,
        description=OPIS.replace("cicha okolica", "spokojna okolica"),
    )
    assert same_object(copied, _candidate(conn))


def test_different_flats_are_not_merged(conn):
    db.upsert_listing(conn, listing(source_id="A", phone_e164="+48501234567"))
    other = listing(
        source="otodom",
        source_id="B",
        phone_e164="+48600111222",
        street=None,
        area_m2=31.0,
        price=380000,
        description="Kawalerka na Przymorzu, do własnej aranżacji, niski czynsz.",
    )
    assert not same_object(other, _candidate(conn))


def test_assign_group_joins_same_flat_across_portals(conn):
    first = listing(source="olx", source_id="A")
    first.dedup_group = assign_group(conn, first)
    first_id, _ = db.upsert_listing(conn, first)

    second = listing(source="otodom", source_id="B", area_m2=52.8, price=655000)
    second.dedup_group = assign_group(conn, second, listing_id=None)
    db.upsert_listing(conn, second)

    groups = {
        row["dedup_group"]
        for row in conn.execute("SELECT dedup_group FROM listings").fetchall()
    }
    assert len(groups) == 1
    assert None not in groups


def test_assign_group_gives_new_group_to_unrelated_flat(conn):
    first = listing(source_id="A")
    first.dedup_group = assign_group(conn, first)
    db.upsert_listing(conn, first)

    other = listing(
        source="otodom",
        source_id="B",
        phone_e164="+48600111222",
        area_m2=31.0,
        price=380000,
        description="Kawalerka na Przymorzu, niski czynsz, do wprowadzenia.",
    )
    assert assign_group(conn, other) != first.dedup_group


def test_pick_primary_takes_oldest_then_richest(conn):
    stamp_old = "2026-09-01T06:00:00Z"
    stamp_new = "2026-09-04T06:00:00Z"
    db.upsert_listing(
        conn,
        listing(source="olx", source_id="A", first_seen_at=stamp_old, last_seen_at=stamp_old,
                street="Grunwaldzka", rooms=3, floor=2),
    )
    db.upsert_listing(
        conn,
        listing(source="otodom", source_id="B", first_seen_at=stamp_new, last_seen_at=stamp_new),
    )
    rows = conn.execute("SELECT * FROM listings").fetchall()

    assert pick_primary(rows)["source"] == "olx"
    assert pick_primary([]) is None


def test_pick_primary_breaks_tie_on_richer_record(conn):
    stamp = "2026-09-01T06:00:00Z"
    db.upsert_listing(
        conn,
        listing(source="olx", source_id="A", first_seen_at=stamp, last_seen_at=stamp,
                price=None, area_m2=None, phone_e164=None),
    )
    db.upsert_listing(
        conn,
        listing(source="otodom", source_id="B", first_seen_at=stamp, last_seen_at=stamp,
                street="Grunwaldzka", rooms=3, floor=2),
    )
    rows = conn.execute("SELECT * FROM listings").fetchall()
    assert pick_primary(rows)["source"] == "otodom"


def _candidate(conn):
    from ocrm.dedup import Candidate

    row = conn.execute(
        "SELECT id, dedup_group, phone_e164, street, area_m2, price, content_hash FROM listings"
    ).fetchone()
    return Candidate(*tuple(row))
