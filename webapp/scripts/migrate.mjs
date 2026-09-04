/**
 * Tworzy schemę w bazie wskazanej przez DATABASE_URL.
 * Zwraca listę tabel po migracji. Idempotentny - można puszczać wielokrotnie.
 */

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import postgres from "postgres";

const here = dirname(fileURLToPath(import.meta.url));
const url = process.env.DATABASE_URL;

if (!url) {
  console.error("Brak DATABASE_URL. Ustaw zmienną i uruchom ponownie.");
  process.exit(1);
}

const sql = postgres(url, { ssl: url.includes("sslmode=disable") ? false : "require", max: 1 });

try {
  await sql.unsafe(readFileSync(join(here, "..", "lib", "schema.sql"), "utf8"));
  const tables = await sql`
    SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename
  `;
  console.log(`Schema gotowa. Tabele (${tables.length}): ${tables.map((t) => t.tablename).join(", ")}`);
} catch (error) {
  console.error("Migracja nie przeszła:", error.message);
  process.exitCode = 1;
} finally {
  await sql.end();
}
