/**
 * POST /api/leads/{id}/status — zmiana statusu leada.
 * lost_reason jest obowiązkowy przy przejściu na 'lost'.
 */

import { requireSession, handle, jsonBody } from "@/lib/http";
import { updateStatus } from "@/lib/leads";
import {
  BadRequest,
  LEAD_STATUSES,
  oneOf,
  optionalText,
  optionalTimestamp,
  positiveInt,
} from "@/lib/guards";

export async function POST(request: Request, context: { params: Promise<{ id: string }> }) {
  const denied = await requireSession();
  if (denied) return denied;
  const { id } = await context.params;
  return handle(async () => {
    const body = await jsonBody(request);
    const status = oneOf(body.status, LEAD_STATUSES, "status");
    const lostReason = optionalText(body.lost_reason ?? body.lostReason, "lost_reason", 500);
    if (status === "lost" && !lostReason) {
      throw new BadRequest("Przejście na 'lost' wymaga podania lost_reason.");
    }
    const nextStepAt = optionalTimestamp(body.next_step_at ?? body.nextStepAt, "next_step_at");
    if (status === "callback" && !nextStepAt) {
      throw new BadRequest("Status 'callback' wymaga daty next_step_at.");
    }
    return updateStatus(positiveInt(id, "id"), {
      status,
      nextStep: optionalText(body.next_step ?? body.nextStep, "next_step", 500),
      nextStepAt,
      lostReason,
    });
  });
}
