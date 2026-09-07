"""Pobieranie stron i JSON-a przez prawdziwą przeglądarkę.

Zwraca zdekodowany JSON (`get_json`) albo treść strony (`get_html`), a przy odmowie
podnosi Blocked — kontrakt zgodny z Fetcher.get(), żeby pipeline nie musiał wiedzieć,
którym transportem przyszły dane.

DLACZEGO PRZEGLĄDARKA, A NIE httpx. Zmierzone 4 i 7 września 2026: OLX i Otodom stoją
za tym samym CloudFrontem, który odrzuca klienty HTTP po odcisku połączenia, a nie po
nagłówkach. Dowód, że to nie nagłówki: przy Otodomie httpx dostaje 403 "Request blocked"
(te same 919 bajtów) dla czterech różnych zestawów nagłówków — z Accept-Encoding i
Sec-Fetch włącznie — a curl i Chromium dostają 200 na tym samym adresie i z tego samego
łącza. Przy OLX 403 dostaje nawet /robots.txt. Skoro odcisku nie da się podrobić po
stronie klienta HTTP, transportem musi być przeglądarka.

Zapytanie idzie jako fetch() WEWNĄTRZ strony na origin olx.pl, a nie jako nawigacja.
Nawigacja pod adres API kończy się czasem "Download is starting", bo Chromium traktuje
odpowiedź application/json jak plik do pobrania; fetch() z tej samej domeny nie ma
tego problemu i przy okazji nie jest zapytaniem cross-origin.

Przeglądarka wstaje raz na cały przebieg i jest zamykana w finally u wywołującego.
Opóźnienie między zapytaniami pilnowane jest tak samo jak w Fetcherze: pierwsze idzie
od razu, każde kolejne po losowej przerwie.
"""

from __future__ import annotations

import json
import random
import time

from .base import BLOCK_STATUS, Blocked

ORIGIN = "https://www.olx.pl"
ANCHOR = f"{ORIGIN}/api/v1/offers/?limit=1&category_id=14"


class BrowserFetcher:
    def __init__(
        self,
        user_agent: str,
        delay_seconds: tuple[float, float] = (3.0, 8.0),
        headless: bool = True,
        sleep=time.sleep,
        anchor: str | None = ANCHOR,
    ) -> None:
        self.user_agent = user_agent
        self.delay_seconds = delay_seconds
        self.headless = headless
        self.anchor = anchor
        self._sleep = sleep
        self._first_request = True
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

    def _ensure_page(self):
        """Kotwica jest potrzebna tylko pod get_json: fetch() z tej samej domeny nie jest
        zapytaniem cross-origin. Przy get_html nie ma czego kotwiczyć, bo nawigujemy
        wprost pod adres strony."""
        if self._page is not None:
            return self._page
        from playwright.sync_api import sync_playwright

        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=self.headless)
        self._context = self._browser.new_context(user_agent=self.user_agent, locale="pl-PL")
        self._page = self._context.new_page()
        if self.anchor:
            response = self._page.goto(self.anchor, wait_until="domcontentloaded", timeout=45000)
            if response is not None and response.status in BLOCK_STATUS:
                raise Blocked(f"status {response.status} przy wejściu na {ORIGIN}")
            self._first_request = True
        return self._page

    def get_html(self, url: str) -> str:
        page = self._ensure_page()
        self._wait()
        try:
            response = page.goto(url, wait_until="domcontentloaded", timeout=45000)
        except Exception as exc:
            raise Blocked(f"błąd przeglądarki przy {url}: {exc}") from exc
        status = response.status if response is not None else 0
        if status in BLOCK_STATUS or status >= 500:
            raise Blocked(f"status {status} przy {url}")
        return page.content()

    def get_json(self, path: str) -> dict:
        page = self._ensure_page()
        self._wait()
        try:
            result = page.evaluate(
                """async (p) => {
                    const r = await fetch(p, { headers: { accept: 'application/json' } });
                    return { status: r.status, body: await r.text() };
                }""",
                path,
            )
        except Exception as exc:
            raise Blocked(f"błąd przeglądarki przy {path}: {exc}") from exc

        status = int(result.get("status") or 0)
        if status in BLOCK_STATUS or status >= 500:
            raise Blocked(f"status {status} przy {path}")
        try:
            payload = json.loads(result.get("body") or "")
        except ValueError as exc:
            raise Blocked(f"odpowiedź spoza JSON-a przy {path}: {exc}") from exc
        if isinstance(payload, dict) and payload.get("error") and "data" not in payload:
            detail = payload["error"].get("detail") or payload["error"].get("title")
            raise Blocked(f"API OLX odmówiło przy {path}: {detail}")
        return payload

    def _wait(self) -> None:
        if self._first_request:
            self._first_request = False
            return
        low, high = self.delay_seconds
        self._sleep(random.uniform(low, high))

    def close(self) -> None:
        for name in ("_context", "_browser"):
            obj = getattr(self, name)
            if obj is not None:
                try:
                    obj.close()
                except Exception:
                    pass
                setattr(self, name, None)
        self._page = None
        if self._playwright is not None:
            try:
                self._playwright.stop()
            except Exception:
                pass
            self._playwright = None

    def __enter__(self) -> "BrowserFetcher":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
