/**
 * POST /api/contacts/{id}/dnc — twarde oznaczenie „nie kontaktować".
 * Flaga wisi przy numerze, więc przetrwa powrót ogłoszenia pod nowym source_id.
 */

import { requireSession, handle, jsonBody } from "@/lib/http";
import { markDoNotCall } from "@/lib/leads";
import { optionalText, positiveInt } from "@/lib/guards";

export async function POST(request: Request, context: { params: Promise<{ id: string }> }) {
  const denied = await requireSession();
  if (denied) return denied;
  const { id } = await context.params;
  return handle(async () => {
    const body = await jsonBody(request).catch(() => ({}) as Record<string, unknown>);
    return markDoNotCall(positiveInt(id, "id"), optionalText(body.note, "note"));
  });
}
