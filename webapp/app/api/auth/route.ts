/**
 * POST /api/auth — wymiana PIN-u na ciasteczko sesji. DELETE — wylogowanie.
 * Zwraca { ok } albo 401 przy złym PIN-ie.
 */

import { NextResponse } from "next/server";
import { signIn, signOut } from "@/lib/auth";
import { jsonBody } from "@/lib/http";

export async function POST(request: Request) {
  try {
    const body = await jsonBody(request);
    const pin = typeof body.pin === "string" ? body.pin : "";
    if (!pin || !(await signIn(pin))) {
      return NextResponse.json({ error: "Zły PIN." }, { status: 401 });
    }
    return NextResponse.json({ ok: true });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Nieznany błąd.";
    return NextResponse.json({ error: message }, { status: 400 });
  }
}

export async function DELETE() {
  await signOut();
  return NextResponse.json({ ok: true });
}
