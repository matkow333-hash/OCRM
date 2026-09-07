/**
 * POST /api/leads/{id}/meeting — umówienie spotkania po rozmowie.
 * Data jest obowiązkowa: bez niej spotkanie nie trafiłoby do kalendarza, a lead
 * dostałby status 'meeting' bez terminu - dokładnie to, co ta zmiana naprawia.
 * Zwraca zapisany rekord z tabeli meetings.
 */

import { requireSession, handle, jsonBody } from "@/lib/http";
import { bookMeeting } from "@/lib/meetings";
import { BadRequest, optionalText, optionalTimestamp, positiveInt } from "@/lib/guards";

export async function POST(request: Request, context: { params: Promise<{ id: string }> }) {
  const denied = await requireSession();
  if (denied) return denied;
  const { id } = await context.params;
  return handle(async () => {
    const body = await jsonBody(request);
    const startsAt = optionalTimestamp(body.starts_at ?? body.startsAt, "starts_at");
    if (!startsAt) {
      throw new BadRequest("Umówienie spotkania wymaga daty starts_at.");
    }
    return bookMeeting(positiveInt(id, "id"), {
      startsAt,
      address: optionalText(body.address, "address", 300),
      note: optionalText(body.note, "note"),
    });
  });
}
