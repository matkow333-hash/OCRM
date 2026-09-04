# OCRM — specyfikacja projektu dla agenta kodującego

> Wklej ten plik jako pierwszy kontekst. Zbuduj według niego, w kolejności z sekcji „Milestones".
> Nie zaczynaj od Facebooka. Nie buduj UI zanim działa pipeline. Nie dodawaj funkcji spoza tego dokumentu.

---

## 1. Kontekst

**OCRM** = Operational Center of Research and Marketing.

System operacyjny dla **Mileny** — agentki nieruchomości pracującej w agencji na terenie Trójmiasta (Gdańsk, Sopot, Gdynia). Agencja nie daje jej żadnych narzędzi ani leadów. Ma znaleźć wszystko sama, w sprzedaży i w wynajmie.

Umowa z agencją pozwala jej budować własną bazę kontaktów i prowadzić markę osobistą — sprawdzone, brak przeszkód.

### Kto jest właścicielem czego

| Rola | Kto | Uwaga |
|---|---|---|
| Zamawiający / developer | Mat | Pisze i utrzymuje system |
| Użytkownik końcowy | Milena | Nie jest techniczna. Pracuje z telefonu, w terenie |

### Jedyna metryka sukcesu miesiąca 1

**10 wykonanych połączeń dziennie.**

Nie liczba zebranych ofert. Nie liczba rekordów w bazie. Baza z tysiącem numerów, do których nikt nie zadzwonił, jest warta zero. Każda decyzja projektowa ma być rozstrzygana pytaniem: *czy to zwiększy liczbę wykonanych telefonów?*

---

## 2. Twarde zasady projektowe

Te reguły wygrywają z każdą inną preferencją. Jeśli implementacja im przeczy — implementacja jest zła.

1. **Mała skala, ludzkie tempo.** Jeden przebieg skanera co 30–60 minut. Losowe opóźnienia 3–8 s między requestami. Limit stron na przebieg. Bez farmy proxy, bez rotacji IP, bez równoległych workerów na jeden portal.
2. **Tylko dane publiczne.** Żadnych treści za logowaniem, żadnego obchodzenia captchy, żadnej redystrybucji zebranych danych na zewnątrz.
3. **Respektuj `robots.txt`.** Adapter, który dostanie blokadę (403, 429, captcha), wyłącza się na godzinę i loguje zdarzenie — nie ponawia agresywnie.
4. **Facebook dopiero w fazie 3.** Ryzyko blokady konta osobistego jest tam najwyższe. Nie implementuj wcześniej, nawet „na próbę".
5. **RODO.** Numery pochodzą z publicznych ogłoszeń. System musi mieć pole `do_not_call` i honorować je bezwarunkowo — kontakt oznaczony w ten sposób nigdy nie trafia na poranną listę, nawet jeśli ogłoszenie wróci pod nowym `source_id`.
6. **Wpis do bazy w 10 sekund, z telefonu.** Jeśli aktualizacja statusu leada wymaga więcej niż dwóch tapnięć, projekt UI jest zły.
7. **Bez komentarzy inline w kodzie.** Każdy plik zaczyna się krótkim docstringiem: co robi i co zwraca. Reszta ma być czytelna sama z siebie.
8. **Bez sekretów w repo.** Konfiguracja w `config.yaml`, sekrety w `.env`, oba w `.gitignore` (dołóż `config.example.yaml` i `.env.example`).

---

## 3. Architektura

```
źródła (OLX, Otodom, …)
        │  adapters/*.py — pobierają i parsują
        ▼
   RawListing (dataclass)
        │  normalize.py — telefon E.164, adres, cena, metraż
        ▼
   classify.py — prywatny czy pośrednik
        │
        ▼
   dedup.py — łączy to samo mieszkanie z wielu portali
        │
        ▼
   SQLite (listings / contacts / leads / call_log)
        │
        ├── scoring.py → poranna lista (top 15)
        ├── api.py → FastAPI + jednostronicowy UI na telefon
        └── notify.py → wiadomość o 8:00
```

### Stack

| Warstwa | Wybór |
|---|---|
| Język | Python 3.11+ |
| Pobieranie | Playwright (chromium, headless), `httpx` tam gdzie wystarcza |
| Parsowanie | `selectolax` lub `beautifulsoup4` |
| Baza | SQLite (`data/ocrm.db`), dostęp przez `sqlite3` + cienka warstwa w `db.py` |
| API + UI | FastAPI + jeden plik `web/index.html` (vanilla JS, bez frameworka) |
| Harmonogram | `cron` (Linux/macOS) lub Task Scheduler (Windows) wywołujący `cli.py scan` |
| Dostęp z telefonu | Cloudflare Tunnel albo Tailscale — do wyboru, udokumentuj oba w README |
| Testy | `pytest` |

Bez Dockera w v1. Bez Postgresa w v1. Bez Celery, Redisa, kolejek. Jeśli kusi cię dodanie zależności — nie dodawaj.

### Struktura repo

```
ocrm/
├── README.md
├── OCRM.md                  ten plik
├── requirements.txt
├── config.example.yaml
├── .env.example
├── data/                    .gitignore
│   └── ocrm.db
├── src/ocrm/
│   ├── __init__.py
│   ├── config.py            wczytanie i walidacja config.yaml
│   ├── db.py                schema, migracje, connection
│   ├── models.py            dataclasses: RawListing, Listing, Contact, Lead
│   ├── normalize.py         telefon, adres, cena, metraż
│   ├── classify.py          prywatny vs pośrednik
│   ├── dedup.py             grupowanie duplikatów
│   ├── scoring.py           ranking porannej listy
│   ├── pipeline.py          scan → normalize → classify → dedup → zapis
│   ├── notify.py            wysyłka porannej listy
│   ├── api.py               FastAPI: endpointy + serwowanie UI
│   ├── cli.py               scan / list / serve / export
│   └── adapters/
│       ├── base.py          klasa Adapter, kontrakt
│       ├── olx.py
│       ├── otodom.py
│       ├── gratka.py
│       └── morizon.py
├── web/
│   └── index.html
└── tests/
    ├── test_normalize.py
    ├── test_classify.py
    ├── test_dedup.py
    ├── test_scoring.py
    └── fixtures/            zapisane fragmenty HTML do testów parserów
```

---

## 4. Model danych

SQLite. Wszystkie znaczniki czasu w UTC, ISO 8601.

```sql
CREATE TABLE listings (
  id                INTEGER PRIMARY KEY,
  source            TEXT NOT NULL,          -- 'olx' | 'otodom' | 'gratka' | 'morizon'
  source_id         TEXT NOT NULL,
  url               TEXT NOT NULL,
  deal_type         TEXT NOT NULL,          -- 'sale' | 'rent'
  city              TEXT,                   -- 'Gdańsk' | 'Sopot' | 'Gdynia'
  district          TEXT,
  street            TEXT,
  price             INTEGER,
  area_m2           REAL,
  rooms             INTEGER,
  floor             INTEGER,
  title             TEXT,
  description       TEXT,
  content_hash      TEXT,                   -- simhash opisu, do dedup
  phone_e164        TEXT,
  seller_type       TEXT NOT NULL,          -- 'private' | 'agency' | 'unknown'
  agency_score      REAL NOT NULL,          -- 0.0–1.0, wyżej = bardziej pośrednik
  dedup_group       TEXT,
  first_seen_at     TEXT NOT NULL,
  last_seen_at      TEXT NOT NULL,
  is_active         INTEGER NOT NULL DEFAULT 1,
  UNIQUE (source, source_id)
);

CREATE TABLE contacts (
  id                INTEGER PRIMARY KEY,
  phone_e164        TEXT NOT NULL UNIQUE,
  name              TEXT,
  do_not_call       INTEGER NOT NULL DEFAULT 0,
  do_not_call_at    TEXT,
  note              TEXT,
  created_at        TEXT NOT NULL
);

CREATE TABLE leads (
  id                INTEGER PRIMARY KEY,
  contact_id        INTEGER NOT NULL REFERENCES contacts(id),
  listing_id        INTEGER REFERENCES listings(id),
  status            TEXT NOT NULL,          -- patrz niżej
  next_step         TEXT,
  next_step_at      TEXT,
  lost_reason       TEXT,
  contract_ends_at  TEXT,                   -- gdy ma umowę z inną agencją
  created_at        TEXT NOT NULL,
  updated_at        TEXT NOT NULL
);

CREATE TABLE call_log (
  id                INTEGER PRIMARY KEY,
  lead_id           INTEGER NOT NULL REFERENCES leads(id),
  called_at         TEXT NOT NULL,
  outcome           TEXT NOT NULL,          -- 'no_answer' | 'talked' | 'refused' | 'callback' | 'meeting'
  opener_used       TEXT,                   -- 'A' | 'B' | 'C'
  objection         TEXT,
  note              TEXT
);

CREATE TABLE daily_stats (
  day               TEXT PRIMARY KEY,
  calls_made        INTEGER NOT NULL DEFAULT 0,
  target            INTEGER NOT NULL DEFAULT 10,
  meetings_booked   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE scan_log (
  id                INTEGER PRIMARY KEY,
  source            TEXT NOT NULL,
  started_at        TEXT NOT NULL,
  finished_at       TEXT,
  pages             INTEGER,
  found             INTEGER,
  new               INTEGER,
  status            TEXT NOT NULL,          -- 'ok' | 'blocked' | 'error'
  detail            TEXT
);
```

### Statusy leada

```
new → called_no_answer → talked → meeting → contract
                     ↘ callback (z datą)
                     ↘ lost (z lost_reason)
                     ↘ dnc  (nie kontaktować — twarde)
```

`lost_reason` jest **obowiązkowy** przy przejściu na `lost`. Po miesiącu to jest materiał na poprawę skryptu rozmowy — bez tego pola nie da się poprawić niczego.

---

## 5. Moduły

### M1 — Radar ofert prywatnych ✱ priorytet

Zbiera świeże ogłoszenia **od właścicieli, bez pośrednika**, sprzedaż i wynajem, Gdańsk / Sopot / Gdynia.

Właściciel wystawiający mieszkanie sam jest jednocześnie ofertą i klientem — to najcenniejszy typ kontaktu dla agentki. To jest sedno całego systemu.

#### Kontrakt adaptera

```python
class Adapter(Protocol):
    name: str
    def search(self, cfg: SearchConfig) -> Iterator[RawListing]: ...
```

`RawListing` niesie surowe pola, bez normalizacji: `source`, `source_id`, `url`, `deal_type`, `title`, `description`, `price_raw`, `area_raw`, `location_raw`, `phone_raw`, `seller_label`, `posted_at_raw`.

Adapter **nie** zapisuje do bazy, **nie** normalizuje, **nie** klasyfikuje. Robi jedno: zwraca to, co znalazł.

#### Kolejność implementacji

| # | Portal | Uwagi |
|---|---|---|
| 1 | **OLX** | Najprostszy. Ma filtr „Osoby prywatne". Telefon często za jednym kliknięciem — Playwright. Zacznij tutaj i doprowadź do końca, zanim ruszysz dalej |
| 2 | **Otodom** | Ma filtr ofert prywatnych. Silniejsza ochrona (Cloudflare). Spodziewaj się, że będzie trzeba wolniej |
| 3 | Gratka, Morizon, Nieruchomosci-online | Mniejszy ruch, słabsza ochrona. Szybkie do dopisania po ustabilizowaniu dwóch pierwszych |
| 4 | Facebook Marketplace i grupy | **Faza 3.** Nie wcześniej |

#### Wykrywanie pośrednika — `classify.py`

Zwraca `agency_score` 0.0–1.0 oraz `seller_type`. Sygnały, każdy z wagą:

- flaga portalu „oferta prywatna" / „biuro nieruchomości" (najsilniejszy sygnał, gdy dostępny)
- słowa w opisie: `prowizja`, `biuro nieruchomości`, `zapraszam do współpracy`, `oferta biura`, `pośrednictwo`, `licencja`, `MLS`, `nasza oferta`, `polecam kontakt`
- ten sam `phone_e164` na więcej niż 3 aktywnych ogłoszeniach → prawie na pewno pośrednik
- ten sam numer w więcej niż 2 dzielnicach jednocześnie
- opis dłuższy niż 1500 znaków z nagłówkami i listą udogodnień (charakterystyczne dla biur)

Próg: `agency_score >= 0.6` → `agency`, `<= 0.3` → `private`, pomiędzy → `unknown`. `unknown` **trafia** na listę, ale niżej w rankingu.

Progi i wagi trzymaj w `config.yaml`, nie w kodzie — będą strojone na realnych danych.

#### Deduplikacja — `dedup.py`

To samo mieszkanie wisi na czterech portalach. Kolejność reguł:

1. **Identyczny `phone_e164` + metraż ±1 m² + cena ±3%** → ten sam obiekt. Reguła najmocniejsza.
2. Brak telefonu: **ulica + metraż ±1 m² + cena ±3%**.
3. **Simhash opisu**, odległość Hamminga ≤ 3 → ten sam obiekt (ogłoszenia bywają kopiowane słowo w słowo).

Grupa dostaje `dedup_group` (UUID). Na poranną listę trafia **jeden** rekord z grupy — ten z najstarszym `first_seen_at` (tam właściciel zaczął) i najbogatszymi danymi.

#### Ranking porannej listy — `scoring.py`

Zwraca top 15 na dziś. Składniki:

| Sygnał | Kierunek |
|---|---|
| Świeżość (`first_seen_at` dzisiaj) | ↑ mocno |
| `seller_type == 'private'` | ↑ mocno |
| Ogłoszenie starsze niż 10 dni i wciąż aktywne | ↑ (właściciel zmęczony, otwarcie C) |
| Zaległy `next_step_at` na istniejącym leadzie | ↑ najmocniej — follow-up bije nowy lead |
| Już dzwoniono w ciągu 14 dni bez `callback` | ↓ do zera |
| `do_not_call` | wykluczenie twarde |
| `seller_type == 'agency'` | wykluczenie |

Każda pozycja na liście niesie **sugerowane otwarcie** (A / B / C — patrz M4) wyliczone z wieku ogłoszenia i tego, czy w bazie jest pasujący kupujący.

---

### M3 — Baza i UI

Jedna strona, obsługiwana kciukiem, na telefonie.

**Widok „Dziś"** — domyślny i jedyny, który się liczy:
- licznik na górze: `wykonane / 10` — duży, to jest cel dnia
- lista 15 kart: imię lub „właściciel", dzielnica, metraż, cena, wiek ogłoszenia, sugerowane otwarcie
- na karcie: przycisk **Dzwoń** (`tel:` link) i cztery przyciski wyniku — `nie odebrał` / `rozmowa` / `odmowa` / `spotkanie`
- jedno tapnięcie = wpis do `call_log` + inkrementacja `daily_stats`

**Widok „Moje"** — leady w toku, sortowane po `next_step_at`. Zaległe na górze, na czerwono.

**Wpis notatki** — pole tekstowe z obsługą dyktowania systemowego (zwykły `<textarea>`, dyktowanie robi klawiatura telefonu).

Endpointy:

```
GET  /api/today                → poranna lista
GET  /api/leads?status=…       → leady
POST /api/leads/{id}/call      → {outcome, opener_used, objection, note}
POST /api/leads/{id}/status    → {status, next_step, next_step_at, lost_reason}
POST /api/contacts/{id}/dnc    → oznacz nie kontaktować
GET  /api/stats?days=30        → statystyki do wykresu
```

Bez logowania w v1, ale **nie wystawiaj tego na publiczny adres bez tokenu**. Cloudflare Tunnel z Access albo Tailscale — udokumentuj w README, który wybrałeś i dlaczego.

---

### M4 — Trener rozmów ✔ gotowe

Treść merytoryczna już istnieje jako osobna karta (trzy otwarcia, osiem obiekcji, formuła RODO, drill, debrief). **Nie generuj jej od nowa.**

Do zrobienia w kodzie tylko dwie rzeczy:

1. Pole `opener_used` (`A` / `B` / `C`) i `objection` w `call_log` — po miesiącu widać, które otwarcie działa i o co ludzie pytają najczęściej.
2. Ekran „Debrief" w UI: trzy pytania na koniec dnia, zapis do prostej tabeli `debrief(day, calls, stuck_phrase, tomorrow_fix)`.

Reguła produktowa, która ma być widoczna w UI: **licznik pokazuje wykonane połączenia, nie udane.** Odmowa inkrementuje licznik tak samo jak umówione spotkanie. To jest celowe — zdejmuje presję oceny, która jest realną blokadą użytkowniczki.

---

### M2 — Radar popytu (faza 2)

Ogłoszenia „poszukuję mieszkania", zapytania na OLX, posty w lokalnych grupach. Dużo więcej szumu niż w M1 — wymaga filtrowania treści, nie tylko strukturalnego. Nie zaczynaj, dopóki M1 nie dowozi stabilnie i dopóki nie ma pierwszych wykonanych telefonów.

### M5 — Marka osobista / Instagram (faza 3)

Świadomie ostatnie. Poza zakresem kodu w v1 — do rozpisania osobno.

---

## 6. Konfiguracja

`config.example.yaml`:

```yaml
area:
  cities: [Gdańsk, Sopot, Gdynia]
  districts: []            # pusta lista = wszystkie
search:
  deal_types: [sale, rent]
  sale:
    price_min: 250000
    price_max: 1800000
    area_min: 20
    area_max: 140
  rent:
    price_min: 1500
    price_max: 8000
    area_min: 18
    area_max: 120
scan:
  interval_minutes: 45
  max_pages_per_source: 5
  delay_seconds: [3, 8]
  sources: [olx]           # dokładaj po jednym, gdy poprzedni działa
classify:
  agency_threshold: 0.6
  private_threshold: 0.3
  phone_listings_agency_cutoff: 3
  keywords_agency:
    - prowizja
    - biuro nieruchomości
    - zapraszam do współpracy
    - pośrednictwo
list:
  size: 15
  daily_call_target: 10
notify:
  time: "08:00"
  channel: email           # email | none  (sms/whatsapp: faza 2)
```

---

## 7. Milestones — kolejność pracy

Realizuj po kolei. Nie zaczynaj kolejnego, zanim poprzedni nie spełnia kryteriów odbioru.

### M0 — Szkielet
- [ ] Struktura repo, `requirements.txt`, `config.py` z walidacją
- [ ] `db.py`: pełna schema, migracja idempotentna, `python -m ocrm.cli init`
- [ ] `models.py`, `normalize.py` (telefon → E.164 dla PL, cena, metraż, adres)
- **Odbiór:** `pytest tests/test_normalize.py` przechodzi; baza tworzy się od zera jedną komendą.

### M1a — Adapter OLX
- [ ] `adapters/base.py` + `adapters/olx.py`
- [ ] Filtr osób prywatnych, obsługa paginacji, pobranie numeru telefonu
- [ ] Respektowanie limitów i opóźnień z configu; log do `scan_log`
- [ ] Fixture'y HTML w `tests/fixtures/` i test parsera offline
- **Odbiór:** `python -m ocrm.cli scan --source olx` zwraca ≥ 20 ogłoszeń z Trójmiasta, z czego ≥ 80% ma numer telefonu; ponowny przebieg nie tworzy duplikatów.

### M1b — Klasyfikacja i dedup
- [ ] `classify.py` z wagami z configu
- [ ] `dedup.py` z trzema regułami
- [ ] `pipeline.py` spinający całość
- **Odbiór:** na próbce 100 ogłoszeń ręczna weryfikacja daje ≤ 10% błędnych klasyfikacji prywatny/pośrednik; żaden duplikat nie pojawia się dwa razy na liście.

### M3a — Baza leadów i ranking
- [ ] `scoring.py`, tworzenie `contacts` i `leads` z listingów
- [ ] `python -m ocrm.cli list --today` wypisuje 15 pozycji z sugerowanym otwarciem
- **Odbiór:** lista nigdy nie zawiera `do_not_call` ani `agency`; zaległe follow-upy są na górze.

### M3b — UI i API
- [ ] `api.py` + `web/index.html`, widoki „Dziś" i „Moje"
- [ ] Rejestracja połączenia jednym tapnięciem, licznik dnia
- [ ] Instrukcja wystawienia na telefon (Tunnel albo Tailscale) w README
- **Odbiór:** na telefonie da się przejść pełny cykl: otwórz listę → zadzwoń → oznacz wynik → wróć, bez zoomowania i bez literówek.

### M1c — Otodom i reszta portali
- [ ] `adapters/otodom.py`, potem gratka i morizon
- **Odbiór:** dedup poprawnie łączy to samo mieszkanie z OLX i Otodom.

### M4 — Trener w kodzie
- [ ] `opener_used`, `objection` w rejestracji połączenia
- [ ] Ekran debriefu
- **Odbiór:** po tygodniu da się wygenerować zestawienie: które otwarcie ma najwyższy odsetek `talked`.

### M-notify — Poranna wiadomość
- [ ] `notify.py`, wysyłka o 8:00, link do widoku „Dziś"
- **Odbiór:** wiadomość przychodzi codziennie; treść czytelna na ekranie blokady.

---

## 8. Ryzyka techniczne — miej je na uwadze przy każdym adapterze

| Ryzyko | Objaw | Reakcja |
|---|---|---|
| Ochrona antybotowa | 403, 429, captcha, pusta lista | Adapter wyłącza się na 60 min, wpis `status='blocked'` do `scan_log`, powiadomienie. **Nie** ponawiaj z krótszym interwałem |
| Zmiana struktury HTML | Parser zwraca 0 wyników przy statusie 200 | Test na fixture'ach wychwytuje to lokalnie; alert gdy przebieg zwraca 0 dwa razy z rzędu |
| Brak numeru w ogłoszeniu | Część OLX wymaga kliknięcia | Playwright klika; jeśli nie ma numeru, rekord i tak wchodzi do bazy z `phone_e164 = NULL` i nie trafia na listę |
| Fałszywe „prywatne" | Pośrednik podszywa się pod właściciela | Reguła „ten sam numer > 3 ogłoszenia" łapie większość; przewiduj ręczne oznaczanie w UI |
| Rozjazd stref czasowych | Poranna lista o złej porze | Wszystko w UTC w bazie, konwersja tylko przy wyświetlaniu |

---

## 9. Czego NIE budować w v1

Lista jest tak samo wiążąca jak reszta dokumentu.

- Automatycznego wysyłania wiadomości do właścicieli — to spam, zabije markę osobistą, zanim powstanie
- Integracji z Facebookiem w jakiejkolwiek formie
- Wielu użytkowników, ról, logowania hasłem
- Dockera, Kubernetesa, chmury, kolejek zadań
- Aplikacji mobilnej — strona ma wystarczyć
- Generatora treści na Instagram
- Systemu powiadomień push
- Modelu ML do czegokolwiek. Reguły w `classify.py` wystarczą i są debugowalne

---

## 10. Stan na dziś (03.09.2026)

| Element | Status |
|---|---|
| Brief projektowy, zakres, ryzyka | ✔ gotowe |
| Obszar działania: Gdańsk / Sopot / Gdynia | ✔ ustalone |
| Umowa z agencją — zgoda na bazę i markę | ✔ sprawdzone |
| Karta rozmowy: otwarcia, obiekcje, RODO, drill | ✔ gotowe |
| Kod — cokolwiek | ✘ nic |

**Do uzupełnienia przez Mata, nie przez agenta kodującego:** nazwa agencji, model rozliczenia prowizji, stawka. Potrzebne do karty rozmowy, nie do kodu — kod może ruszać bez tego.

**Otwarta decyzja:** czy skaner chodzi na laptopie Mata czy Mileny. Domyślnie zakładaj **laptop Mileny** — inaczej system przestaje działać w dniu, w którym Mat nie włączy komputera. Konsekwencja: instalacja musi być jednym skryptem, a uruchomienie jednym kliknięciem, bez terminala po jej stronie.

---

## 11. Pierwsze zadanie

Zbuduj **M0 + M1a**. Nic więcej.

Na koniec pokaż:
1. Drzewo utworzonych plików
2. Wynik `python -m ocrm.cli init` i `python -m ocrm.cli scan --source olx`
3. Pierwsze 10 rekordów z tabeli `listings`
4. Listę miejsc, w których musiałeś zgadywać strukturę HTML OLX — do weryfikacji na żywym serwisie
