/**
 * Bramka na wszystkich stronach poza logowaniem i endpointem ingest.
 * Zwraca przekierowanie na /login, gdy w żądaniu nie ma ciasteczka sesji.
 */

import { NextResponse, type NextRequest } from "next/server";

const PUBLIC_PATHS = ["/login", "/api/auth", "/api/ingest", "/manifest.json", "/sw.js", "/icon.svg"];

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;
  if (PUBLIC_PATHS.some((path) => pathname === path || pathname.startsWith(`${path}/`))) {
    return NextResponse.next();
  }
  if (request.cookies.has("ocrm_session")) return NextResponse.next();
  if (pathname.startsWith("/api/")) {
    return NextResponse.json({ error: "Brak sesji." }, { status: 401 });
  }
  const target = request.nextUrl.clone();
  target.pathname = "/login";
  target.search = "";
  return NextResponse.redirect(target);
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
