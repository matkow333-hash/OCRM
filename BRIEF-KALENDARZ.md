# Brief: kalendarz spotkań

Ustalenia z 7 września 2026. Dokument wiążący dla budowy.

## Czego dotyczy

Po rozmowie telefonicznej Milena ma móc umówić spotkanie z datą i adresem, zobaczyć
wszystkie terminy w kalendarzu wewnątrz aplikacji i po spotkaniu zapisać, jak poszło.

## Dziura, którą to zamyka

Dziś tapnięcie w „spotkanie" na karcie w zakładce Dziś zapisuje rozmowę, podbija licznik
i ustawia leadowi status `meeting`. Ale w `lib/leads.ts` stoi:

```
next_step_at = CASE WHEN outcome = 'callback' THEN ... ELSE NULL END
```

Data jest przy spotkaniu **jawnie kasowana**. Aplikacja wie, że spotkanie zostało umówione,
i nie wie ani kiedy, ani gdzie. Adresu i przebiegu nie ma gdzie zapisać.

## Decyzje

| Pytanie | Odpowiedź |
|---|---|
| Co pokazuje kalendarz | spotkania **i** oddzwonienia (`callback` ma już datę w `next_step_at`, dziś niewidoczną) |
| Ile spotkań na lead | historia wielu, osobna tabela `meetings` |
| Widok na telefonie | lista nadchodzących jako domyślna, siatka miesiąca pod przełącznikiem |

**Dlaczego osobna tabela, a nie kolumny w `leads`:** jeden właściciel miewa kilka spotkań
— pierwsze oglądanie, drugie z żoną, trzecie po obniżce ceny. Kolumny przechowałyby
tylko ostatnie i zjadłyby historię, a ta aplikacja jest zbudowana wokół liczenia tego,
co się faktycznie działo.

## Zakres

**1. Umówienie spotkania.** Tapnięcie w „spotkanie" podnosi arkusz: data i godzina,
adres, notatka. Adres podpowiadany z ogłoszenia (miasto, dzielnica, ulica są w bazie).
Data wymagana — API odrzuca żądanie bez niej, zamiast zapisywać po cichu. Ta sama
dyscyplina co przy `lost_reason` i `next_step_at`.

**2. Kalendarz.** Czwarta zakładka obok Dziś / Moje / Debrief. Pozycja niesie godzinę,
nazwisko, adres i **numer do tapnięcia** — najczęstsza potrzeba przy spotkaniu to
zadzwonić, że się spóźnię. Dzisiejsze terminy wyróżnione.

**3. Zamknięcie spotkania.** Termin, który minął, prosi o wynik: **umowa** /
**do przemyślenia** / **nie wyszło**, plus notatka. Wpina się w istniejące statusy
(`contract`, `callback`, `lost`), nie tworzy równoległego świata. Przy „nie wyszło"
powód wymagany.

## Baza

Migracja **wyłącznie dodająca** (`CREATE TABLE IF NOT EXISTS`) — baza jest jedna
i produkcyjna, nie ma kopii testowej. Skanera to nie dotyczy, spotkania żyją tylko
po stronie aplikacji.

```
meetings
  id, lead_id -> leads(id) ON DELETE CASCADE
  starts_at    TIMESTAMPTZ NOT NULL
  address      TEXT
  note         TEXT
  outcome      TEXT            -- NULL dopóki spotkanie się nie odbyło
  outcome_note TEXT
  created_at, updated_at
```

## Statystyki

Skoro spotkania będą zapisane, da się policzyć, ile umówień kończy się umową.
Z zastrzeżeniem obowiązującym w tym projekcie bez wyjątku: **liczba zawsze razem
z wielkością próbki, a poniżej progu wiarygodności „za mało danych"** zamiast procentu
policzonego z sześciu spotkań.

## Poza zakresem, świadomie

- **Synchronizacja z Kalendarzem Google** — osobne konto, osobna zgoda, osobny zakres.
- **Przypomnienia i powiadomienia** — aplikacja nie ma infrastruktury powiadomień;
  przypomnienie byłoby napisem, którego nikt nie zobaczy.
- **Spotkania cykliczne** — nie ten przypadek użycia.

## Warunki brzegowe bez zmian

- Wszystkie ekrany i endpointy poza `/login`, `/api/auth` i `/api/ingest` wymagają sesji.
- Numery pochodzą z publicznych ogłoszeń i nie są nikomu przekazywane.
- Każda statystyka podaje liczbę próbek.
