/**
 * Spotkania: umawianie po rozmowie, kalendarz i zamykanie po fakcie.
 * Zwraca rekordy z tabeli meetings wzbogacone o dane leada, kontaktu i ogłoszenia.
 *
 * Osobna tabela, a nie kolumny w leads, bo jeden właściciel miewa kilka spotkań:
 * pierwsze oglądanie, drugie z małżonkiem, trzecie po obniżce ceny. Kolumny
 * przechowałyby wyłącznie ostatnie i zjadłyby historię, na której stoi cała
 * sprawozdawczość tej aplikacji.
 *
 * Kalendarz łączy dwa źródła terminów: spotkania z tej tabeli oraz oddzwonienia,
 * czyli leady ze statusem callback, które datę mają od dawna w leads.next_step_at
 * i do tej pory nikt jej nigdzie nie widział.
 */

import { sql } from "@/lib/db";
import { BadRequest } from "@/lib/guards";

export const MEETING_OUTCOMES = ["contract", "thinking", "failed"] as const;
export type MeetingOutcome = (typeof MEETING_OUTCOMES)[number];

const OUTCOME_TO_LEAD_STATUS: Record<MeetingOutcome, string> = {
  contract: "contract",
  thinking: "callback",
  failed: "lost",
};

export type CalendarEntry = {
  kind: "meeting" | "callback";
  id: number;
  leadId: number;
  startsAt: string;
  name: string | null;
  phone: string | null;
  address: string | null;
  note: string | null;
  listingUrl: string | null;
  price: number | null;
  outcome: string | null;
  past: boolean;
};

export async function bookMeeting(
  leadId: number,
  input: { startsAt: string; address: string | null; note: string | null },
) {
  return sql.begin(async (tx) => {
    const [lead] = await tx<Array<{ id: number }>>`
      SELECT id FROM leads WHERE id = ${leadId} FOR UPDATE
    `;
    if (!lead) throw new BadRequest("Nie ma takiego leada.");

    const [meeting] = await tx`
      INSERT INTO meetings (lead_id, starts_at, address, note)
      VALUES (${leadId}, ${input.startsAt}, ${input.address}, ${input.note})
      RETURNING *
    `;

    await tx`
      UPDATE leads
         SET status = 'meeting',
             next_step = 'spotkanie',
             next_step_at = ${input.startsAt},
             updated_at = now()
       WHERE id = ${leadId}
    `;

    return meeting;
  });
}

export async function closeMeeting(
  meetingId: number,
  input: { outcome: MeetingOutcome; note: string | null },
) {
  if (input.outcome === "failed" && !input.note) {
    throw new BadRequest("Przy wyniku „nie wyszło” powód jest wymagany.");
  }
  return sql.begin(async (tx) => {
    const [meeting] = await tx<Array<{ id: number; lead_id: number }>>`
      SELECT id, lead_id FROM meetings WHERE id = ${meetingId} FOR UPDATE
    `;
    if (!meeting) throw new BadRequest("Nie ma takiego spotkania.");

    const [zapisane] = await tx`
      UPDATE meetings
         SET outcome = ${input.outcome},
             outcome_note = ${input.note},
             updated_at = now()
       WHERE id = ${meetingId}
      RETURNING *
    `;

    const status = OUTCOME_TO_LEAD_STATUS[input.outcome];
    await tx`
      UPDATE leads
         SET status = ${status},
             lost_reason = CASE WHEN ${status} = 'lost' THEN ${input.note} ELSE lost_reason END,
             next_step = CASE WHEN ${status} = 'callback' THEN 'oddzwonić po spotkaniu' ELSE NULL END,
             next_step_at = CASE WHEN ${status} = 'callback'
                                 THEN now() + interval '7 days' ELSE NULL END,
             updated_at = now()
       WHERE id = ${meeting.lead_id}
    `;

    return zapisane;
  });
}

export async function calendar(fromIso: string, toIso: string): Promise<CalendarEntry[]> {
  const spotkania = await sql<Array<Record<string, unknown>>>`
    SELECT m.id, m.lead_id, m.starts_at, m.address, m.note, m.outcome,
           c.name, c.phone_e164, l.url, l.price
      FROM meetings m
      JOIN leads le ON le.id = m.lead_id
      JOIN contacts c ON c.id = le.contact_id
      LEFT JOIN listings l ON l.id = le.listing_id
     WHERE m.starts_at >= ${fromIso} AND m.starts_at < ${toIso}
     ORDER BY m.starts_at
  `;

  const oddzwonienia = await sql<Array<Record<string, unknown>>>`
    SELECT le.id AS lead_id, le.next_step_at, le.next_step,
           c.name, c.phone_e164, l.url, l.price,
           l.city, l.district, l.street
      FROM leads le
      JOIN contacts c ON c.id = le.contact_id
      LEFT JOIN listings l ON l.id = le.listing_id
     WHERE le.status = 'callback'
       AND le.next_step_at IS NOT NULL
       AND le.next_step_at >= ${fromIso}
       AND le.next_step_at < ${toIso}
     ORDER BY le.next_step_at
  `;

  const teraz = Date.now();
  const wpisy: CalendarEntry[] = [];

  for (const row of spotkania) {
    const startsAt = new Date(row.starts_at as string).toISOString();
    wpisy.push({
      kind: "meeting",
      id: Number(row.id),
      leadId: Number(row.lead_id),
      startsAt,
      name: (row.name as string) ?? null,
      phone: (row.phone_e164 as string) ?? null,
      address: (row.address as string) ?? null,
      note: (row.note as string) ?? null,
      listingUrl: (row.url as string) ?? null,
      price: row.price === null || row.price === undefined ? null : Number(row.price),
      outcome: (row.outcome as string) ?? null,
      past: new Date(startsAt).getTime() < teraz,
    });
  }

  for (const row of oddzwonienia) {
    const startsAt = new Date(row.next_step_at as string).toISOString();
    wpisy.push({
      kind: "callback",
      id: Number(row.lead_id),
      leadId: Number(row.lead_id),
      startsAt,
      name: (row.name as string) ?? null,
      phone: (row.phone_e164 as string) ?? null,
      address: addressFromListing(row),
      note: (row.next_step as string) ?? null,
      listingUrl: (row.url as string) ?? null,
      price: row.price === null || row.price === undefined ? null : Number(row.price),
      outcome: null,
      past: new Date(startsAt).getTime() < teraz,
    });
  }

  return wpisy.sort((a, b) => a.startsAt.localeCompare(b.startsAt));
}

export function addressFromListing(row: Record<string, unknown>): string | null {
  const czesci = [row.street, row.district, row.city]
    .map((value) => (typeof value === "string" ? value.trim() : ""))
    .filter(Boolean);
  return czesci.length ? czesci.join(", ") : null;
}

/**
 * Skuteczność spotkań. Zwraca liczbę razem z wielkością próbki, a poniżej progu
 * oddaje enough=false zamiast procentu - reguła obowiązująca w tym projekcie
 * bez wyjątku, bo liczba policzona z sześciu spotkań jest gorsza niż jej brak.
 */
export async function meetingStats(minSample = 20) {
  const [row] = await sql<Array<{ zamkniete: number; umowy: number }>>`
    SELECT COUNT(*)::int AS zamkniete,
           COUNT(*) FILTER (WHERE outcome = 'contract')::int AS umowy
      FROM meetings
     WHERE outcome IS NOT NULL
  `;
  const sample = Number(row?.zamkniete ?? 0);
  const contracts = Number(row?.umowy ?? 0);
  return {
    sample,
    contracts,
    minSample,
    enough: sample >= minSample,
    rate: sample >= minSample ? Math.round((contracts / sample) * 100) : null,
  };
}
