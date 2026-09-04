/**
 * POST /api/leads/{id}/call — rejestracja wykonanego połączenia jednym tapnięciem.
 * Zwraca zapisany wpis z call_log; licznik dnia rośnie niezależnie od wyniku rozmowy.
 */

import { requireSession, handle, jsonBody } from "@/lib/http";
import { logCall } from "@/lib/leads";
import { CALL_OUTCOMES, OPENERS, oneOf, optionalText, positiveInt } from "@/lib/guards";

export async function POST(request: Request, context: { params: Promise<{ id: string }> }) {
  const denied = await requireSession();
  if (denied) return denied;
  const { id } = await context.params;
  return handle(async () => {
    const body = await jsonBody(request);
    const openerRaw = body.opener_used ?? body.openerUsed;
    return logCall(positiveInt(id, "id"), {
      outcome: oneOf(body.outcome, CALL_OUTCOMES, "outcome"),
      openerUsed: openerRaw ? oneOf(openerRaw, OPENERS, "opener_used") : null,
      objection: optionalText(body.objection, "objection", 500),
      note: optionalText(body.note, "note"),
    });
  });
}
