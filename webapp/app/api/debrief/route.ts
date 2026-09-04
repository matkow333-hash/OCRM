/**
 * GET/POST /api/debrief — trzy pytania na koniec dnia (M4).
 * Zwraca zapis dnia; ponowny POST tego samego dnia nadpisuje wpis.
 */

import { sql } from "@/lib/db";
import { requireSession, handle, jsonBody } from "@/lib/http";
import { optionalText } from "@/lib/guards";

export const dynamic = "force-dynamic";

export async function GET() {
  const denied = await requireSession();
  if (denied) return denied;
  return handle(async () => {
    const [row] = await sql`
      SELECT to_char(day, 'YYYY-MM-DD') AS day, calls, stuck_phrase, tomorrow_fix
        FROM debrief WHERE day = CURRENT_DATE
    `;
    const [today] = await sql`SELECT calls_made FROM daily_stats WHERE day = CURRENT_DATE`;
    return { entry: row ?? null, callsToday: today?.calls_made ?? 0 };
  });
}

export async function POST(request: Request) {
  const denied = await requireSession();
  if (denied) return denied;
  return handle(async () => {
    const body = await jsonBody(request);
    const [row] = await sql`
      INSERT INTO debrief (day, calls, stuck_phrase, tomorrow_fix)
      VALUES (
        CURRENT_DATE,
        COALESCE((SELECT calls_made FROM daily_stats WHERE day = CURRENT_DATE), 0),
        ${optionalText(body.stuck_phrase ?? body.stuckPhrase, "stuck_phrase", 1000)},
        ${optionalText(body.tomorrow_fix ?? body.tomorrowFix, "tomorrow_fix", 1000)}
      )
      ON CONFLICT (day) DO UPDATE SET
        calls = EXCLUDED.calls,
        stuck_phrase = EXCLUDED.stuck_phrase,
        tomorrow_fix = EXCLUDED.tomorrow_fix
      RETURNING to_char(day, 'YYYY-MM-DD') AS day, calls, stuck_phrase, tomorrow_fix
    `;
    return row;
  });
}
