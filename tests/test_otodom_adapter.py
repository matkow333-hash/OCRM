"""Testy adaptera Otodom na zapisanych fixture'ach - bez ruchu sieciowego.

Fixture'y sa prawdziwymi odpowiedziami serwisu z 7 wrzesnia 2026, przyciete do szesciu
ofert i do pol, ktorych adapter uzywa. Zielone znaczy, ze zmiana struktury strony
zostanie wylapana lokalnie, zanim skaner ruszy w swiat.
"""

import re
from dataclasses import replace
from pathlib import Path

import pytest

from ocrm.adapters.otodom import (
    OtodomAdapter,
    build_search_url,
    item_to_raw,
    parse_offer_page,
    parse_search_page,
)
from ocrm.config import parse_config
from ocrm.normalize import normalize_listing

FIXTURES = Path(__file__).parent / "fixtures"

CONFIG_DATA = {
    "area": {"cities": ["Gdańsk", "Sopot", "Gdynia"], "districts": []},
    "search": {
        "deal_types": ["sale"],
        "sale": {"price_min": 250000, "price_max": 1800000, "area_min": 20, "area_max": 140},
        "rent": {"price_min": 1500, "price_max": 8000, "area_min": 18, "area_max": 120},
    },
    "scan": {
        "interval_minutes": 45,
        "max_pages_per_source": 1,
        "delay_seconds": [3, 8],
        "sources": ["otodom"],
        "fetch_details": False,
        "fetch_phones": False,
    },
    "classify": {
        "agency_threshold": 0.6,
        "private_threshold": 0.3,
        "phone_listings_agency_cutoff": 3,
        "keywords_agency": ["prowizja"],
    },
    "list": {"size": 15, "daily_call_target": 10},
    "notify": {"time": "08:00", "channel": "none"},
}


class FakeFetcher:
    """Atrapa transportu przegladarkowego: wyniki pod adresem wyszukiwania,
    strona oferty pod kazdym adresem /pl/oferta/."""

    def __init__(self, wyniki: str, oferta: str | None = None):
        self.wyniki = wyniki
        self.oferta = oferta or ""
        self.adresy: list[str] = []

    def get_html(self, url: str) -> str:
        self.adresy.append(url)
        return self.oferta if "/pl/oferta/" in url else self.wyniki

    def close(self) -> None:
        pass


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def make_config(**scan_overrides):
    data = {key: dict(value) for key, value in CONFIG_DATA.items()}
    data["scan"] = {**CONFIG_DATA["scan"], **scan_overrides}
    return parse_config(data)


def test_search_url_carries_city_path_ranges_and_private_filter():
    cfg = make_config().search_config()

    url = build_search_url("sale", "Gdańsk", cfg, page=3)

    assert "/pl/wyniki/sprzedaz/mieszkanie/pomorskie/gdansk/gdansk/gdansk" in url
    assert "ownerTypeSingleSelect=PRIVATE" in url
    assert "priceMin=250000" in url
    assert "areaMax=140" in url
    assert "page=3" in url


def test_search_url_refuses_city_outside_the_measured_map():
    cfg = make_config().search_config()

    with pytest.raises(ValueError, match="Nieznane miasto"):
        build_search_url("sale", "Kraków", cfg)


def test_parse_search_page_reads_items_and_page_count():
    listings, total_pages = parse_search_page(fixture("otodom_search.html"), "sale")

    assert listings
    assert total_pages >= 1
    assert {item.source for item in listings} == {"otodom"}
    assert all(item.url.startswith("https://www.otodom.pl/pl/oferta/") for item in listings)


def test_listing_carries_price_area_and_location_without_visiting_offer():
    listings, _ = parse_search_page(fixture("otodom_search.html"), "sale")

    first = listings[0]
    assert isinstance(first.price_raw, int) and first.price_raw > 0
    assert first.area_raw
    assert first.location_raw and "," in first.location_raw
    assert first.seller_label == "osoba prywatna"


def test_agency_listings_are_dropped_even_when_the_portal_returns_them():
    """Filtr ownerTypeSingleSelect=PRIVATE przepuszcza agencje przy wynajmie:
    zmierzone 17 ofert prywatnych na 37 zwroconych. Flaga jest ostatnim slowem."""
    agencja = {"id": 1, "slug": "biuro-nieruchomosci-ID1", "isPrivateOwner": False}

    assert item_to_raw(agencja, "rent") is None


def test_rooms_and_floor_enums_become_numbers():
    listings, _ = parse_search_page(fixture("otodom_search.html"), "sale")

    pokoje = [item.rooms_raw for item in listings if item.rooms_raw is not None]
    assert pokoje and all(isinstance(value, int) for value in pokoje)
    pietra = [item.floor_raw for item in listings if item.floor_raw is not None]
    assert all(isinstance(value, int) for value in pietra)


def test_street_travels_inside_location_so_normalizer_fills_it():
    listings, _ = parse_search_page(fixture("otodom_search.html"), "sale")
    z_ulica = [item for item in listings if item.location_raw and re.search(r"\bul\.", item.location_raw)]

    assert z_ulica, "fixture nie zawiera zadnej oferty z ulica"
    listing = normalize_listing(z_ulica[0])
    assert listing.city
    assert listing.street


def test_offer_page_yields_the_phone_number():
    detail = parse_offer_page(fixture("otodom_offer.html"))

    assert detail["phone_raw"] and detail["phone_raw"].startswith("+48")
    assert detail["seller_label"] == "osoba prywatna"
    assert detail["description"]


def test_offer_page_without_a_number_is_not_an_error():
    """Wlasciciel moze nie podac numeru (hasPhoneNumber=false) i ogloszenie i tak
    ma wejsc do bazy z pustym telefonem. Zmierzone: 11 ofert z numerem na 12."""
    pusta = (
        '<script id="__NEXT_DATA__" type="application/json" crossorigin="anonymous">'
        '{"props":{"pageProps":{"ad":{"contactDetails":'
        '{"name":"Jarek","type":"private","phones":[],"hasPhoneNumber":false}}}}}'
        "</script>"
    )

    detail = parse_offer_page(pusta)

    assert detail["phone_raw"] is None
    assert detail["seller_label"] == "osoba prywatna"


def test_adapter_reads_phone_only_when_configuration_asks_for_it():
    cfg = make_config().search_config()
    fetcher = FakeFetcher(fixture("otodom_search.html"), fixture("otodom_offer.html"))
    adapter = OtodomAdapter(fetcher=fetcher)

    listings = list(adapter.search(replace(cfg, cities=["Gdańsk"])))

    assert listings
    assert all(item.phone_raw is None for item in listings)
    assert all("/pl/oferta/" not in url for url in fetcher.adresy)


def test_adapter_fetches_offer_pages_when_phones_are_requested():
    cfg = make_config(fetch_phones=True).search_config()
    fetcher = FakeFetcher(fixture("otodom_search.html"), fixture("otodom_offer.html"))
    adapter = OtodomAdapter(fetcher=fetcher)

    listings = list(adapter.search(replace(cfg, cities=["Gdańsk"])))

    assert all(item.phone_raw and item.phone_raw.startswith("+48") for item in listings)
    assert sum(1 for url in fetcher.adresy if "/pl/oferta/" in url) == len(listings)


def test_adapter_deduplicates_across_pages():
    cfg = make_config(max_pages_per_source=3).search_config()
    adapter = OtodomAdapter(fetcher=FakeFetcher(fixture("otodom_search.html")))

    listings = list(adapter.search(replace(cfg, cities=["Gdańsk"])))
    identyfikatory = [item.source_id for item in listings]

    assert len(identyfikatory) == len(set(identyfikatory))


def test_broken_page_yields_nothing_instead_of_raising():
    listings, total_pages = parse_search_page("<html><body>nic tu nie ma</body></html>", "sale")

    assert listings == []
    assert total_pages == 0
