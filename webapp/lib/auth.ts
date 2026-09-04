/**
 * Bramka jednego użytkownika: PIN wymieniany na podpisane ciasteczko.
 * Zwraca true, gdy żądanie niesie ważną sesję. Ingest ze skanera chodzi osobnym tokenem.
 */

import { cookies } from "next/headers";

const COOKIE = "ocrm_session";
const MAX_AGE = 60 * 60 * 24 * 30;

async function hmac(value: string): Promise<string> {
  const secret = process.env.OCRM_SESSION_SECRET;
  if (!secret || secret.length < 16) {
    throw new Error("OCRM_SESSION_SECRET musi mieć co najmniej 16 znaków.");
  }
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const signature = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(value));
  return Array.from(new Uint8Array(signature))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

function timingSafeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

export async function sessionValue(): Promise<string> {
  return hmac("ocrm-v1");
}

export async function isAuthenticated(): Promise<boolean> {
  const jar = await cookies();
  const token = jar.get(COOKIE)?.value;
  if (!token) return false;
  try {
    return timingSafeEqual(token, await sessionValue());
  } catch {
    return false;
  }
}

export async function signIn(pin: string): Promise<boolean> {
  const expected = process.env.OCRM_PIN;
  if (!expected) throw new Error("Brak OCRM_PIN w zmiennych środowiskowych.");
  if (!timingSafeEqual(pin.trim(), expected)) return false;
  const jar = await cookies();
  jar.set(COOKIE, await sessionValue(), {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge: MAX_AGE,
  });
  return true;
}

export async function signOut(): Promise<void> {
  const jar = await cookies();
  jar.delete(COOKIE);
}

export function ingestTokenValid(header: string | null): boolean {
  const expected = process.env.INGEST_TOKEN;
  if (!expected || expected.length < 16) return false;
  const provided = (header ?? "").replace(/^Bearer\s+/i, "");
  return timingSafeEqual(provided, expected);
}
