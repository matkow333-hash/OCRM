# OCRM — Operational Center of Research and Marketing

Radar publicznych ogłoszeń mieszkaniowych od właścicieli w Trójmieście (Gdańsk, Sopot, Gdynia)
plus aplikacja na telefon, w której Milena obdzwania listę. Cel systemu jest jeden:
**10 wykonanych połączeń dziennie**. Specyfikacja produktowa: [OCRM.md](OCRM.md).

## Architektura

Aplikacja stoi na Vercelu, skaner nie. To nie jest wybór estetyczny: Vercel to funkcje
serverless bez trwałego dysku i bez przeglądarki, więc Playwright i baza SQLite nie mają
tam jak działać.

```
  laptop (Milena)                          Vercel                      Neon / Vercel Postgres
┌──────────────────────┐        ┌────────────────────────┐        ┌──────────────────────┐
│ python -m ocrm.cli   │        │ Next.js PWA            │        │ listings   contacts  │
│   scan --push        │        │  /        Dziś         │        │ leads      call_log  │
│                      │  HTTPS │  /moje    Moje         │  SQL   │ daily_stats debrief  │
│ OLX → normalize →    │───────▶│  /debrief Debrief      │───────▶│                      │
│ classify → dedup     │ Bearer │  /api/ingest (token)   │        │                      │
│ SQLite data/ocrm.db  │        │  /api/*     (PIN)      │        │                      │
└──────────────────────┘        └────────────────────────┘        └──────────────────────┘
        co 45 min (cron)              telefon Mileny
```

Skaner zostaje jedynym miejscem, gdzie pracuje Playwright i gdzie leżą surowe dane.
Do aplikacji trafia tylko to, co już przeszło klasyfikację i deduplikację.

| Warstwa | Wybór | Dlaczego |
|---|---|---|
| Skaner | Python 3.11, Playwright, SQLite | zostaje na laptopie, ma dysk i przeglądarkę — bez przeglądarki OLX odpowiada 403 |
| Aplikacja | Next.js 16 (App Router), React 19, TypeScript | PWA instalowana na ekranie głównym, bez App Store |
| Baza aplikacji | Postgres (Neon albo Vercel Postgres) | serverless nie utrzyma pliku SQLite |
| Transport | `POST /api/ingest`, token Bearer | skaner nie potrzebuje dostępu do bazy |
| Dostęp | PIN → podpisane ciasteczko | publiczny adres wymaga bramki |

## Stan prac

| Milestone | Stan |
|---|---|
| M0 — szkielet, config, baza, normalizacja | ✔ gotowe |
| M1a — adapter OLX | ✔ zweryfikowany na żywym OLX, chodzi na publicznym API portalu |
| M1b — klasyfikacja i deduplikacja | ✔ gotowe |
| M3a — leady i ranking porannej listy | ✔ gotowe |
| M3b — API i UI na telefon | ✔ gotowe |
| M4 — otwarcia A/B/C, debrief | ✔ gotowe |
| M1c — Otodom, Gratka, Morizon | ✘ nie zaczęte |
| M-notify — wiadomość o 8:00 | ✘ nie zaczęte (brak dostawcy e-mail) |
| **Numery telefonu** | ⛔ **zablokowane przez OLX — patrz niżej, wymaga decyzji** |
| M2 — radar popytu | ✘ faza 2 |

## Uruchomienie skanera (laptop)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt && pip install -e .
python -m playwright install chromium
cp config.example.yaml config.yaml
cp .env.example .env                  # uzupełnij OCRM_APP_URL i INGEST_TOKEN

python -m ocrm.cli init               # tworzy data/ocrm.db
python -m ocrm.cli scan --source olx  # jeden przebieg
python -m ocrm.cli list --private     # co wpadło
python -m ocrm.cli scan --push        # przebieg + wysyłka do aplikacji
python -m pytest                      # 98 testów, bez sieci
```

Cron co 45 minut:

```cron
*/45 * * * * cd /sciezka/do/OCRM && .venv/bin/python -m ocrm.cli scan --push >> data/scan.log 2>&1
```

Windows: Task Scheduler, to samo polecenie, wyzwalacz „powtarzaj co 45 minut”.

## Uruchomienie aplikacji lokalnie

```bash
cd webapp
npm install
cp .env.example .env.local            # uzupełnij DATABASE_URL, OCRM_PIN, sekrety
npm run migrate                       # zakłada schemę w Postgresie
npm run dev
```

## Wdrożenie na Vercel

1. **Baza.** Załóż Postgres w Neon (`neon.tech`, darmowy plan wystarczy) albo w zakładce
   Storage na Vercelu. Skopiuj connection string.
2. **Projekt.** Vercel → Add New → Project → import tego repo.
   W ustawieniach projektu ustaw **Root Directory = `webapp`**. Framework wykryje się sam.
3. **Zmienne środowiskowe** (Settings → Environment Variables), wszystkie na Production i Preview:

   | Zmienna | Co wpisać |
   |---|---|
   | `DATABASE_URL` | connection string z kroku 1 |
   | `OCRM_PIN` | PIN, którym loguje się Milena |
   | `OCRM_SESSION_SECRET` | losowy ciąg, min. 32 znaki (`openssl rand -hex 32`) |
   | `INGEST_TOKEN` | drugi losowy ciąg, min. 32 znaki — trafia też do `.env` skanera |
   | `DAILY_CALL_TARGET` | `10` |
   | `LIST_SIZE` | `15` |

4. **Migracja.** Lokalnie, raz: `cd webapp && DATABASE_URL="…" npm run migrate`.
5. **Deploy.** Vercel zbuduje projekt po pushu na gałąź.
6. **Telefon.** Otwórz adres w Safari/Chrome → Udostępnij → „Dodaj do ekranu początkowego”.
   Aplikacja startuje pełnoekranowo, bez paska adresu.

## Bezpieczeństwo i RODO

- Wszystkie strony i endpointy poza `/login`, `/api/auth` i `/api/ingest` wymagają
  ciasteczka sesji; `middleware.ts` odcina resztę.
- `/api/ingest` chodzi na osobnym tokenie Bearer — skaner nie zna PIN-u i nie ma dostępu
  do bazy, a wyciek tokenu nie daje wglądu w leady.
- `do_not_call` wisi przy **numerze**, nie przy ogłoszeniu. Sprawdzone testem: to samo
  ogłoszenie wrzucone pod nowym `source_id` nie zakłada leada dla numeru z flagą.
- `lost_reason` jest wymagany przy przejściu na `lost`, `next_step_at` przy `callback` —
  API odrzuca żądanie bez nich (400), nie zapisuje po cichu.
- Numery pochodzą wyłącznie z publicznych ogłoszeń i nie są nikomu przekazywane.

## Zasady pracy skanera

Wymuszone w kodzie, nie w dobrych chęciach:

- `config.py` odrzuca `interval_minutes < 30`, `delay_seconds` poniżej 1 s,
  `max_pages_per_source > 20` i karencję krótszą niż 60 minut
- `Fetcher` czyta `robots.txt` każdej domeny i nie pobiera tego, co zabronione
- losowe opóźnienie 3–8 s między requestami, jeden wątek, jeden portal naraz
- 401/403/407/429/451, 5xx albo captcha → `Blocked` → `status='blocked'` w `scan_log`
  i **godzina karencji**; kolejny `scan` w tym czasie kończy się `cooldown`
- dwa przebiegi z rzędu z zerem wyników zostawiają ostrzeżenie w `scan_log.detail`
- ogłoszenie bez numeru i tak wchodzi do bazy z `phone_e164 = NULL`

## Jak działa klasyfikacja (M1b)

`classify.py` liczy `agency_score` 0.0–1.0 z sygnałów, których wagi siedzą w `config.yaml`:
flaga portalu, słowa kluczowe biura, ten sam numer na wielu ogłoszeniach, ten sam numer
w wielu dzielnicach, opis-broszura. Próg `>= 0.6` → `agency` (wykluczenie z listy),
`<= 0.3` → `private`, pomiędzy → `unknown` (wchodzi na listę, ale niżej).

Jedno rozszerzenie poza literę specyfikacji, bo bez niego reguła gubiła najlepsze leady:
słowo „prowizja” trafia też w opis właściciela piszącego „**bez** prowizji”. Dlatego doszła
lista `keywords_private` z wagą ujemną i wykrywanie negacji. Właściciel piszący
„bezpośrednio, bez prowizji, bez pośredników” wychodzi jako `private` — jest na to test.

## Jak działa deduplikacja (M1b)

Trzy reguły w kolejności ze specyfikacji: (1) ten sam numer + metraż ±1 m² + cena ±3%,
(2) bez numeru: ulica + metraż + cena, (3) simhash opisu, Hamming ≤ 3.

Simhash liczony jest ze słów i par słów. Zmierzone na realnej długości ogłoszenia (~110 słów):
zmiana jednego słowa daje dystans 1, dopisanie dwóch słów — 3, inne ogłoszenie — 26.
Próg ≤ 3 jest więc trafiony. Na krótkich opisach (< 200 znaków) ten sam pomiar daje 8,
czyli reguła i tak by nie zadziałała, a ryzykowałaby sklejeniem różnych mieszkań — dlatego
krótkie opisy w ogóle nie dostają odcisku i zostają przy regułach 1 i 2.

## Adapter OLX — co zostało zmierzone

Weryfikacja na żywym OLX, 4 września 2026. Pierwsza wersja adaptera **nie zwracała ani jednego
ogłoszenia** i nie mogła: parsowała HTML, którego OLX nie oddaje.

**Transportem musi być przeglądarka.** OLX stoi za CloudFrontem odrzucającym klientów HTTP.
`httpx` i `curl` dostają 403 „Request blocked" nawet na `/robots.txt`, z pełnym zestawem
nagłówków przeglądarki włącznie. To odcisk połączenia, nie nagłówki — nie da się tego obejść
po stronie klienta HTTP. Chromium sterowany Playwrightem dostaje 200 z tego samego łącza.

**Strona wyników nie niesie ogłoszeń.** `window.__PRERENDERED_STATE__` zawiera wyłącznie drzewo
kategorii, `window.__TAURUS__` jest pustą tablicą, a `data-cy="l-card"` nie występuje
w dokumencie ani razu. Lista dorenderowuje się po stronie klienta.

**Dane idą z publicznego API portalu.** `/robots.txt` OLX-a jawnie dopuszcza `/api/v1/offers/`
(`Disallow: /api/` z późniejszym `Allow: /api/v1/offers/`), więc to droga przewidziana przez
serwis. Odpowiedź niesie cenę, metraż, pokoje, piętro, dzielnicę, opis i flagę `business`
w jednym zapytaniu na partię — wejście na stronę każdej oferty przestało być potrzebne.

Zmierzone identyfikatory (OLX nie publikuje dokumentacji, więc pochodzą z odpowiedzi API):

| Co | Wartość | Jak sprawdzić |
|---|---|---|
| Mieszkania sprzedaż | `category_id=14` | `metadata.adverts.config.targeting.cat_l2` = `sprzedaz` |
| Mieszkania wynajem | `category_id=15` | to samo pole = `wynajem` |
| Gdańsk / Gdynia / Sopot | `city_id` 5659 / 5849 / 15983 | `location.city.id` w ofertach |
| Pomorskie | `region_id=5` | `location.region.name` |

Dwie pułapki, obie z pomiaru:

- **`contact.phone` w API jest wartością logiczną**, nie numerem. Wpisany wprost dawał
  `phone_raw = True` i numer „True" w bazie. Dziś trafia do `extra["has_phone"]`.
- **Przy `limit=40` API oddaje 51 ogłoszeń**, bo dokłada promowane ponad limit. Warunek
  „krótsza partia znaczy koniec" był więc błędny; koniec danych poznajemy po
  `metadata.visible_total_count`.

Filtra osób prywatnych nie da się podać w zapytaniu — API odpowiada
`Dynamic filters not applicable for category 14: filter_enum_private_business`. Nie szkodzi:
każda oferta niesie flagę `business`, a `classify.py` i tak liczy własny `agency_score`.

Fixture'y `tests/fixtures/olx_api_*.json` to prawdziwe odpowiedzi API przycięte do dziesięciu
ogłoszeń na miasto. Licznik `visible_total_count` zostaje w nich prawdziwy, bo to po nim
adapter poznaje koniec danych.

### Numery telefonu — blokada wymagająca decyzji

**OLX nie pokazuje już numeru bez zalogowania.** Na stronie oferty nie ma przycisku
„Pokaż numer" ani żadnego z zakładanych selektorów; są „Zapytaj o ofertę" i „Zaloguj się /
Załóż konto". Sprawdzone po odrzuceniu banera zgody, który wcześniej zasłaniał stronę.

Pozyskiwanie numeru z treści ogłoszenia **nie jest wyjściem**: na 284 pobranych ogłoszeniach
numer w opisie ma 3, a wśród 158 ogłoszeń prywatnych — jedno.

Bez numerów aplikacja ma listę mieszkań, ale nie ma do kogo dzwonić. Rozstrzygnięcie należy
do właściciela: konto OLX i logowanie skanera, inne źródło ogłoszeń, albo kontakt czatem
zamiast telefonem. To decyzja o regulaminie portalu i o cudzych danych, nie decyzja techniczna.

## Struktura repo

```
src/ocrm/          skaner: config, db, models, normalize, classify, dedup, pipeline, push, cli
  adapters/        base (robots.txt, opóźnienia, blokady) + olx
webapp/            aplikacja Next.js na Vercel
  app/             ekrany Dziś / Moje / Debrief / Login + API
  components/      widoki klienckie
  lib/             db, auth, guards, scoring, leads, schema.sql
  public/          manifest PWA, ikona, service worker
tests/             98 testów offline + fixture'y HTML
.github/workflows/ CI: pytest + typecheck + build
```

## API

| Endpoint | Autoryzacja | Opis |
|---|---|---|
| `POST /api/auth` | — | PIN → ciasteczko sesji |
| `GET /api/today` | sesja | poranna lista + licznik dnia |
| `GET /api/leads?status=…` | sesja | leady w toku |
| `POST /api/leads/{id}/call` | sesja | zapis połączenia, podbija licznik |
| `POST /api/leads/{id}/status` | sesja | zmiana statusu |
| `POST /api/contacts/{id}/dnc` | sesja | „nie kontaktować” |
| `GET /api/stats?days=30` | sesja | dzienne liczniki + skuteczność otwarć |
| `GET/POST /api/debrief` | sesja | debrief dnia |
| `POST /api/ingest` | token Bearer | wejście danych ze skanera |
