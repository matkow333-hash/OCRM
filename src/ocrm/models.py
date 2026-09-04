"""Dataclasses przepływające przez pipeline: RawListing, Listing, Contact, Lead.

RawListing to surowe pola prosto z portalu. Listing to rekord gotowy do zapisu w SQLite.
"""

from __future__ import annotations

from dataclasses import dataclass, field

SELLER_TYPES = ("private", "agency", "unknown")
LEAD_STATUSES = (
    "new",
    "called_no_answer",
    "talked",
    "callback",
    "meeting",
    "contract",
    "lost",
    "dnc",
)
CALL_OUTCOMES = ("no_answer", "talked", "refused", "callback", "meeting")


@dataclass
class RawListing:
    source: str
    source_id: str
    url: str
    deal_type: str
    title: str | None = None
    description: str | None = None
    price_raw: str | None = None
    area_raw: str | None = None
    location_raw: str | None = None
    phone_raw: str | None = None
    seller_label: str | None = None
    posted_at_raw: str | None = None
    rooms_raw: str | None = None
    floor_raw: str | None = None
    extra: dict = field(default_factory=dict)


@dataclass
class Listing:
    source: str
    source_id: str
    url: str
    deal_type: str
    city: str | None = None
    district: str | None = None
    street: str | None = None
    price: int | None = None
    area_m2: float | None = None
    rooms: int | None = None
    floor: int | None = None
    title: str | None = None
    description: str | None = None
    content_hash: str | None = None
    phone_e164: str | None = None
    seller_type: str = "unknown"
    agency_score: float = 0.0
    dedup_group: str | None = None
    first_seen_at: str | None = None
    last_seen_at: str | None = None
    is_active: int = 1


@dataclass
class Contact:
    phone_e164: str
    name: str | None = None
    do_not_call: int = 0
    do_not_call_at: str | None = None
    note: str | None = None
    created_at: str | None = None
    id: int | None = None


@dataclass
class Lead:
    contact_id: int
    listing_id: int | None = None
    status: str = "new"
    next_step: str | None = None
    next_step_at: str | None = None
    lost_reason: str | None = None
    contract_ends_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    id: int | None = None
