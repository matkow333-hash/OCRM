"""Testy parsera OLX na zapisanych fixture'ach HTML - bez ruchu sieciowego.

Zwraca zielone, gdy zmiana struktury strony jest wyłapana lokalnie, zanim skaner ruszy w świat.
Test pełnego przebiegu podmienia Fetcher na atrapę czytającą pliki z dysku.
"""

import json
import re
from dataclasses import replace
from pathlib import Path

import pytest

from ocrm import db, pipeline
from ocrm.adapters.olx import (
    CITY_ID,
    OlxAdapter,
    build_api_path,
    build_search_url,
    parse_offer_page,
    parse_search_dom,
    parse_search_page,
)
from ocrm.config import parse_config

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
        "sources": ["olx"],
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
    """Atrapa transportu przeglądarkowego: oddaje zapisane odpowiedzi API po city_id.

    Fixture'y pochodzą z żywego OLX-a (4 września 2026), przycięte do dziesięciu ogłoszeń
    na miasto. Licznik visible_total_count zostaje prawdziwy, bo to po nim adapter poznaje
    koniec danych - podmiana na dziesiątkę ukryłaby błąd w warunku stopu.
    """

    def __init__(self, payloads: dict[int, dict] | None = None, repeat: bool = False):
        self.payloads = payloads or {}
        self.repeat = repeat
        self.paths: list[str] = []

    def get_json(self, path: str) -> dict:
        self.paths.append(path)
        city_id = int(re.search(r"city_id=(\d+)", path).group(1))
        offset = int(re.search(r"offset=(\d+)", path).group(1))
        payload = self.payloads.get(city_id)
        if payload is None:
            return {"data": [], "metadata": {"visible_total_count": 0}}
        if offset and not self.repeat:
            return {"data": [], "metadata": {"visible_total_count": 0}}
        return payload

    def close(self) -> None:
        pass


def api_fixture(city: str) -> dict:
    return json.loads((FIXTURES / f"olx_api_{city}.json").read_text(encoding="utf-8"))


def tricity_payloads() -> dict[int, dict]:
    return {
        CITY_ID["gdansk"]: api_fixture("gdansk"),
        CITY_ID["sopot"]: api_fixture("sopot"),
        CITY_ID["gdynia"]: api_fixture("gdynia"),
    }


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def make_config(**scan_overrides):
    data = {key: dict(value) for key, value in CONFIG_DATA.items()}
    data["scan"] = {**CONFIG_DATA["scan"], **scan_overrides}
    return parse_config(data)


def test_build_search_url_uses_private_filter_and_ranges():
    cfg = make_config().search_config()
    url = build_search_url("sale", "Gdańsk", cfg, page=2)

    assert url.startswith("https://www.olx.pl/nieruchomosci/mieszkania/sprzedaz/gdansk/?")
    assert "search%5Bfilter_enum_private_business%5D%5B0%5D=private" in url
    assert "search%5Bfilter_float_price%3Afrom%5D=250000" in url
    assert "search%5Bfilter_float_m%3Ato%5D=140" in url
    assert "search%5Border%5D=created_at%3Adesc" in url
    assert url.endswith("page=2")


def test_build_search_url_first_page_has_no_page_param():
    cfg = make_config().search_config()
    assert "page=" not in build_search_url("rent", "Sopot", cfg)


def test_parse_search_page_reads_embedded_state():
    listings = parse_search_page(fixture("olx_search_state.html"), "sale")

    assert len(listings) == 12
    first = listings[0]
    assert first.source == "olx"
    assert first.source_id == "987654301"
    assert first.url.startswith("https://www.olx.pl/d/oferta/")
    assert first.price_raw == "649 000 zł"
    assert first.area_raw == "52.3 m²"
    assert first.rooms_raw == "3 pokoje"
    assert first.floor_raw == "2 piętro"
    assert first.location_raw == "Gdańsk, Wrzeszcz Górny, Pomorskie"
    assert first.seller_label == "private"
    assert listings[2].seller_label == "business"


def test_parse_search_page_makes_relative_urls_absolute():
    listings = parse_search_page(fixture("olx_search_state.html"), "rent")
    assert listings[1].url == "https://www.olx.pl/d/oferta/oferta-2-ID16aB02.html"
    assert listings[1].phone_raw == "501 234 567"


def test_parse_search_dom_fallback():
    listings = parse_search_dom(fixture("olx_search_dom.html"), "sale")

    assert [item.source_id for item in listings] == ["16aBcD", "16aBcE"]
    assert listings[0].title == "Mieszkanie 3 pokoje, Wrzeszcz Górny, bezpośrednio"
    assert listings[0].price_raw == "649 000 zł"
    assert listings[0].location_raw == "Gdańsk, Wrzeszcz Górny"
    assert listings[0].posted_at_raw == "Dzisiaj o 05:12"


def test_parse_search_page_falls_back_to_dom_when_state_missing():
    listings = parse_search_page(fixture("olx_search_dom.html"), "sale")
    assert len(listings) == 2


def test_parse_search_page_empty_on_garbage():
    assert parse_search_page("<html><body>nic tu nie ma</body></html>", "sale") == []


def test_parse_offer_page():
    detail = parse_offer_page(fixture("olx_offer.html"))

    assert "bez pośredników" in detail["description"]
    assert detail["seller_label"] == "Osoba prywatna"
    assert detail["phone_raw"] == "+48501234567"
    assert detail["area_raw"] == "Powierzchnia: 52.3 m²"
    assert detail["rooms_raw"] == "Liczba pokoi: 3 pokoje"
    assert detail["floor_raw"] == "Poziom: 2 piętro"


def test_adapter_search_yields_listings_without_network():
    cfg = make_config().search_config()
    adapter = OlxAdapter(fetcher=FakeFetcher(tricity_payloads()))
    cfg_one_city = replace(cfg, cities=["Gdańsk"])

    listings = list(adapter.search(cfg_one_city))
    assert len(listings) == 10
    assert {item.source for item in listings} == {"olx"}
    assert all(item.url.startswith("https://www.olx.pl/") for item in listings)


def test_adapter_search_deduplicates_ids_across_batches():
    cfg = make_config(max_pages_per_source=2).search_config()
    adapter = OlxAdapter(fetcher=FakeFetcher(tricity_payloads(), repeat=True))
    cfg_one_city = replace(cfg, cities=["Gdańsk"])

    assert len(list(adapter.search(cfg_one_city))) == 10


def test_api_payload_carries_detail_fields_without_visiting_offer_page():
    """Powód, dla którego adapter nie wchodzi już na stronę każdej oferty:
    partia z API niesie opis, metraż, pokoje i etykietę sprzedawcy od razu."""
    cfg = make_config().search_config()
    fetcher = FakeFetcher(tricity_payloads())
    adapter = OlxAdapter(fetcher=fetcher)

    listings = list(adapter.search(replace(cfg, cities=["Gdańsk"])))

    assert all(item.description for item in listings)
    assert all(item.area_raw for item in listings)
    assert all(item.seller_label in ("firma", "osoba prywatna") for item in listings)
    assert len(fetcher.paths) == 1


def test_api_phone_flag_is_not_mistaken_for_a_number():
    """contact.phone w API jest wartością logiczną. Wpisany wprost dawał numer 'True'."""
    cfg = make_config().search_config()
    adapter = OlxAdapter(fetcher=FakeFetcher(tricity_payloads()))

    listings = list(adapter.search(replace(cfg, cities=["Gdańsk"])))

    assert all(item.phone_raw is None for item in listings)
    assert any(item.extra.get("has_phone") for item in listings)


def test_api_path_carries_category_city_and_ranges():
    cfg = make_config().search_config()

    path = build_api_path("sale", "Gdańsk", cfg, offset=40)

    assert "category_id=14" in path
    assert f"city_id={CITY_ID['gdansk']}" in path
    assert "offset=40" in path
    assert "filter_float_price%3Afrom=250000" in path
    assert "filter_float_m%3Ato=140" in path


def test_api_path_refuses_city_outside_the_measured_map():
    cfg = make_config().search_config()

    with pytest.raises(ValueError, match="Nieznane miasto"):
        build_api_path("sale", "Kraków", cfg)


@pytest.fixture()
def conn(tmp_path):
    connection = db.connect(tmp_path / "ocrm.db")
    db.init_db(connection)
    yield connection
    connection.close()


def test_scan_source_stores_only_tricity_and_is_idempotent(conn, monkeypatch):
    cfg = make_config()

    def adapter_factory(_name):
        return OlxAdapter(fetcher=FakeFetcher(tricity_payloads()))

    monkeypatch.setattr(pipeline, "get_adapter", adapter_factory)

    first = pipeline.scan_source(conn, cfg, "olx")
    assert first.status == "ok"
    assert first.found == 30

    rows = conn.execute("SELECT city, seller_type FROM listings").fetchall()
    assert {row["city"] for row in rows} == {"Gdańsk", "Sopot", "Gdynia"}
    assert first.new == len(rows)

    second = pipeline.scan_source(conn, cfg, "olx")
    assert second.new == 0
    assert conn.execute("SELECT COUNT(*) AS n FROM listings").fetchone()["n"] == len(rows)


def test_scan_source_logs_block_and_then_cools_down(conn, monkeypatch):
    cfg = make_config()

    class BlockingFetcher(FakeFetcher):
        def get_json(self, path: str) -> dict:
            from ocrm.adapters.base import Blocked

            raise Blocked("status 429 przy " + path)

    monkeypatch.setattr(
        pipeline, "get_adapter", lambda _name: OlxAdapter(fetcher=BlockingFetcher())
    )

    result = pipeline.scan_source(conn, cfg, "olx")
    assert result.status == "blocked"
    assert conn.execute("SELECT status FROM scan_log").fetchall()[-1]["status"] == "blocked"

    again = pipeline.scan_source(conn, cfg, "olx")
    assert again.status == "cooldown"
