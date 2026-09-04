/**
 * Połączenie z Postgresem (Neon / Vercel Postgres).
 * Zwraca leniwy uchwyt `sql`: klient powstaje przy pierwszym zapytaniu, nie przy imporcie,
 * dzięki czemu `next build` przechodzi bez DATABASE_URL (CI, kompilacja na Vercelu).
 */

import postgres from "postgres";

type Client = ReturnType<typeof postgres>;

declare global {
  var __ocrmSql: Client | undefined;
}

function create(): Client {
  const url = process.env.DATABASE_URL;
  if (!url) {
    throw new Error(
      "Brak DATABASE_URL. Ustaw ją w Vercel → Settings → Environment Variables i wdróż ponownie.",
    );
  }
  const ssl = url.includes("sslmode=disable") ? false : ("require" as const);
  return postgres(url, { ssl, max: 3, idle_timeout: 20, prepare: false });
}

function client(): Client {
  if (!globalThis.__ocrmSql) globalThis.__ocrmSql = create();
  return globalThis.__ocrmSql;
}

export const sql = new Proxy((() => undefined) as unknown as Client, {
  apply: (_target, _thisArg, args: unknown[]) =>
    (client() as unknown as (...rest: unknown[]) => unknown)(...args),
  get: (_target, property: string | symbol) => {
    const value = (client() as unknown as Record<string | symbol, unknown>)[property];
    return typeof value === "function" ? value.bind(client()) : value;
  },
}) as Client;

export const LIST_SIZE = Number(process.env.LIST_SIZE ?? 15);
export const DAILY_CALL_TARGET = Number(process.env.DAILY_CALL_TARGET ?? 10);
