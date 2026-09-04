"""Testy normalizacji: telefon E.164, cena, metraż, pokoje, piętro, lokalizacja.

Zwraca zielone, gdy RawListing zamienia się w Listing bez utraty i bez wymyślania danych.
"""

import pytest

from ocrm.models import RawListing
from ocrm.normalize import (
    normalize_area,
    normalize_floor,
    normalize_listing,
    normalize_location,
    normalize_phone,
    normalize_price,
    normalize_rooms,
)


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("501234567", "+48501234567"),
        ("+48 501 234 567", "+48501234567"),
        ("48501234567", "+48501234567"),
        ("0048 501-234-567", "+48501234567"),
        ("0501234567", "+48501234567"),
        ("tel. 501 234 567", "+48501234567"),
        ("(58) 123 45 67", "+48581234567"),
    ],
)
def test_normalize_phone_accepts_polish_formats(raw, expected):
    assert normalize_phone(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "brak", "12345", "1234567890123", "001234567"])
def test_normalize_phone_rejects_garbage(raw):
    assert normalize_phone(raw) is None


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("649 000 zł", 649000),
        ("649000", 649000),
        ("1 250 000 zł do negocjacji", 1250000),
        ("3 200 zł/mc", 3200),
        (1250000, 1250000),
        ("2 500,50 zł", 2500),
    ],
)
def test_normalize_price(raw, expected):
    assert normalize_price(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "Zapytaj o cenę", "0"])
def test_normalize_price_missing(raw):
    assert normalize_price(raw) is None


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("52,30 m²", 52.3),
        ("52.3 m2", 52.3),
        ("Powierzchnia: 48 m²", 48.0),
        (61.5, 61.5),
        ("38", 38.0),
    ],
)
def test_normalize_area(raw, expected):
    assert normalize_area(raw) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [("3 pokoje", 3), ("2 pokoi", 2), ("Kawalerka", 1), ("4", 4), (3, 3)],
)
def test_normalize_rooms(raw, expected):
    assert normalize_rooms(raw) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [("parter", 0), ("3 piętro", 3), ("Piętro: 7", 7), ("suterena", -1), (2, 2)],
)
def test_normalize_floor(raw, expected):
    assert normalize_floor(raw) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Gdańsk, Wrzeszcz Górny", ("Gdańsk", "Wrzeszcz Górny", None)),
        ("Gdynia, Pomorskie", ("Gdynia", None, None)),
        ("Sopot", ("Sopot", None, None)),
        ("Gdańsk, Oliwa, ul. Grunwaldzka", ("Gdańsk", "Oliwa", "Grunwaldzka")),
        ("Warszawa, Mokotów", ("Warszawa", "Mokotów", None)),
        ("gdansk, Zaspa", ("Gdańsk", "Zaspa", None)),
    ],
)
def test_normalize_location(raw, expected):
    assert normalize_location(raw) == expected


def test_normalize_listing_maps_raw_to_listing():
    raw = RawListing(
        source="olx",
        source_id="ID123",
        url="https://www.olx.pl/d/oferta/x-ID123.html",
        deal_type="sale",
        title="  Mieszkanie 3 pokoje Wrzeszcz  ",
        description=" Sprzedam mieszkanie bezpośrednio ",
        price_raw="649 000 zł",
        area_raw="52,30 m²",
        rooms_raw="3 pokoje",
        floor_raw="2 piętro",
        location_raw="Gdańsk, Wrzeszcz Górny",
        phone_raw="+48 501 234 567",
        seller_label="Osoba prywatna",
    )
    listing = normalize_listing(raw, seen_at="2026-09-04T06:00:00Z")

    assert listing.source_id == "ID123"
    assert listing.city == "Gdańsk"
    assert listing.district == "Wrzeszcz Górny"
    assert listing.price == 649000
    assert listing.area_m2 == 52.3
    assert listing.rooms == 3
    assert listing.floor == 2
    assert listing.phone_e164 == "+48501234567"
    assert listing.title == "Mieszkanie 3 pokoje Wrzeszcz"
    assert listing.first_seen_at == listing.last_seen_at == "2026-09-04T06:00:00Z"
    assert listing.seller_type == "unknown"


def test_normalize_listing_survives_empty_fields():
    raw = RawListing(source="olx", source_id="1", url="https://x", deal_type="rent")
    listing = normalize_listing(raw)

    assert listing.price is None
    assert listing.area_m2 is None
    assert listing.phone_e164 is None
    assert listing.city is None
    assert listing.is_active == 1
