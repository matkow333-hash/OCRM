"""Adapter OLX: wyszukiwarka mieszkań od osób prywatnych w Trójmieście.

Zwraca iterator RawListing z list wyników (sprzedaż i wynajem, miasto po mieście, strona po stronie).
Parsowanie idzie najpierw po stanie JSON osadzonym w stronie, a gdy go nie ma - po strukturze DOM.
Numer telefonu odsłania Playwright, opcjonalnie, wyłącznie na stronie oferty.
"""

from __future__ import annotations

import json
import re
from typing import Any, Iterator
from urllib.parse import urlencode, urljoin

from selectolax.parser import HTMLParser

from ..config import SearchConfig
from ..models import RawListing
from ..normalize import fold
from .base import Blocked, Fetcher

BASE_URL = "https://www.olx.pl"
CATEGORY_PATH = {
    "sale": "/nieruchomosci/mieszkania/sprzedaz/",
    "rent": "/nieruchomosci/mieszkania/wynajem/",
}
STATE_MARKERS = ("window.__PRERENDERED_STATE__=", "__PRERENDERED_STATE__ =", "__NEXT_DATA__")
PRIVATE_LABELS = ("osoba prywatna", "prywatne", "private")
BUSINESS_LABELS = ("firma", "business", "biuro", "deweloper")

CARD_SELECTORS = ('div[data-cy="l-card"]', 'div[data-testid="l-card"]')
TITLE_SELECTORS = ('h4', 'h6', '[data-cy="ad-card-title"]')
PRICE_SELECTORS = ('[data-testid="ad-price"]', 'p[data-testid="ad-price"]')
LOCATION_SELECTORS = ('[data-testid="location-date"]',)
DESCRIPTION_SELECTORS = ('[data-cy="ad_description"]', '[data-testid="ad_description"]')
SELLER_SELECTORS = ('[data-testid="trader-title"]', '[data-cy="seller_card"]')
PARAMS_SELECTORS = ('[data-testid="ad-parameters-container"]', '[data-cy="ad-parameters"]')

_ID_FROM_URL = re.compile(r"-ID([0-9A-Za-z]+)\.html")
_AREA_HINT = re.compile(r"\d+(?:[.,]\d+)?\s*m", re.IGNORECASE)
_ROOMS_HINT = re.compile(r"\bpoko|kawalerka", re.IGNORECASE)
_FLOOR_HINT = re.compile(r"piętro|parter|suterena", re.IGNORECASE)


class OlxAdapter:
    name = "olx"

    def __init__(self, fetcher: Fetcher | None = None, phone_reader=None) -> None:
        self._fetcher = fetcher
        self._phone_reader = phone_reader
        self.pages_fetched = 0

    def search(self, cfg: SearchConfig) -> Iterator[RawListing]:
        fetcher = self._fetcher or Fetcher(cfg.user_agent, cfg.delay_seconds)
        owns_fetcher = self._fetcher is None
        phone_reader = self._phone_reader
        if phone_reader is None and cfg.fetch_phones:
            phone_reader = PlaywrightPhoneReader(cfg.user_agent, cfg.delay_seconds)
        seen: set[str] = set()
        try:
            for deal_type in cfg.deal_types:
                for city in cfg.cities:
                    for raw in self._search_city(fetcher, cfg, deal_type, city, seen):
                        if cfg.fetch_details:
                            self._enrich(fetcher, raw)
                        if cfg.fetch_phones and not raw.phone_raw and phone_reader is not None:
                            raw.phone_raw = phone_reader.read(raw.url)
                        yield raw
        finally:
            if phone_reader is not None and hasattr(phone_reader, "close"):
                phone_reader.close()
            if owns_fetcher:
                fetcher.close()

    def _search_city(
        self,
        fetcher: Fetcher,
        cfg: SearchConfig,
        deal_type: str,
        city: str,
        seen: set[str],
    ) -> Iterator[RawListing]:
        for page in range(1, cfg.max_pages + 1):
            url = build_search_url(deal_type, city, cfg, page)
            html = fetcher.get(url)
            self.pages_fetched += 1
            listings = parse_search_page(html, deal_type)
            if not listings:
                return
            for raw in listings:
                if raw.source_id in seen:
                    continue
                seen.add(raw.source_id)
                yield raw

    def _enrich(self, fetcher: Fetcher, raw: RawListing) -> None:
        try:
            html = fetcher.get(raw.url)
        except Blocked:
            raise
        detail = parse_offer_page(html)
        raw.description = detail.get("description") or raw.description
        raw.seller_label = detail.get("seller_label") or raw.seller_label
        raw.phone_raw = detail.get("phone_raw") or raw.phone_raw
        raw.area_raw = raw.area_raw or detail.get("area_raw")
        raw.rooms_raw = raw.rooms_raw or detail.get("rooms_raw")
        raw.floor_raw = raw.floor_raw or detail.get("floor_raw")


def build_search_url(deal_type: str, city: str, cfg: SearchConfig, page: int = 1) -> str:
    if deal_type not in CATEGORY_PATH:
        raise ValueError(f"Nieznany deal_type: {deal_type}")
    limits = cfg.filter_for(deal_type)
    params = {
        "search[order]": "created_at:desc",
        "search[filter_enum_private_business][0]": "private",
        "search[filter_float_price:from]": limits.price_min,
        "search[filter_float_price:to]": limits.price_max,
        "search[filter_float_m:from]": int(limits.area_min),
        "search[filter_float_m:to]": int(limits.area_max),
    }
    if page > 1:
        params["page"] = page
    path = f"{CATEGORY_PATH[deal_type]}{fold(city)}/"
    return f"{urljoin(BASE_URL, path)}?{urlencode(params)}"


def parse_search_page(html: str, deal_type: str) -> list[RawListing]:
    state = extract_state(html)
    if state is not None:
        ads = find_ads(state)
        listings = [ad_to_raw(ad, deal_type) for ad in ads]
        listings = [item for item in listings if item is not None]
        if listings:
            return listings
    return parse_search_dom(html, deal_type)


def extract_state(html: str) -> Any | None:
    for marker in STATE_MARKERS:
        index = html.find(marker)
        while index != -1:
            start = html.find("=", index + len(marker) - 1)
            if marker == "__NEXT_DATA__":
                start = html.find(">", index)
            if start == -1:
                break
            payload = _decode_json_at(html, start + 1)
            if payload is not None:
                return payload
            index = html.find(marker, index + 1)
    return None


def _decode_json_at(html: str, start: int) -> Any | None:
    decoder = json.JSONDecoder()
    cursor = start
    while cursor < len(html) and html[cursor] in " \t\r\n":
        cursor += 1
    if cursor >= len(html) or html[cursor] not in '{["':
        return None
    try:
        value, _ = decoder.raw_decode(html, cursor)
    except ValueError:
        return None
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return None
    return value


def find_ads(state: Any) -> list[dict]:
    """Szuka w stanie strony najdłuższej listy słowników wyglądających na ogłoszenia."""
    best: list[dict] = []
    stack: list[Any] = [state]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            stack.extend(node.values())
        elif isinstance(node, list):
            candidates = [item for item in node if _looks_like_ad(item)]
            if len(candidates) > len(best):
                best = candidates
            stack.extend(item for item in node if isinstance(item, (dict, list)))
    return best


def _looks_like_ad(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    has_url = isinstance(item.get("url"), str) and ".html" in item["url"]
    has_id = "id" in item
    has_title = isinstance(item.get("title"), str)
    return has_url and has_id and has_title


def ad_to_raw(ad: dict, deal_type: str) -> RawListing | None:
    url = ad.get("url") or ""
    if not url:
        return None
    if url.startswith("/"):
        url = urljoin(BASE_URL, url)
    source_id = str(ad.get("id") or _id_from_url(url) or "")
    if not source_id:
        return None
    params = _params_map(ad.get("params"))
    location = ad.get("location") or {}
    contact = ad.get("contact") or {}
    raw = RawListing(
        source="olx",
        source_id=source_id,
        url=url,
        deal_type=deal_type,
        title=ad.get("title"),
        description=ad.get("description"),
        price_raw=_price_from(ad, params),
        area_raw=params.get("m"),
        rooms_raw=params.get("rooms"),
        floor_raw=params.get("floor_select") or params.get("floor"),
        location_raw=_location_from(location),
        phone_raw=contact.get("phone") if isinstance(contact, dict) else None,
        seller_label=_seller_label_from(ad),
        posted_at_raw=ad.get("created_time") or ad.get("last_refresh_time"),
    )
    return raw


def _id_from_url(url: str) -> str | None:
    match = _ID_FROM_URL.search(url)
    return match.group(1) if match else None


def _params_map(params: Any) -> dict[str, str]:
    result: dict[str, str] = {}
    if not isinstance(params, list):
        return result
    for entry in params:
        if not isinstance(entry, dict):
            continue
        key = entry.get("key") or entry.get("name")
        value = entry.get("value")
        if isinstance(value, dict):
            value = value.get("label") or value.get("value") or value.get("key")
        if key and value is not None:
            result[str(key)] = str(value)
    return result


def _price_from(ad: dict, params: dict[str, str]) -> str | None:
    if "price" in params:
        return params["price"]
    price = ad.get("price")
    if isinstance(price, dict):
        for key in ("displayValue", "value", "regularPrice", "amount"):
            if price.get(key) is not None:
                candidate = price[key]
                if isinstance(candidate, dict):
                    candidate = candidate.get("value") or candidate.get("displayValue")
                return str(candidate)
    if price is not None:
        return str(price)
    return None


def _location_from(location: Any) -> str | None:
    if not isinstance(location, dict):
        return str(location) if location else None
    parts = []
    for key in ("city", "district", "region"):
        value = location.get(key)
        if isinstance(value, dict):
            value = value.get("name")
        if value:
            parts.append(str(value))
    return ", ".join(parts) or None


def _seller_label_from(ad: dict) -> str | None:
    for key in ("business", "sellerType", "seller_type", "user_label"):
        value = ad.get(key)
        if isinstance(value, bool):
            return "firma" if value else "osoba prywatna"
        if isinstance(value, str) and value:
            return value
    user = ad.get("user")
    if isinstance(user, dict):
        if isinstance(user.get("isBusiness"), bool):
            return "firma" if user["isBusiness"] else "osoba prywatna"
        if user.get("company_name"):
            return "firma"
    return None


def parse_search_dom(html: str, deal_type: str) -> list[RawListing]:
    tree = HTMLParser(html)
    cards = []
    for selector in CARD_SELECTORS:
        cards = tree.css(selector)
        if cards:
            break
    listings: list[RawListing] = []
    for card in cards:
        link = card.css_first("a[href]")
        if link is None:
            continue
        href = link.attributes.get("href") or ""
        if not href:
            continue
        url = urljoin(BASE_URL, href)
        source_id = _id_from_url(url)
        if not source_id:
            continue
        listings.append(
            RawListing(
                source="olx",
                source_id=source_id,
                url=url,
                deal_type=deal_type,
                title=_text(card, TITLE_SELECTORS),
                price_raw=_text(card, PRICE_SELECTORS),
                location_raw=_first_segment(_text(card, LOCATION_SELECTORS)),
                posted_at_raw=_last_segment(_text(card, LOCATION_SELECTORS)),
            )
        )
    return listings


def parse_offer_page(html: str) -> dict[str, str | None]:
    tree = HTMLParser(html)
    detail: dict[str, str | None] = {
        "description": _text(tree, DESCRIPTION_SELECTORS),
        "seller_label": _seller_label_from_dom(tree),
        "phone_raw": _phone_from_dom(tree),
        "area_raw": None,
        "rooms_raw": None,
        "floor_raw": None,
    }
    for value in _param_texts(tree):
        if detail["area_raw"] is None and _AREA_HINT.search(value):
            detail["area_raw"] = value
        elif detail["rooms_raw"] is None and _ROOMS_HINT.search(value):
            detail["rooms_raw"] = value
        elif detail["floor_raw"] is None and _FLOOR_HINT.search(value):
            detail["floor_raw"] = value
    return detail


def _param_texts(tree: HTMLParser) -> list[str]:
    for selector in PARAMS_SELECTORS:
        container = tree.css_first(selector)
        if container is not None:
            return [node.text(strip=True) for node in container.css("p, li, span") if node.text(strip=True)]
    return []


def _seller_label_from_dom(tree: HTMLParser) -> str | None:
    label = _text(tree, SELLER_SELECTORS)
    if label:
        return label
    body = tree.text(separator=" ", strip=True).lower() if tree.body else ""
    for marker in PRIVATE_LABELS:
        if marker in body:
            return "osoba prywatna"
    for marker in BUSINESS_LABELS:
        if marker in body:
            return "firma"
    return None


def _phone_from_dom(tree: HTMLParser) -> str | None:
    link = tree.css_first('a[href^="tel:"]')
    if link is not None:
        return (link.attributes.get("href") or "")[4:] or None
    node = tree.css_first('[data-testid="contact-phone"]')
    return node.text(strip=True) if node is not None else None


def _text(node, selectors: tuple[str, ...]) -> str | None:
    for selector in selectors:
        found = node.css_first(selector)
        if found is not None:
            text = found.text(separator=" ", strip=True)
            if text:
                return text
    return None


def _first_segment(value: str | None) -> str | None:
    return value.split(" - ")[0].strip() if value else None


def _last_segment(value: str | None) -> str | None:
    if not value or " - " not in value:
        return None
    return value.split(" - ")[-1].strip()


class PlaywrightPhoneReader:
    """Odsłania numer na stronie oferty jednym kliknięciem w 'Pokaż numer'."""

    SHOW_PHONE_SELECTORS = (
        '[data-testid="show-phone"]',
        'button[data-cy="ad-contact-phone"]',
        'text="Pokaż numer"',
    )
    PHONE_SELECTORS = (
        '[data-testid="contact-phone"]',
        'a[href^="tel:"]',
    )

    def __init__(self, user_agent: str, delay_seconds: tuple[float, float]) -> None:
        self.user_agent = user_agent
        self.delay_seconds = delay_seconds
        self._playwright = None
        self._browser = None

    def _ensure_browser(self):
        if self._browser is not None:
            return self._browser
        from playwright.sync_api import sync_playwright

        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=True)
        return self._browser

    def read(self, url: str) -> str | None:
        import random
        import time

        try:
            browser = self._ensure_browser()
        except Exception:
            return None
        context = browser.new_context(user_agent=self.user_agent, locale="pl-PL")
        page = context.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(random.uniform(*self.delay_seconds))
            for selector in self.SHOW_PHONE_SELECTORS:
                button = page.query_selector(selector)
                if button is not None:
                    button.click()
                    page.wait_for_timeout(2000)
                    break
            for selector in self.PHONE_SELECTORS:
                node = page.query_selector(selector)
                if node is None:
                    continue
                href = node.get_attribute("href") or ""
                if href.startswith("tel:"):
                    return href[4:]
                text = (node.inner_text() or "").strip()
                if text:
                    return text
            return None
        except Exception:
            return None
        finally:
            context.close()

    def close(self) -> None:
        if self._browser is not None:
            self._browser.close()
            self._browser = None
        if self._playwright is not None:
            self._playwright.stop()
            self._playwright = None
