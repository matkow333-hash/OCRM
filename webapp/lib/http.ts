/**
 * Wspólna obsługa odpowiedzi API: bramka sesji, mapowanie błędów na kody HTTP.
 * Zwraca Response gotowy do oddania z route handlera.
 */

import { NextResponse } from "next/server";
import { isAuthenticated } from "./auth";
import { BadRequest } from "./guards";

export async function requireSession(): Promise<NextResponse | null> {
  if (await isAuthenticated()) return null;
  return NextResponse.json({ error: "Brak sesji." }, { status: 401 });
}

export async function handle<T>(work: () => Promise<T>): Promise<NextResponse> {
  try {
    return NextResponse.json({ data: await work() });
  } catch (error) {
    if (error instanceof BadRequest) {
      return NextResponse.json({ error: error.message }, { status: 400 });
    }
    const message = error instanceof Error ? error.message : "Nieznany błąd.";
    const status = message.includes("Nie ma takiego") ? 404 : 500;
    if (status === 500) console.error(error);
    return NextResponse.json({ error: message }, { status });
  }
}

export async function jsonBody(request: Request): Promise<Record<string, unknown>> {
  try {
    const parsed = await request.json();
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      throw new BadRequest("Oczekiwano obiektu JSON.");
    }
    return parsed as Record<string, unknown>;
  } catch (error) {
    if (error instanceof BadRequest) throw error;
    throw new BadRequest("Ciało żądania nie jest poprawnym JSON-em.");
  }
}
