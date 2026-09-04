/**
 * Odczyt odpowiedzi API z zachowaniem przyczyny błędu.
 * Zwraca `data` z odpowiedzi albo rzuca wyjątkiem z komunikatem, który da się pokazać na ekranie.
 */

export async function readJson<T>(response: Response, fallback: string): Promise<T> {
  let body: { data?: T; error?: string } | null = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  if (!response.ok) {
    throw new Error(body?.error ? `${fallback} ${body.error}` : fallback);
  }
  if (!body || body.data === undefined) throw new Error(fallback);
  return body.data;
}
