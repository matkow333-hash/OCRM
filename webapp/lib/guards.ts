/**
 * Walidacja danych wchodzących przez API i wspólne odpowiedzi błędów.
 * Zwraca sparsowaną wartość albo rzuca BadRequest, który route zamienia na 400.
 */

export const CALL_OUTCOMES = ["no_answer", "talked", "refused", "callback", "meeting"] as const;
export const LEAD_STATUSES = [
  "new",
  "called_no_answer",
  "talked",
  "callback",
  "meeting",
  "contract",
  "lost",
  "dnc",
] as const;
export const OPENERS = ["A", "B", "C"] as const;
export const DEAL_TYPES = ["sale", "rent"] as const;
export const SELLER_TYPES = ["private", "agency", "unknown"] as const;

export class BadRequest extends Error {}

export function oneOf<T extends readonly string[]>(
  value: unknown,
  allowed: T,
  field: string,
): T[number] {
  if (typeof value !== "string" || !allowed.includes(value)) {
    throw new BadRequest(`Pole ${field}: dozwolone ${allowed.join(", ")}.`);
  }
  return value as T[number];
}

export function optionalText(value: unknown, field: string, maxLength = 2000): string | null {
  if (value === undefined || value === null || value === "") return null;
  if (typeof value !== "string") throw new BadRequest(`Pole ${field} musi być tekstem.`);
  if (value.length > maxLength) throw new BadRequest(`Pole ${field}: maksimum ${maxLength} znaków.`);
  return value;
}

export function optionalTimestamp(value: unknown, field: string): string | null {
  if (value === undefined || value === null || value === "") return null;
  if (typeof value !== "string" || Number.isNaN(Date.parse(value))) {
    throw new BadRequest(`Pole ${field} musi być datą ISO 8601.`);
  }
  return new Date(value).toISOString();
}

export function positiveInt(value: unknown, field: string): number {
  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed <= 0) {
    throw new BadRequest(`Pole ${field} musi być dodatnią liczbą całkowitą.`);
  }
  return parsed;
}

export function boundedInt(value: unknown, field: string, min: number, max: number, fallback: number): number {
  if (value === undefined || value === null || value === "") return fallback;
  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed < min || parsed > max) {
    throw new BadRequest(`Pole ${field} musi być liczbą całkowitą ${min}..${max}.`);
  }
  return parsed;
}

export function phoneE164(value: unknown, field: string): string {
  if (typeof value !== "string" || !/^\+\d{8,15}$/.test(value)) {
    throw new BadRequest(`Pole ${field} musi być numerem w formacie E.164.`);
  }
  return value;
}
