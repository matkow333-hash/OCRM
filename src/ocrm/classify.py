"""Rozpoznanie pośrednika: zwraca agency_score 0.0-1.0 oraz seller_type.

Sygnały i ich wagi pochodzą z config.yaml, nie z kodu - będą strojone na realnych danych.
PhoneContext niesie to, czego nie widać w pojedynczym ogłoszeniu: ile aktywnych ofert
i ile dzielnic wisi pod tym samym numerem.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass

from .config import ClassifySettings
from .models import Listing
from .normalize import fold

NEGATION_WINDOW = 14
NEGATIONS = ("bez ", "brak ", "nie pobieram", "zero ")
SECTION_MARKERS = ("•", "▪", "★", "✔", "- ", "–", "\n\n")


@dataclass(frozen=True)
class PhoneContext:
    active_listings: int = 0
    districts: int = 0


def phone_context(conn: sqlite3.Connection, phone: str | None, exclude_id: int | None = None) -> PhoneContext:
    if not phone:
        return PhoneContext()
    params: list[object] = [phone]
    clause = "WHERE phone_e164 = ? AND is_active = 1"
    if exclude_id is not None:
        clause += " AND id <> ?"
        params.append(exclude_id)
    row = conn.execute(
        f"SELECT COUNT(*) AS listings, COUNT(DISTINCT district) AS districts FROM listings {clause}",
        params,
    ).fetchone()
    return PhoneContext(active_listings=row["listings"] or 0, districts=row["districts"] or 0)


def agency_score(listing: Listing, cfg: ClassifySettings, context: PhoneContext | None = None) -> float:
    context = context or PhoneContext()
    weights = cfg.weights
    score = cfg.base_score
    haystack = fold(" ".join(filter(None, (listing.title, listing.description))))

    portal = _portal_flag(listing)
    if portal == "agency":
        score += weights["portal_flag_agency"]
    elif portal == "private":
        score += weights["portal_flag_private"]

    hits = _keyword_hits(haystack, cfg.keywords_agency)
    score += min(hits * weights["keyword_hit"], weights["keyword_hit_max"])

    private_hits = _keyword_hits(haystack, cfg.keywords_private, allow_negated=True)
    score += max(private_hits * weights["keyword_private_hit"], weights["keyword_private_max"])

    if context.active_listings >= cfg.phone_listings_agency_cutoff:
        score += weights["phone_many_listings"]
    if context.districts > cfg.phone_districts_agency_cutoff:
        score += weights["phone_many_districts"]

    if _looks_like_brochure(listing.description, cfg.long_description_chars):
        score += weights["long_description"]

    return round(min(max(score, 0.0), 1.0), 3)


def seller_type_for(score: float, cfg: ClassifySettings) -> str:
    if score >= cfg.agency_threshold:
        return "agency"
    if score <= cfg.private_threshold:
        return "private"
    return "unknown"


def classify(listing: Listing, cfg: ClassifySettings, context: PhoneContext | None = None) -> Listing:
    listing.agency_score = agency_score(listing, cfg, context)
    listing.seller_type = seller_type_for(listing.agency_score, cfg)
    return listing


def _portal_flag(listing: Listing) -> str | None:
    label = listing.seller_type
    return label if label in {"agency", "private"} else None


def _keyword_hits(haystack: str, keywords: list[str], allow_negated: bool = False) -> int:
    if not haystack:
        return 0
    hits = 0
    for keyword in keywords:
        needle = fold(keyword)
        if not needle:
            continue
        for match in re.finditer(re.escape(needle), haystack):
            if not allow_negated and _is_negated(haystack, match.start()):
                continue
            hits += 1
            break
    return hits


def _is_negated(haystack: str, position: int) -> bool:
    window = haystack[max(0, position - NEGATION_WINDOW) : position]
    return any(marker in window for marker in NEGATIONS)


def _looks_like_brochure(description: str | None, threshold: int) -> bool:
    if not description or len(description) < threshold:
        return False
    return sum(description.count(marker) for marker in SECTION_MARKERS) >= 3
