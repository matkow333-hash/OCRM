"""Testy rozpoznawania pośrednika.

Zwraca zielone, gdy właściciel piszący „bez prowizji" nie ląduje w koszu z biurami,
a biuro z trzema ofertami pod jednym numerem nie przechodzi jako osoba prywatna.
"""

import pytest

from ocrm import db
from ocrm.classify import PhoneContext, agency_score, classify, phone_context
from ocrm.config import parse_config
from ocrm.models import Listing
from ocrm.normalize import utc_now
from tests.test_config_db import VALID


def settings(**overrides):
    data = {key: dict(value) for key, value in VALID.items()}
    data["classify"] = {
        **VALID["classify"],
        "keywords_agency": [
            "prowizja",
            "biuro nieruchomości",
            "zapraszam do współpracy",
            "pośrednictwo",
            "nasza oferta",
        ],
        **overrides,
    }
    return parse_config(data).classify


def listing(**fields) -> Listing:
    base = dict(
        source="olx",
        source_id="1",
        url="https://example.test/1",
        deal_type="sale",
        city="Gdańsk",
        district="Wrzeszcz",
        price=600000,
        area_m2=50.0,
        first_seen_at=utc_now(),
        last_seen_at=utc_now(),
    )
    base.update(fields)
    return Listing(**base)


def test_portal_flag_private_wins_when_description_is_neutral():
    item = listing(seller_type="private", description="Sprzedam mieszkanie.")
    assert classify(item, settings()).seller_type == "private"


def test_portal_flag_agency_marks_agency():
    item = listing(seller_type="agency", description="Sprzedam mieszkanie.")
    result = classify(item, settings())
    assert result.seller_type == "agency"
    assert result.agency_score >= 0.6


def test_agency_keywords_push_score_up():
    item = listing(
        description="Nasza oferta. Prowizja 2%. Zapraszam do współpracy z biurem nieruchomości."
    )
    assert classify(item, settings()).seller_type == "agency"


def test_owner_writing_without_commission_stays_private():
    item = listing(
        description="Sprzedam bezpośrednio, bez prowizji, bez pośredników. Kontakt po 16."
    )
    result = classify(item, settings())
    assert result.seller_type == "private"
    assert result.agency_score <= 0.3


def test_same_phone_on_many_listings_marks_agency():
    item = listing(description="Mieszkanie do sprzedania.")
    context = PhoneContext(active_listings=4, districts=1)
    assert classify(item, settings(), context).seller_type == "agency"


def test_same_phone_in_many_districts_raises_score():
    item = listing(description="Mieszkanie do sprzedania.")
    spread = agency_score(item, settings(), PhoneContext(active_listings=1, districts=4))
    single = agency_score(item, settings(), PhoneContext(active_listings=1, districts=1))
    assert spread > single


def test_brochure_description_raises_score():
    brochure = "Zapraszamy do zapoznania się z ofertą.\n\n" + ("• udogodnienie w standardzie " * 90)
    assert len(brochure) > 1500
    high = agency_score(listing(description=brochure), settings())
    low = agency_score(listing(description="Krótki opis mieszkania."), settings())
    assert high > low


def test_neutral_listing_lands_in_unknown_band():
    item = listing(description="Mieszkanie 50 m2, druga linia zabudowy.")
    result = classify(item, settings())
    assert result.seller_type == "unknown"
    assert 0.3 < result.agency_score < 0.6


def test_score_is_clamped_to_unit_range():
    item = listing(
        seller_type="agency",
        description="Prowizja. Biuro nieruchomości. Pośrednictwo. Nasza oferta.",
    )
    assert agency_score(item, settings(), PhoneContext(active_listings=9, districts=9)) <= 1.0


def test_weights_come_from_config_not_code():
    item = listing(description="Prowizja od kupującego.")
    default = agency_score(item, settings())
    muted = agency_score(item, settings(weights={"keyword_hit": 0.0, "keyword_hit_max": 0.0}))
    assert default > muted


@pytest.fixture()
def conn(tmp_path):
    connection = db.connect(tmp_path / "ocrm.db")
    db.init_db(connection)
    yield connection
    connection.close()


def test_phone_context_counts_active_listings_and_districts(conn):
    stamp = utc_now()
    for index, district in enumerate(["Wrzeszcz", "Oliwa", "Zaspa"], start=1):
        db.upsert_listing(
            conn,
            listing(
                source_id=str(index),
                district=district,
                phone_e164="+48501234567",
                first_seen_at=stamp,
                last_seen_at=stamp,
            ),
        )

    context = phone_context(conn, "+48501234567")
    assert context.active_listings == 3
    assert context.districts == 3
    assert phone_context(conn, None) == PhoneContext()
    assert phone_context(conn, "+48999888777").active_listings == 0
