/**
 * GET /api/calendar?from=&to= — terminy w oknie czasu.
 * Łączy spotkania z tabeli meetings i oddzwonienia (leady ze statusem callback,
 * których data od dawna leży w leads.next_step_at i do tej pory nie była nigdzie widoczna).
 * Zwraca listę wpisów posortowaną po dacie plus skuteczność spotkań z wielkością próbki.
 */

import { requireSession, handle } from "@/lib/http";
import { calendar, meetingStats } from "@/lib/meetings";
import { BadRequest } from "@/lib/guards";

const DZIEN = 24 * 60 * 60 * 1000;

export async function GET(request: Request) {
  const denied = await requireSession();
  if (denied) return denied;
  return handle(async () => {
    const params = new URL(request.url).searchParams;
    const from = okno(params.get("from"), new Date(Date.now() - 7 * DZIEN));
    const to = okno(params.get("to"), new Date(Date.now() + 60 * DZIEN));
    if (from >= to) throw new BadRequest("Parametr from musi być wcześniejszy niż to.");
    return {
      entries: await calendar(from.toISOString(), to.toISOString()),
      stats: await meetingStats(),
    };
  });
}

function okno(value: string | null, fallback: Date): Date {
  if (!value) return fallback;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    throw new BadRequest("Parametry from i to muszą być datami ISO 8601.");
  }
  return parsed;
}
