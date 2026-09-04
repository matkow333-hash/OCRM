/**
 * GET /api/leads?status=… — leady w toku, zaległe na górze.
 * Zwraca { items }.
 */

import { requireSession, handle } from "@/lib/http";
import { listLeads } from "@/lib/leads";
import { LEAD_STATUSES, oneOf } from "@/lib/guards";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const denied = await requireSession();
  if (denied) return denied;
  const raw = new URL(request.url).searchParams.get("status");
  const status = raw ? oneOf(raw, LEAD_STATUSES, "status") : undefined;
  return handle(async () => ({ items: await listLeads(status) }));
}
