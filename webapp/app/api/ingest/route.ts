/**
 * POST /api/ingest — skaner z laptopa wrzuca tu ogłoszenia po klasyfikacji i dedupie.
 * Autoryzacja tokenem Bearer (INGEST_TOKEN), nie sesją użytkowniczki.
 * Zwraca { received, inserted, updated, leads_created }.
 */

import { NextResponse } from "next/server";
import { sql } from "@/lib/db";
import { ingestTokenValid } from "@/lib/auth";
import { jsonBody } from "@/lib/http";
import {
  BadRequest,
  DEAL_TYPES,
  SELLER_TYPES,
  oneOf,
  optionalText,
  optionalTimestamp,
} from "@/lib/guards";

export const maxDuration = 60;

type Incoming = {
  source: string;
  source_id: string;
  url: string;
  deal_type: string;
  city: string | null;
  district: string | null;
  street: string | null;
  price: number | null;
  area_m2: number | null;
  rooms: number | null;
  floor: number | null;
  title: string | null;
  description: string | null;
  content_hash: string | null;
  phone_e164: string | null;
  seller_type: string;
  agency_score: number;
  dedup_group: string | null;
  first_seen_at: string;
  last_seen_at: string;
  is_active: boolean;
};

export async function POST(request: Request) {
  if (!ingestTokenValid(request.headers.get("authorization"))) {
    return NextResponse.json({ error: "Brak lub zły token ingest." }, { status: 401 });
  }
  try {
    const body = await jsonBody(request);
    const raw = body.listings;
    if (!Array.isArray(raw)) throw new BadRequest("Pole listings musi być tablicą.");
    if (raw.length > 500) throw new BadRequest("Maksimum 500 ogłoszeń na jedno żądanie.");

    const parsed = raw.map(parseListing);
    let inserted = 0;
    let updated = 0;
    let leadsCreated = 0;

    for (const item of parsed) {
      const [row] = await sql<Array<{ id: number; created: boolean }>>`
        INSERT INTO listings (
          source, source_id, url, deal_type, city, district, street, price, area_m2,
          rooms, floor, title, description, content_hash, phone_e164, seller_type,
          agency_score, dedup_group, first_seen_at, last_seen_at, is_active
        ) VALUES (
          ${item.source}, ${item.source_id}, ${item.url}, ${item.deal_type}, ${item.city},
          ${item.district}, ${item.street}, ${item.price}, ${item.area_m2}, ${item.rooms},
          ${item.floor}, ${item.title}, ${item.description}, ${item.content_hash},
          ${item.phone_e164}, ${item.seller_type}, ${item.agency_score}, ${item.dedup_group},
          ${item.first_seen_at}, ${item.last_seen_at}, ${item.is_active}
        )
        ON CONFLICT (source, source_id) DO UPDATE SET
          url = EXCLUDED.url,
          city = COALESCE(EXCLUDED.city, listings.city),
          district = COALESCE(EXCLUDED.district, listings.district),
          street = COALESCE(EXCLUDED.street, listings.street),
          price = COALESCE(EXCLUDED.price, listings.price),
          area_m2 = COALESCE(EXCLUDED.area_m2, listings.area_m2),
          rooms = COALESCE(EXCLUDED.rooms, listings.rooms),
          floor = COALESCE(EXCLUDED.floor, listings.floor),
          title = COALESCE(EXCLUDED.title, listings.title),
          description = COALESCE(EXCLUDED.description, listings.description),
          content_hash = COALESCE(EXCLUDED.content_hash, listings.content_hash),
          phone_e164 = COALESCE(EXCLUDED.phone_e164, listings.phone_e164),
          seller_type = EXCLUDED.seller_type,
          agency_score = EXCLUDED.agency_score,
          dedup_group = COALESCE(EXCLUDED.dedup_group, listings.dedup_group),
          last_seen_at = EXCLUDED.last_seen_at,
          is_active = EXCLUDED.is_active
        RETURNING id, (xmax = 0) AS created
      `;
      if (row.created) inserted += 1;
      else updated += 1;

      if (item.phone_e164 && item.seller_type !== "agency" && item.is_active) {
        leadsCreated += await ensureLead(row.id, item.phone_e164);
      }
    }

    return NextResponse.json({
      data: { received: parsed.length, inserted, updated, leads_created: leadsCreated },
    });
  } catch (error) {
    if (error instanceof BadRequest) {
      return NextResponse.json({ error: error.message }, { status: 400 });
    }
    console.error(error);
    return NextResponse.json({ error: "Błąd zapisu ingestu." }, { status: 500 });
  }
}

async function ensureLead(listingId: number, phone: string): Promise<number> {
  const [contact] = await sql<Array<{ id: number; do_not_call: boolean }>>`
    INSERT INTO contacts (phone_e164) VALUES (${phone})
    ON CONFLICT (phone_e164) DO UPDATE SET phone_e164 = EXCLUDED.phone_e164
    RETURNING id, do_not_call
  `;
  if (contact.do_not_call) return 0;
  const created = await sql<Array<{ id: number }>>`
    INSERT INTO leads (contact_id, listing_id, status)
    VALUES (${contact.id}, ${listingId}, 'new')
    ON CONFLICT (contact_id, listing_id) DO NOTHING
    RETURNING id
  `;
  return created.length;
}

function parseListing(value: unknown): Incoming {
  if (!value || typeof value !== "object") throw new BadRequest("Element listings musi być obiektem.");
  const item = value as Record<string, unknown>;
  const text = (field: string, max = 20000) => optionalText(item[field], field, max);
  const required = (field: string) => {
    const parsed = text(field, 500);
    if (!parsed) throw new BadRequest(`Pole ${field} jest wymagane.`);
    return parsed;
  };
  return {
    source: required("source"),
    source_id: required("source_id"),
    url: required("url"),
    deal_type: oneOf(item.deal_type, DEAL_TYPES, "deal_type"),
    city: text("city", 120),
    district: text("district", 120),
    street: text("street", 200),
    price: numberOrNull(item.price, "price"),
    area_m2: numberOrNull(item.area_m2, "area_m2"),
    rooms: numberOrNull(item.rooms, "rooms"),
    floor: numberOrNull(item.floor, "floor"),
    title: text("title", 500),
    description: text("description"),
    content_hash: text("content_hash", 64),
    phone_e164: item.phone_e164 ? String(item.phone_e164) : null,
    seller_type: oneOf(item.seller_type ?? "unknown", SELLER_TYPES, "seller_type"),
    agency_score: numberOrNull(item.agency_score, "agency_score") ?? 0,
    dedup_group: text("dedup_group", 64),
    first_seen_at: optionalTimestamp(item.first_seen_at, "first_seen_at") ?? new Date().toISOString(),
    last_seen_at: optionalTimestamp(item.last_seen_at, "last_seen_at") ?? new Date().toISOString(),
    is_active: item.is_active === undefined ? true : Boolean(item.is_active),
  };
}

function numberOrNull(value: unknown, field: string): number | null {
  if (value === undefined || value === null || value === "") return null;
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) throw new BadRequest(`Pole ${field} musi być liczbą.`);
  return parsed;
}
