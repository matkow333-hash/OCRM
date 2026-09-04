"""Normalizacja surowych pól ogłoszenia: telefon, cena, metraż, pokoje, piętro, adres.

Zwraca wartości gotowe do zapisu: telefon w E.164 dla Polski, cena jako int,
metraż jako float, lokalizacja rozbita na miasto / dzielnicę / ulicę.
Funkcja normalize_listing() zamienia RawListing na Listing.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone

from .models import Listing, RawListing

TRICITY = {
    "gdansk": "Gdańsk",
    "sopot": "Sopot",
    "gdynia": "Gdynia",
}

_NON_DIGITS = re.compile(r"\D+")
_PRICE_TOKEN = re.compile(r"\d[\d\s .,]*")
_AREA_TOKEN = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:m2|m²|m\b)", re.IGNORECASE)
_ROOMS_TOKEN = re.compile(r"(\d+)\s*(?:pok|pokoj|pokój|pokoje|pokoi|room)", re.IGNORECASE)
_FLOOR_TOKEN = re.compile(r"(-?\d+)")
_STREET_PREFIX = re.compile(r"^(?:ul\.?|ulica|al\.?|aleja|aleje|os\.?|osiedle|pl\.?|plac)\s+", re.IGNORECASE)
_PRICE_NOISE = ("do negocjacji", "zapytaj o cenę", "zapytaj o cene", "cena do uzgodnienia")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def fold(text: str) -> str:
    stripped = unicodedata.normalize("NFKD", text.replace("ł", "l").replace("Ł", "L"))
    return "".join(c for c in stripped if not unicodedata.combining(c)).lower().strip()


def normalize_phone(raw: str | None) -> str | None:
    if not raw:
        return None
    candidate = raw.strip()
    if candidate.count("+") > 1:
        return None
    digits = _NON_DIGITS.sub("", candidate)
    if not digits:
        return None
    if digits.startswith("0048"):
        digits = digits[4:]
    elif digits.startswith("48") and len(digits) == 11:
        digits = digits[2:]
    elif digits.startswith("0") and len(digits) == 10:
        digits = digits[1:]
    if len(digits) != 9 or digits[0] in "01":
        return None
    return f"+48{digits}"


def normalize_price(raw: str | int | float | None) -> int | None:
    if raw is None:
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return int(raw) if raw > 0 else None
    text = raw.strip().lower()
    if not text:
        return None
    if any(noise in text for noise in _PRICE_NOISE) and not _PRICE_TOKEN.search(text):
        return None
    match = _PRICE_TOKEN.search(text)
    if not match:
        return None
    token = match.group(0).replace(" ", "").replace(" ", "")
    if "," in token:
        token = token.split(",")[0]
    if token.count(".") == 1 and len(token.split(".")[1]) in (1, 2):
        token = token.split(".")[0]
    token = token.replace(".", "")
    if not token.isdigit():
        return None
    value = int(token)
    return value if value > 0 else None


def normalize_area(raw: str | int | float | None) -> float | None:
    if raw is None:
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return round(float(raw), 2) if raw > 0 else None
    text = raw.replace(" ", " ").strip()
    if not text:
        return None
    match = _AREA_TOKEN.search(text)
    if match:
        token = match.group(1)
    else:
        fallback = re.search(r"\d+(?:[.,]\d+)?", text)
        if not fallback:
            return None
        token = fallback.group(0)
    value = float(token.replace(",", "."))
    return round(value, 2) if value > 0 else None


def normalize_rooms(raw: str | int | None) -> int | None:
    if raw is None:
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw if raw > 0 else None
    text = raw.strip().lower()
    if not text:
        return None
    if "kawaler" in text or "studio" in text:
        return 1
    match = _ROOMS_TOKEN.search(text)
    if not match:
        match = re.search(r"^\s*(\d+)\s*$", text)
    if not match:
        return None
    value = int(match.group(1))
    return value if 0 < value <= 20 else None


def normalize_floor(raw: str | int | None) -> int | None:
    if raw is None:
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw
    text = fold(raw)
    if not text:
        return None
    if "parter" in text:
        return 0
    if "suterena" in text or "piwnica" in text:
        return -1
    if "poddasze" in text and not _FLOOR_TOKEN.search(text):
        return None
    match = _FLOOR_TOKEN.search(text)
    if not match:
        return None
    value = int(match.group(1))
    return value if -2 <= value <= 50 else None


def normalize_location(raw: str | None) -> tuple[str | None, str | None, str | None]:
    if not raw:
        return None, None, None
    parts = [p.strip() for p in re.split(r"[,/]", raw) if p.strip()]
    if not parts:
        return None, None, None
    city = TRICITY.get(fold(parts[0]), parts[0])
    district = None
    street = None
    for part in parts[1:]:
        if _STREET_PREFIX.match(part):
            if street is None:
                street = _STREET_PREFIX.sub("", part).strip()
            continue
        if district is None and fold(part) not in {"pomorskie", "polska", "mieszkania"}:
            district = part
    return city, district, street


def normalize_listing(raw: RawListing, seen_at: str | None = None) -> Listing:
    stamp = seen_at or utc_now()
    city, district, street = normalize_location(raw.location_raw)
    return Listing(
        source=raw.source,
        source_id=str(raw.source_id),
        url=raw.url,
        deal_type=raw.deal_type,
        city=city,
        district=district,
        street=street,
        price=normalize_price(raw.price_raw),
        area_m2=normalize_area(raw.area_raw),
        rooms=normalize_rooms(raw.rooms_raw),
        floor=normalize_floor(raw.floor_raw),
        title=(raw.title or "").strip() or None,
        description=(raw.description or "").strip() or None,
        phone_e164=normalize_phone(raw.phone_raw),
        first_seen_at=stamp,
        last_seen_at=stamp,
        is_active=1,
    )
