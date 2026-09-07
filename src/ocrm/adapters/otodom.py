"""Adapter Otodom: mieszkania od wlascicieli prywatnych w Trojmiescie.

Zwraca iterator RawListing. Dane z `__NEXT_DATA__` strony wynikow, numer telefonu
ze strony oferty. Transportem jest przegladarka (BrowserFetcher), nie httpx.

TRANSPORT: PIERWSZA WERSJA TEGO PLIKU BYLA W TYM MIEJSCU BLEDNA. Sprawdzenie curlem
dawalo 200 i stad wniosek, ze wystarczy zwykly klient HTTP. Nieprawda: httpx dostaje
403 "Request blocked" (te same 919 bajtow CloudFrontu co przy OLX) dla czterech roznych
zestawow naglowkow, z Accept-Encoding i Sec-Fetch wlacznie. Curl i Chromium przechodza.
Blokada siedzi w odcisku polaczenia, nie w naglowkach, wiec nie da sie jej obejsc
konfiguracja klienta - i dlatego Otodom, tak jak OLX, chodzi przez przegladarke.

DLACZEGO OTODOM, SKORO JEST JUZ OLX. Zmierzone 7 wrzesnia 2026: OLX przestal pokazywac
numer wlasciciela bez zalogowania, a numer w tresci ogloszenia ma 1 na 158 ofert
prywatnych. Bez numeru cala aplikacja nie ma do kogo dzwonic. Otodom podaje numer
otwartym tekstem w danych strony oferty, bez logowania i bez klikania - sprawdzone
na dziesieciu ofertach prywatnych z Gdanska, dziesiec na dziesiec z numerem.

CO JEST ZMIERZONE, A CO ZALOZONE. Wszystkie ponizsze ksztalty pochodza z odpowiedzi
serwisu, nie z dokumentacji:

- stan strony siedzi w `<script id="__NEXT_DATA__" type="application/json" crossorigin>`.
  Atrybut `crossorigin` jest wazny: wzorzec dopasowujacy sam `id` i `type` nie trafia.
- wyniki: `props.pageProps.data.searchAds` z `items` i `pagination`
- oferta: `props.pageProps.ad.contactDetails.phones[0]` oraz `ad.description`
- sciezka miasta ma postac `/pomorskie/<miasto>/<miasto>/<miasto>` i dziala dla calej
  trojki, bo Gdansk, Sopot i Gdynia sa miastami na prawach powiatu. Dla zwyklego miasta
  w powiecie ten wzorzec bylby inny - dlatego miasta sa w jawnej mapie, nie zgadywane.

FILTR OFERT PRYWATNYCH NIE WYSTARCZA. `ownerTypeSingleSelect=PRIVATE` w adresie dziala
przy sprzedazy, ale przy wynajmie przepuszcza agencje: zmierzone 17 ofert prywatnych
na 37 zwroconych. Dlatego kazda pozycja jest jeszcze sprawdzana po fladze
`isPrivateOwner`. Zaufanie samemu filtrowi portalu wpusciloby biura na liste Mileny.

STRONA OFERTY POBIERANA JEST TYLKO DLA WLASCICIELI PRYWATNYCH i tylko wtedy, gdy
konfiguracja prosi o telefony. Reszta pol - cena, metraz, pokoje, pietro, dzielnica,
opis skrocony, data - jest juz na liscie wynikow, wiec jedno zapytanie obsluguje
kilkadziesiat ogloszen.
"""

from __future__ import annotations

import json
import re
from typing import Any, Iterator
from urllib.parse import urlencode, urljoin

from ..config import SearchConfig
from ..models import RawListing
from ..normalize import fold
from .base import Blocked
from .browser import BrowserFetcher

BASE_URL = "https://www.otodom.pl"

TRANSACTION_PATH = {"sale": "sprzedaz", "rent": "wynajem"}

CITY_PATH = {
    "gdansk": "pomorskie/gdansk/gdansk/gdansk",
    "sopot": "pomorskie/sopot/sopot/sopot",
    "gdynia": "pomorskie/gdynia/gdynia/gdynia",
}

_STATE = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL
)

_STREET_PREFIXED = re.compile(r"^(ul\.|al\.|pl\.|os\.)\s", re.IGNORECASE)

ROOMS = {
    "ONE": 1, "TWO": 2, "THREE": 3, "FOUR": 4, "FIVE": 5,
    "SIX": 6, "SEVEN": 7, "EIGHT": 8, "NINE": 9, "TEN": 10,
}

FLOORS = {
    "CELLAR": -1, "GROUND": 0, "FIRST": 1, "SECOND": 2, "THIRD": 3,
    "FOURTH": 4, "FIFTH": 5, "SIXTH": 6, "SEVENTH": 7, "EIGHTH": 8,
    "NINTH": 9, "TENTH": 10,
}


class OtodomAdapter:
    name = "otodom"

    def __init__(self, fetcher=None) -> None:
        self._fetcher = fetcher
        self.pages_fetched = 0
        self.skip_phone_for: set[str] = set()

    def search(self, cfg: SearchConfig) -> Iterator[RawListing]:
        fetcher = self._fetcher or BrowserFetcher(cfg.user_agent, cfg.delay_seconds, anchor=None)
        owns_fetcher = self._fetcher is None
        seen: set[str] = set()
        try:
            for deal_type in cfg.deal_types:
                for city in cfg.cities:
                    for raw in self._search_city(fetcher, cfg, deal_type, city, seen):
                        if (
                            cfg.fetch_phones
                            and not raw.phone_raw
                            and raw.source_id not in self.skip_phone_for
                        ):
                            self._read_phone(fetcher, raw)
                        yield raw
        finally:
            if owns_fetcher:
                fetcher.close()

    def _search_city(
        self,
        fetcher,
        cfg: SearchConfig,
        deal_type: str,
        city: str,
        seen: set[str],
    ) -> Iterator[RawListing]:
        for page in range(1, cfg.max_pages + 1):
            url = build_search_url(deal_type, city, cfg, page)
            html = fetcher.get_html(url)
            self.pages_fetched += 1
            listings, total_pages = parse_search_page(html, deal_type)
            if not listings:
                return
            for raw in listings:
                if raw.source_id in seen:
                    continue
                seen.add(raw.source_id)
                yield raw
            if page >= total_pages:
                return

    def _read_phone(self, fetcher, raw: RawListing) -> None:
        try:
            html = fetcher.get_html(raw.url)
        except Blocked:
            raise
        self.pages_fetched += 1
        detail = parse_offer_page(html)
        raw.phone_raw = detail.get("phone_raw")
        raw.description = detail.get("description") or raw.description
        raw.seller_label = detail.get("seller_label") or raw.seller_label


def build_search_url(deal_type: str, city: str, cfg: SearchConfig, page: int = 1) -> str:
    if deal_type not in TRANSACTION_PATH:
        raise ValueError(f"Nieznany deal_type: {deal_type}")
    path = CITY_PATH.get(fold(city))
    if path is None:
        raise ValueError(f"Nieznane miasto: {city}. Znane: {', '.join(sorted(CITY_PATH))}")
    limits = cfg.filter_for(deal_type)
    params = {
        "ownerTypeSingleSelect": "PRIVATE",
        "priceMin": int(limits.price_min),
        "priceMax": int(limits.price_max),
        "areaMin": int(limits.area_min),
        "areaMax": int(limits.area_max),
    }
    if page > 1:
        params["page"] = page
    prefix = f"/pl/wyniki/{TRANSACTION_PATH[deal_type]}/mieszkanie/{path}"
    return f"{urljoin(BASE_URL, prefix)}?{urlencode(params)}"


def extract_state(html: str) -> Any | None:
    match = _STATE.search(html or "")
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except ValueError:
        return None


def parse_search_page(html: str, deal_type: str) -> tuple[list[RawListing], int]:
    state = extract_state(html)
    if state is None:
        return [], 0
    props = _dig(state, "props", "pageProps", "data", "searchAds")
    if not isinstance(props, dict):
        return [], 0
    pagination = props.get("pagination") or {}
    total_pages = pagination.get("totalPages") if isinstance(pagination, dict) else 0
    items = props.get("items")
    if not isinstance(items, list):
        return [], int(total_pages or 0)
    listings = [item_to_raw(item, deal_type) for item in items if isinstance(item, dict)]
    return [item for item in listings if item is not None], int(total_pages or 0)


def item_to_raw(item: dict, deal_type: str) -> RawListing | None:
    if not item.get("isPrivateOwner"):
        return None
    slug = item.get("slug")
    source_id = item.get("id")
    if not slug or source_id is None:
        return None
    raw = RawListing(
        source="otodom",
        source_id=str(source_id),
        url=f"{BASE_URL}/pl/oferta/{slug}",
        deal_type=deal_type,
        title=item.get("title"),
        description=item.get("shortDescription"),
        price_raw=_money(item.get("totalPrice") or item.get("rentPrice")),
        area_raw=item.get("areaInSquareMeters"),
        rooms_raw=ROOMS.get(str(item.get("roomsNumber") or "")),
        floor_raw=FLOORS.get(str(item.get("floorNumber") or "")),
        location_raw=_location(item.get("location")),
        seller_label="osoba prywatna",
        posted_at_raw=item.get("createdAtFirst") or item.get("dateCreated"),
    )
    return raw


def parse_offer_page(html: str) -> dict[str, str | None]:
    state = extract_state(html)
    pusty: dict[str, str | None] = {"phone_raw": None, "description": None, "seller_label": None}
    if state is None:
        return pusty
    ad = _dig(state, "props", "pageProps", "ad")
    if not isinstance(ad, dict):
        return pusty
    contact = ad.get("contactDetails")
    phone = None
    label = None
    if isinstance(contact, dict):
        phones = contact.get("phones")
        if isinstance(phones, list) and phones:
            phone = str(phones[0]) or None
        typ = contact.get("type")
        if typ == "private":
            label = "osoba prywatna"
        elif typ:
            label = str(typ)
    return {
        "phone_raw": phone,
        "description": _text(ad.get("description")),
        "seller_label": label,
    }


def _dig(node: Any, *keys: str) -> Any:
    for key in keys:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


def _money(value: Any) -> int | None:
    if isinstance(value, dict):
        amount = value.get("value")
        return int(amount) if isinstance(amount, (int, float)) and amount > 0 else None
    if isinstance(value, (int, float)) and value > 0:
        return int(value)
    return None


def _location(location: Any) -> str | None:
    """Sklada miasto, dzielnice, ulice i wojewodztwo w jeden ciag rozdzielony przecinkami.

    Ulica trafia TUTAJ, a nie do osobnego pola, bo normalize_location() i tak wyluskuje
    ja z tego ciagu po przedrostku "ul." i wpisuje do Listing.street. Trzymanie jej obok
    wymagaloby nowej instalacji przez caly pipeline dla danych, ktore juz maja droge.
    Nazwa z Otodomu przychodzi z gotowym przedrostkiem, wiec nie doklejamy drugiego."""
    address = _dig(location, "address") if isinstance(location, dict) else None
    if not isinstance(address, dict):
        return None
    parts = []
    city = address.get("city")
    if isinstance(city, dict) and city.get("name"):
        parts.append(str(city["name"]))
    district = _district(location)
    if district:
        parts.append(district)
    street = _street(location)
    if street:
        parts.append(street if _STREET_PREFIXED.match(street) else f"ul. {street}")
    province = address.get("province")
    if isinstance(province, dict) and province.get("name"):
        parts.append(str(province["name"]))
    return ", ".join(parts) or None


def _district(location: Any) -> str | None:
    locations = _dig(location, "reverseGeocoding", "locations")
    if not isinstance(locations, list):
        return None
    for entry in locations:
        if isinstance(entry, dict) and entry.get("locationLevel") == "district":
            name = entry.get("name")
            if name:
                return str(name)
    return None


def _street(location: Any) -> str | None:
    street = _dig(location, "address", "street") if isinstance(location, dict) else None
    if isinstance(street, dict) and street.get("name"):
        return str(street["name"])
    return None


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = re.sub(r"<[^>]+>", " ", value)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or None
