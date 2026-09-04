/**
 * Ranking porannej listy i sugerowane otwarcie rozmowy.
 * Zwraca do LIST_SIZE pozycji: jeden rekord z grupy duplikatów, bez pośredników,
 * bez numerów oznaczonych do_not_call, z zaległymi follow-upami na samej górze.
 */

import { sql, LIST_SIZE } from "./db";

export const WEIGHTS = {
  overdueFollowUp: 100,
  freshToday: 40,
  privateSeller: 30,
  unknownSeller: 5,
  tiredOwner: 15,
  hasPhone: 10,
};

export const TIRED_OWNER_DAYS = 10;
export const CALL_COOLDOWN_DAYS = 14;

export type Opener = "A" | "B" | "C";

export type TodayItem = {
  leadId: number;
  contactId: number;
  listingId: number | null;
  name: string;
  phone: string;
  city: string | null;
  district: string | null;
  street: string | null;
  price: number | null;
  areaM2: number | null;
  rooms: number | null;
  dealType: string;
  url: string;
  title: string | null;
  ageDays: number;
  sellerType: string;
  status: string;
  nextStepAt: string | null;
  overdue: boolean;
  opener: Opener;
  score: number;
};

export function openerFor(ageDays: number, hasHistory: boolean): Opener {
  if (hasHistory) return "B";
  if (ageDays >= TIRED_OWNER_DAYS) return "C";
  return "A";
}

export async function todayList(limit = LIST_SIZE): Promise<TodayItem[]> {
  const rows = await sql<Array<Record<string, unknown>>>`
    WITH primary_listing AS (
      SELECT DISTINCT ON (COALESCE(dedup_group, 'id:' || id::text))
             id, source, source_id, url, deal_type, city, district, street, price,
             area_m2, rooms, title, phone_e164, seller_type, first_seen_at, dedup_group
        FROM listings
       WHERE is_active = TRUE
         AND seller_type <> 'agency'
         AND phone_e164 IS NOT NULL
       ORDER BY COALESCE(dedup_group, 'id:' || id::text),
                first_seen_at ASC,
                (CASE WHEN price IS NULL THEN 0 ELSE 1 END
                 + CASE WHEN area_m2 IS NULL THEN 0 ELSE 1 END
                 + CASE WHEN rooms IS NULL THEN 0 ELSE 1 END
                 + CASE WHEN street IS NULL THEN 0 ELSE 1 END) DESC
    ),
    last_call AS (
      SELECT lead_id,
             MAX(called_at) AS called_at,
             BOOL_OR(outcome = 'callback') AS has_callback,
             COUNT(*)::int AS calls
        FROM call_log
       GROUP BY lead_id
    )
    SELECT l.id             AS lead_id,
           c.id             AS contact_id,
           pl.id            AS listing_id,
           COALESCE(c.name, 'właściciel') AS name,
           c.phone_e164     AS phone,
           pl.city, pl.district, pl.street, pl.price, pl.area_m2, pl.rooms,
           pl.deal_type, pl.url, pl.title, pl.seller_type,
           l.status, l.next_step_at,
           EXTRACT(DAY FROM now() - pl.first_seen_at)::int AS age_days,
           (l.next_step_at IS NOT NULL AND l.next_step_at <= now()) AS overdue,
           COALESCE(lc.calls, 0) AS calls,
           lc.called_at AS last_called_at,
           COALESCE(lc.has_callback, FALSE) AS has_callback
      FROM leads l
      JOIN contacts c ON c.id = l.contact_id
      LEFT JOIN primary_listing pl ON pl.id = l.listing_id
      LEFT JOIN last_call lc ON lc.lead_id = l.id
     WHERE c.do_not_call = FALSE
       AND l.status NOT IN ('dnc', 'lost', 'contract')
       AND (pl.id IS NOT NULL OR l.next_step_at IS NOT NULL)
  `;

  return rows
    .map(toItem)
    .filter((item) => item.score > 0)
    .sort((a, b) => b.score - a.score || a.ageDays - b.ageDays)
    .slice(0, limit);
}

function toItem(row: Record<string, unknown>): TodayItem {
  const ageDays = Number(row.age_days ?? 0);
  const overdue = Boolean(row.overdue);
  const calls = Number(row.calls ?? 0);
  const hasCallback = Boolean(row.has_callback);
  const lastCalledAt = row.last_called_at ? new Date(row.last_called_at as string) : null;
  const sellerType = String(row.seller_type ?? "unknown");

  let score = 0;
  if (overdue) score += WEIGHTS.overdueFollowUp;
  if (ageDays <= 0) score += WEIGHTS.freshToday;
  if (sellerType === "private") score += WEIGHTS.privateSeller;
  if (sellerType === "unknown") score += WEIGHTS.unknownSeller;
  if (ageDays >= TIRED_OWNER_DAYS) score += WEIGHTS.tiredOwner;
  if (row.phone) score += WEIGHTS.hasPhone;

  const daysSinceCall = lastCalledAt
    ? (Date.now() - lastCalledAt.getTime()) / 86_400_000
    : Number.POSITIVE_INFINITY;
  if (daysSinceCall < CALL_COOLDOWN_DAYS && !hasCallback && !overdue) score = 0;

  return {
    leadId: Number(row.lead_id),
    contactId: Number(row.contact_id),
    listingId: row.listing_id ? Number(row.listing_id) : null,
    name: String(row.name),
    phone: String(row.phone),
    city: (row.city as string) ?? null,
    district: (row.district as string) ?? null,
    street: (row.street as string) ?? null,
    price: row.price === null || row.price === undefined ? null : Number(row.price),
    areaM2: row.area_m2 === null || row.area_m2 === undefined ? null : Number(row.area_m2),
    rooms: row.rooms === null || row.rooms === undefined ? null : Number(row.rooms),
    dealType: String(row.deal_type ?? "sale"),
    url: String(row.url ?? ""),
    title: (row.title as string) ?? null,
    ageDays,
    sellerType,
    status: String(row.status),
    nextStepAt: row.next_step_at ? new Date(row.next_step_at as string).toISOString() : null,
    overdue,
    opener: openerFor(ageDays, calls > 0),
    score,
  };
}

export async function todayCounter(): Promise<{ made: number; target: number; meetings: number }> {
  const [row] = await sql<Array<{ calls_made: number; target: number; meetings_booked: number }>>`
    SELECT calls_made, target, meetings_booked
      FROM daily_stats WHERE day = CURRENT_DATE
  `;
  return {
    made: row?.calls_made ?? 0,
    target: row?.target ?? Number(process.env.DAILY_CALL_TARGET ?? 10),
    meetings: row?.meetings_booked ?? 0,
  };
}
