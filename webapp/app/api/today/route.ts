/**
 * GET /api/today — poranna lista i licznik dnia.
 * Zwraca { items, counter }.
 */

import { requireSession, handle } from "@/lib/http";
import { todayList, todayCounter } from "@/lib/scoring";

export const dynamic = "force-dynamic";

export async function GET() {
  const denied = await requireSession();
  if (denied) return denied;
  return handle(async () => ({
    items: await todayList(),
    counter: await todayCounter(),
  }));
}
