"""Łączenie tego samego mieszkania wiszącego na kilku portalach.

Zwraca dedup_group (UUID) dla ogłoszenia: istniejącą grupę, gdy któraś z trzech reguł
trafi w kandydata, albo nową. pick_primary() wybiera z grupy jeden rekord na poranną listę.
"""

from __future__ import annotations

import re
import sqlite3
import uuid
from dataclasses import dataclass

AREA_TOLERANCE_M2 = 1.0
PRICE_TOLERANCE = 0.03
SIMHASH_BITS = 64
SIMHASH_MAX_DISTANCE = 3
MIN_DESCRIPTION_CHARS = 200

_WORD = re.compile(r"[0-9a-ząćęłńóśźż]+", re.IGNORECASE)


@dataclass(frozen=True)
class Candidate:
    id: int
    dedup_group: str | None
    phone_e164: str | None
    street: str | None
    area_m2: float | None
    price: int | None
    content_hash: str | None


def simhash(text: str | None) -> int | None:
    tokens = _shingles(text)
    if not tokens:
        return None
    vector = [0] * SIMHASH_BITS
    for token in tokens:
        digest = _hash_token(token)
        for bit in range(SIMHASH_BITS):
            vector[bit] += 1 if digest >> bit & 1 else -1
    value = 0
    for bit in range(SIMHASH_BITS):
        if vector[bit] > 0:
            value |= 1 << bit
    return value


def content_hash(text: str | None) -> str | None:
    """Krótkie opisy zostają bez odcisku - na nich simhash zbyt łatwo skleiłby różne mieszkania."""
    if not text or len(text) < MIN_DESCRIPTION_CHARS:
        return None
    value = simhash(text)
    return f"{value:016x}" if value is not None else None


def hamming(left: str | None, right: str | None) -> int | None:
    if not left or not right:
        return None
    try:
        return bin(int(left, 16) ^ int(right, 16)).count("1")
    except ValueError:
        return None


def same_object(listing, candidate: Candidate) -> bool:
    if _phone_rule(listing, candidate):
        return True
    if _street_rule(listing, candidate):
        return True
    return _simhash_rule(listing, candidate)


def assign_group(conn: sqlite3.Connection, listing, listing_id: int | None = None) -> str:
    """Nadaje ogłoszeniu dedup_group i zwraca ją; scala z istniejącą grupą, gdy trafi reguła."""
    for candidate in _candidates(conn, listing, listing_id):
        if same_object(listing, candidate):
            group = candidate.dedup_group or str(uuid.uuid4())
            if candidate.dedup_group is None:
                conn.execute(
                    "UPDATE listings SET dedup_group = ? WHERE id = ?", (group, candidate.id)
                )
            return group
    return str(uuid.uuid4())


def pick_primary(rows: list) -> object | None:
    """Z grupy duplikatów wybiera rekord najstarszy i najbogatszy w dane."""
    if not rows:
        return None
    return sorted(rows, key=lambda row: (row["first_seen_at"], -_richness(row)))[0]


def _richness(row) -> int:
    fields = ("phone_e164", "price", "area_m2", "rooms", "floor", "street", "district", "description")
    return sum(1 for field in fields if _get(row, field) is not None)


def _get(row, field):
    try:
        return row[field]
    except (KeyError, IndexError, TypeError):
        return getattr(row, field, None)


def _candidates(conn: sqlite3.Connection, listing, listing_id: int | None) -> list[Candidate]:
    clauses = ["is_active = 1"]
    params: list[object] = []
    if listing_id is not None:
        clauses.append("id <> ?")
        params.append(listing_id)
    if listing.city:
        clauses.append("(city IS NULL OR city = ?)")
        params.append(listing.city)
    clauses.append("deal_type = ?")
    params.append(listing.deal_type)
    rows = conn.execute(
        f"""
        SELECT id, dedup_group, phone_e164, street, area_m2, price, content_hash
          FROM listings WHERE {' AND '.join(clauses)}
        """,
        params,
    ).fetchall()
    return [Candidate(*tuple(row)) for row in rows]


def _phone_rule(listing, candidate: Candidate) -> bool:
    if not listing.phone_e164 or listing.phone_e164 != candidate.phone_e164:
        return False
    return _area_close(listing.area_m2, candidate.area_m2) and _price_close(listing.price, candidate.price)


def _street_rule(listing, candidate: Candidate) -> bool:
    if listing.phone_e164 and candidate.phone_e164:
        return False
    if not listing.street or not candidate.street:
        return False
    if listing.street.strip().lower() != candidate.street.strip().lower():
        return False
    return _area_close(listing.area_m2, candidate.area_m2) and _price_close(listing.price, candidate.price)


def _simhash_rule(listing, candidate: Candidate) -> bool:
    distance = hamming(listing.content_hash, candidate.content_hash)
    return distance is not None and distance <= SIMHASH_MAX_DISTANCE


def _area_close(left: float | None, right: float | None) -> bool:
    if left is None or right is None:
        return False
    return abs(left - right) <= AREA_TOLERANCE_M2


def _price_close(left: int | None, right: int | None) -> bool:
    if left is None or right is None:
        return False
    if left == right:
        return True
    reference = max(abs(left), abs(right))
    return abs(left - right) / reference <= PRICE_TOLERANCE


def _shingles(text: str | None) -> list[str]:
    """Pojedyncze słowa dają odporność na drobne przeróbki, pary trzymają kolejność."""
    if not text:
        return []
    words = _WORD.findall(text.lower())
    pairs = [f"{words[i]} {words[i + 1]}" for i in range(len(words) - 1)]
    return words + pairs


def _hash_token(token: str) -> int:
    digest = 1469598103934665603
    for byte in token.encode("utf-8"):
        digest ^= byte
        digest = (digest * 1099511628211) & 0xFFFFFFFFFFFFFFFF
    return digest
