/**
 * POST /api/meetings/{id}/outcome — zamknięcie spotkania po fakcie.
 * Wynik przenosi leada na istniejący status: umowa -> contract,
 * do przemyślenia -> callback, nie wyszło -> lost. Przy 'failed' powód wymagany,
 * tak samo jak przy zwykłym przejściu na 'lost'.
 */

import { requireSession, handle, jsonBody } from "@/lib/http";
import { closeMeeting, MEETING_OUTCOMES } from "@/lib/meetings";
import { oneOf, optionalText, positiveInt } from "@/lib/guards";

export async function POST(request: Request, context: { params: Promise<{ id: string }> }) {
  const denied = await requireSession();
  if (denied) return denied;
  const { id } = await context.params;
  return handle(async () => {
    const body = await jsonBody(request);
    return closeMeeting(positiveInt(id, "id"), {
      outcome: oneOf(body.outcome, MEETING_OUTCOMES, "outcome"),
      note: optionalText(body.note, "note", 1000),
    });
  });
}
