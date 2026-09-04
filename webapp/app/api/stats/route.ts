/**
 * GET /api/stats?days=30 — dzienne liczniki połączeń i skuteczność otwarć A/B/C.
 * Zwraca { days, openers }.
 */

import { requireSession, handle } from "@/lib/http";
import { openerBreakdown, stats } from "@/lib/leads";
import { boundedInt } from "@/lib/guards";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const denied = await requireSession();
  if (denied) return denied;
  const days = boundedInt(new URL(request.url).searchParams.get("days"), "days", 1, 365, 30);
  return handle(async () => ({
    days: await stats(days),
    openers: await openerBreakdown(days),
  }));
}
