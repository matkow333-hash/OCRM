/**
 * Operacje na kontaktach, leadach i rejestrze połączeń.
 * Zwracają zapisany rekord albo rzucają wyjątek; walidacja wejścia siedzi w guards.ts.
 */

import { sql } from "./db";
import { CALL_OUTCOMES, LEAD_STATUSES } from "./guards";

export type CallInput = {
  outcome: (typeof CALL_OUTCOMES)[number];
  openerUsed?: string | null;
  objection?: string | null;
  note?: string | null;
};

export type StatusInput = {
  status: (typeof LEAD_STATUSES)[number];
  nextStep?: string | null;
  nextStepAt?: string | null;
  lostReason?: string | null;
};

const OUTCOME_TO_STATUS: Record<string, string | null> = {
  no_answer: "called_no_answer",
  talked: "talked",
  refused: "lost",
  callback: "callback",
  meeting: "meeting",
};

export async function logCall(leadId: number, input: CallInput) {
  return sql.begin(async (tx) => {
    const [lead] = await tx<Array<{ id: number; status: string }>>`
      SELECT id, status FROM leads WHERE id = ${leadId} FOR UPDATE
    `;
    if (!lead) throw new Error("Nie ma takiego leada.");

    const [call] = await tx`
      INSERT INTO call_log (lead_id, outcome, opener_used, objection, note)
      VALUES (${leadId}, ${input.outcome}, ${input.openerUsed ?? null},
              ${input.objection ?? null}, ${input.note ?? null})
      RETURNING *
    `;

    const nextStatus = OUTCOME_TO_STATUS[input.outcome];
    if (nextStatus) {
      const lostReason = input.outcome === "refused" ? (input.objection ?? "odmowa w rozmowie") : null;
      await tx`
        UPDATE leads
           SET status = ${nextStatus},
               lost_reason = COALESCE(${lostReason}, lost_reason),
               next_step_at = CASE WHEN ${input.outcome} = 'callback'
                                   THEN COALESCE(next_step_at, now() + interval '2 days')
                                   ELSE NULL END,
               updated_at = now()
         WHERE id = ${leadId}
      `;
    }

    await tx`
      INSERT INTO daily_stats (day, calls_made, target, meetings_booked)
      VALUES (CURRENT_DATE, 1, ${Number(process.env.DAILY_CALL_TARGET ?? 10)},
              ${input.outcome === "meeting" ? 1 : 0})
      ON CONFLICT (day) DO UPDATE
        SET calls_made = daily_stats.calls_made + 1,
            meetings_booked = daily_stats.meetings_booked
                              + ${input.outcome === "meeting" ? 1 : 0}
    `;

    return call;
  });
}

export async function updateStatus(leadId: number, input: StatusInput) {
  const [lead] = await sql`
    UPDATE leads
       SET status = ${input.status},
           next_step = ${input.nextStep ?? null},
           next_step_at = ${input.nextStepAt ?? null},
           lost_reason = ${input.lostReason ?? null},
           updated_at = now()
     WHERE id = ${leadId}
    RETURNING *
  `;
  if (!lead) throw new Error("Nie ma takiego leada.");
  if (input.status === "dnc") {
    await sql`
      UPDATE contacts SET do_not_call = TRUE, do_not_call_at = now()
       WHERE id = (SELECT contact_id FROM leads WHERE id = ${leadId})
    `;
  }
  return lead;
}

export async function markDoNotCall(contactId: number, note?: string | null) {
  return sql.begin(async (tx) => {
    const [contact] = await tx`
      UPDATE contacts
         SET do_not_call = TRUE, do_not_call_at = now(), note = COALESCE(${note ?? null}, note)
       WHERE id = ${contactId}
      RETURNING *
    `;
    if (!contact) throw new Error("Nie ma takiego kontaktu.");
    await tx`
      UPDATE leads SET status = 'dnc', next_step_at = NULL, updated_at = now()
       WHERE contact_id = ${contactId} AND status <> 'dnc'
    `;
    return contact;
  });
}

export async function listLeads(status?: string) {
  return sql<Array<Record<string, unknown>>>`
    SELECT l.id, l.status, l.next_step, l.next_step_at, l.lost_reason, l.updated_at,
           c.id AS contact_id, COALESCE(c.name, 'właściciel') AS name, c.phone_e164 AS phone,
           c.do_not_call,
           li.city, li.district, li.price, li.area_m2, li.rooms, li.url, li.deal_type,
           (l.next_step_at IS NOT NULL AND l.next_step_at <= now()) AS overdue,
           (SELECT COUNT(*)::int FROM call_log cl WHERE cl.lead_id = l.id) AS calls
      FROM leads l
      JOIN contacts c ON c.id = l.contact_id
      LEFT JOIN listings li ON li.id = l.listing_id
     WHERE c.do_not_call = FALSE
       AND (${status ?? null}::text IS NULL OR l.status = ${status ?? null})
       AND (${status ?? null}::text IS NOT NULL
            OR l.status IN ('called_no_answer', 'talked', 'callback', 'meeting'))
     ORDER BY (l.next_step_at IS NULL), l.next_step_at ASC, l.updated_at DESC
     LIMIT 200
  `;
}

export async function stats(days: number) {
  return sql<Array<Record<string, unknown>>>`
    SELECT to_char(day, 'YYYY-MM-DD') AS day, calls_made, target, meetings_booked
      FROM daily_stats
     WHERE day > CURRENT_DATE - ${days}::int
     ORDER BY day ASC
  `;
}

export async function openerBreakdown(days: number) {
  return sql<Array<Record<string, unknown>>>`
    SELECT opener_used,
           COUNT(*)::int AS calls,
           SUM(CASE WHEN outcome IN ('talked', 'meeting') THEN 1 ELSE 0 END)::int AS talked,
           SUM(CASE WHEN outcome = 'meeting' THEN 1 ELSE 0 END)::int AS meetings
      FROM call_log
     WHERE opener_used IS NOT NULL
       AND called_at > now() - (${days}::int * interval '1 day')
     GROUP BY opener_used
     ORDER BY opener_used
  `;
}
