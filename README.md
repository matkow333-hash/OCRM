# OCRM — Operational Center of Research and Marketing

Radar publicznych ogłoszeń mieszkaniowych od właścicieli w Trójmieście (Gdańsk, Sopot, Gdynia).
Cel systemu jest jeden: **10 wykonanych połączeń dziennie**. Specyfikacja: [OCRM.md](OCRM.md).

Stan repo: **M0 (szkielet) + M1a (adapter OLX)**. Klasyfikacja, dedup, ranking, API i UI
jeszcze nie istnieją — kolejne milestone'y z sekcji 7 specyfikacji.

## Instalacja

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
python -m playwright install chromium
cp config.example.yaml config.yaml
cp .env.example .env
```

`config.yaml` i `.env` są w `.gitignore` — w repo leżą tylko wzorce.

## Użycie

```bash
python -m ocrm.cli init                  # tworzy data/ocrm.db i schema (idempotentnie)
python -m ocrm.cli scan --source olx     # jeden przebieg skanera
python -m pytest                         # testy offline, bez ruchu sieciowego
```

`scan` bez `--source` bierze listę z `config.yaml` → `scan.sources`.
Kod wyjścia 1 oznacza blokadę portalu albo błąd — nadaje się do monitoringu w cronie.

Harmonogram (co 45 minut, zgodnie z `scan.interval_minutes`):

```cron
*/45 * * * * cd /sciezka/do/OCRM && .venv/bin/python -m ocrm.cli scan >> data/scan.log 2>&1
```

Windows: Task Scheduler, to samo polecenie, wyzwalacz „powtarzaj co 45 minut”.

## Zasady pracy skanera

Wymuszone w kodzie, nie w dobrych chęciach:

- `config.py` odrzuca `interval_minutes < 30`, `delay_seconds` poniżej 1 s i `max_pages_per_source > 20`
- `Fetcher` czyta `robots.txt` każdej domeny i nie pobiera tego, co zabronione
- losowe opóźnienie 3–8 s między requestami, jeden wątek, jeden portal naraz
- status 401/403/407/429/451, 5xx albo captcha → `Blocked` → wpis `status='blocked'` w `scan_log`
  i **godzina karencji** (`scan.block_cooldown_minutes`); kolejny `scan` w tym czasie kończy się
  statusem `cooldown` i nie dotyka portalu
- dwa przebiegi z rzędu z zerem wyników zostawiają w `scan_log.detail` ostrzeżenie o parserze
- ogłoszenie bez numeru telefonu i tak wchodzi do bazy z `phone_e164 = NULL`

## Struktura

```
src/ocrm/
├── config.py     wczytanie i walidacja config.yaml, SearchConfig dla adapterów
├── db.py         schema SQLite, migracja idempotentna, upsert ogłoszeń, scan_log
├── models.py     RawListing, Listing, Contact, Lead
├── normalize.py  telefon E.164, cena, metraż, pokoje, piętro, adres
├── pipeline.py   adapter → normalize → zapis, log przebiegu
├── cli.py        init / scan
└── adapters/
    ├── base.py   kontrakt Adapter, Fetcher (robots.txt, opóźnienia, wykrywanie blokad)
    └── olx.py    OLX: budowa URL z filtrem osób prywatnych, parser stanu i DOM, odsłanianie numeru
tests/
├── test_normalize.py    normalizacja pól
├── test_config_db.py    walidacja configu, idempotentna migracja, upsert
├── test_olx_adapter.py  parser OLX na fixture'ach + przebieg pipeline bez sieci
└── fixtures/            zapisane fragmenty HTML
```

## Adapter OLX — co jest zgadywane

Struktura HTML OLX nie jest kontraktem i zmienia się bez zapowiedzi. Poniższe miejsca
zostały napisane na podstawie znanych wzorców serwisu i **wymagają weryfikacji na żywym
serwisie**. Każde z nich ma fallback, więc pomyłka w jednym punkcie nie wywraca przebiegu.

| # | Miejsce | Co zgadnięte | Fallback |
|---|---|---|---|
| 1 | Ścieżka kategorii | `/nieruchomosci/mieszkania/sprzedaz/{miasto}/` i `.../wynajem/{miasto}/` | brak — do sprawdzenia w pierwszej kolejności |
| 2 | Slug miasta | `gdansk`, `sopot`, `gdynia` (bez znaków diakrytycznych) | brak |
| 3 | Filtr osób prywatnych | `search[filter_enum_private_business][0]=private` | flaga sprzedawcy z treści oferty |
| 4 | Filtry zakresów | `search[filter_float_price:from|to]`, `search[filter_float_m:from|to]` | filtrowanie po stronie bazy |
| 5 | Sortowanie od najnowszych | `search[order]=created_at:desc` | kolejność domyślna |
| 6 | Paginacja | `page=N` | zatrzymanie na pierwszej pustej stronie |
| 7 | Stan strony w JS | `window.__PRERENDERED_STATE__` (JSON zakodowany jako string) lub `__NEXT_DATA__` | parser DOM |
| 8 | Miejsce listy ogłoszeń w JSON | szukane heurystycznie: najdłuższa lista słowników z `id`, `url`, `title` | parser DOM |
| 9 | Nazwy pól ogłoszenia | `params[].key`: `price`, `m`, `rooms`, `floor_select`; `location.{city,district,region}.name`; `business`; `contact.phone` | pola pomijane, gdy nieobecne |
| 10 | Karta na liście (DOM) | `div[data-cy="l-card"]`, tytuł w `h4`, `[data-testid="ad-price"]`, `[data-testid="location-date"]` | `div[data-testid="l-card"]`, `h6` |
| 11 | ID oferty z URL | wzorzec `-ID<alfanumeryczny>.html` | `id` ze stanu JSON |
| 12 | Strona oferty | `[data-cy="ad_description"]`, `[data-testid="trader-title"]`, `[data-testid="ad-parameters-container"]` | szukanie fraz „osoba prywatna” / „firma” w treści |
| 13 | Odsłonięcie numeru | przycisk `[data-testid="show-phone"]` / tekst „Pokaż numer”, numer w `a[href^="tel:"]` lub `[data-testid="contact-phone"]` | brak numeru → `phone_e164 = NULL` |

Weryfikacja: otwórz jedną stronę wyników i jedną ofertę w przeglądarce, zapisz HTML do
`tests/fixtures/`, popraw selektory i uruchom `python -m pytest tests/test_olx_adapter.py`.
Fixture'y w repo są syntetyczne — odwzorowują założoną strukturę, nie pobrane strony.

## Stan weryfikacji M1a

| Kryterium odbioru M1a | Stan |
|---|---|
| Parser działa offline na fixture'ach | ✔ `python -m pytest` — 74 testy |
| Ponowny przebieg nie tworzy duplikatów | ✔ test `test_scan_source_stores_only_tricity_and_is_idempotent` |
| Blokada → `scan_log.status='blocked'` + karencja | ✔ test + potwierdzone na żywym 403 |
| `scan --source olx` zwraca ≥ 20 ogłoszeń, ≥ 80% z numerem | ✘ **niezweryfikowane** |

Ostatni punkt wymaga pierwszego uruchomienia na maszynie z dostępem do `www.olx.pl`.
Dopóki nie przejdzie, M1a nie jest odebrane i nie ruszamy dalej.

## Dostęp z telefonu (M3b, jeszcze nie wdrożone)

Do rozstrzygnięcia przy UI, obie drogi udokumentowane z góry:

- **Tailscale** — rekomendowany na start. Laptop i telefon w jednej sieci prywatnej,
  bez publicznego adresu, bez konfiguracji DNS. Nic nie wystawia się do internetu,
  więc brak logowania w v1 nie jest dziurą. Koszt: aplikacja na telefonie musi być włączona.
- **Cloudflare Tunnel + Access** — publiczny adres z bramką logowania e-mailem.
  Wygodniejszy (zwykły link, działa wszędzie), ale wymaga domeny i konta Cloudflare,
  a bez włączonego Access wystawia bazę leadów do sieci.

Reguła: dopóki nie ma tokenu ani logowania, **UI nie wychodzi na publiczny adres**.

## RODO

Numery pochodzą z publicznych ogłoszeń. Tabela `contacts` ma pole `do_not_call` — kontakt
z tą flagą nigdy nie trafia na poranną listę, także wtedy, gdy ogłoszenie wróci pod nowym
`source_id` (flaga wisi przy numerze, nie przy ogłoszeniu). Dane nie są nikomu przekazywane.
