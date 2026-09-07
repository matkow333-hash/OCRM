"use client";

/**
 * Widok „Kalendarz": nadchodzące terminy w dwóch trybach, lista i siatka miesiąca.
 * Lista jest domyślna, bo na wąskim ekranie czyta się lepiej i nie wymaga celowania
 * w małe kratki; siatka służy do przeglądu całości i po tapnięciu dnia pokazuje
 * jego terminy pod spodem.
 *
 * Termin, którego godzina minęła, prosi o zamknięcie: umowa, do przemyślenia
 * albo nie wyszło. Przy „nie wyszło" powód jest wymagany po stronie API, więc
 * przycisk zapisu jest tu nieaktywny, dopóki pole jest puste - żeby nie wysyłać
 * żądania, o którym z góry wiadomo, że zostanie odrzucone.
 *
 * Numer telefonu jest przy każdym terminie klikalny, bo najczęstsza potrzeba
 * w drodze na spotkanie to zadzwonić, że się spóźnię.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { readJson } from "@/lib/api";

type Entry = {
  kind: "meeting" | "callback";
  id: number;
  leadId: number;
  startsAt: string;
  name: string | null;
  phone: string | null;
  address: string | null;
  note: string | null;
  listingUrl: string | null;
  price: number | null;
  outcome: string | null;
  past: boolean;
};

type Stats = {
  sample: number;
  contracts: number;
  minSample: number;
  enough: boolean;
  rate: number | null;
};

const WYNIKI: Array<{ key: string; label: string }> = [
  { key: "contract", label: "umowa" },
  { key: "thinking", label: "do przemyślenia" },
  { key: "failed", label: "nie wyszło" },
];

const DNI = ["pon", "wt", "śr", "czw", "pt", "sob", "ndz"];

function dzienKlucz(iso: string): string {
  return new Date(iso).toLocaleDateString("pl-PL", {
    weekday: "long",
    day: "numeric",
    month: "long",
  });
}

function godzina(iso: string): string {
  return new Date(iso).toLocaleTimeString("pl-PL", { hour: "2-digit", minute: "2-digit" });
}

export default function CalendarView() {
  const [entries, setEntries] = useState<Entry[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [tryb, setTryb] = useState<"lista" | "miesiac">("lista");
  const [miesiac, setMiesiac] = useState(() => {
    const teraz = new Date();
    return new Date(teraz.getFullYear(), teraz.getMonth(), 1);
  });
  const [wybranyDzien, setWybranyDzien] = useState<string | null>(null);
  const [zamykany, setZamykany] = useState<number | null>(null);
  const [wynik, setWynik] = useState<string>("contract");
  const [notatka, setNotatka] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const response = await fetch("/api/calendar", { cache: "no-store" });
      const data = await readJson<{ entries: Entry[]; stats: Stats }>(
        response,
        "Nie udało się pobrać kalendarza.",
      );
      setEntries(data.entries);
      setStats(data.stats);
      setError(null);
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : "Błąd sieci.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function zamknij(entry: Entry) {
    if (wynik === "failed" && !notatka.trim()) return;
    setPending(true);
    try {
      const response = await fetch(`/api/meetings/${entry.id}/outcome`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ outcome: wynik, note: notatka.trim() || null }),
      });
      await readJson(response, "Nie udało się zapisać wyniku spotkania.");
      setZamykany(null);
      setNotatka("");
      setWynik("contract");
      await load();
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : "Błąd sieci.");
    } finally {
      setPending(false);
    }
  }

  const dni = useMemo(() => {
    const grupy = new Map<string, Entry[]>();
    for (const entry of entries) {
      const klucz = new Date(entry.startsAt).toISOString().slice(0, 10);
      const lista = grupy.get(klucz) ?? [];
      lista.push(entry);
      grupy.set(klucz, lista);
    }
    return grupy;
  }, [entries]);

  const kratki = useMemo(() => {
    const pierwszy = new Date(miesiac.getFullYear(), miesiac.getMonth(), 1);
    const przesuniecie = (pierwszy.getDay() + 6) % 7;
    const ile = new Date(miesiac.getFullYear(), miesiac.getMonth() + 1, 0).getDate();
    const pola: Array<{ klucz: string | null; numer: number | null }> = [];
    for (let i = 0; i < przesuniecie; i++) pola.push({ klucz: null, numer: null });
    for (let d = 1; d <= ile; d++) {
      const data = new Date(miesiac.getFullYear(), miesiac.getMonth(), d);
      const klucz = `${data.getFullYear()}-${String(data.getMonth() + 1).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
      pola.push({ klucz, numer: d });
    }
    return pola;
  }, [miesiac]);

  if (loading) return <p className="empty">Wczytuję kalendarz…</p>;
  if (error) return <p className="error">{error}</p>;

  const nadchodzace = entries.filter((entry) => !entry.past || !entry.outcome);
  const doZamkniecia = entries.filter(
    (entry) => entry.kind === "meeting" && entry.past && !entry.outcome,
  );

  return (
    <>
      <div className="bar">
        <span className="counter">
          {nadchodzace.length === 0
            ? "Brak zaplanowanych terminów"
            : `${nadchodzace.length} ${nadchodzace.length === 1 ? "termin" : "terminy"} w planie`}
        </span>
        <div className="tryby">
          <button className={tryb === "lista" ? "active" : ""} onClick={() => setTryb("lista")}>
            lista
          </button>
          <button className={tryb === "miesiac" ? "active" : ""} onClick={() => setTryb("miesiac")}>
            miesiąc
          </button>
        </div>
      </div>

      {stats && (
        <p className="note">
          {stats.enough
            ? `Spotkania kończące się umową: ${stats.rate}% (${stats.contracts} z ${stats.sample}).`
            : `Za mało danych na skuteczność spotkań: zamkniętych ${stats.sample}, potrzeba ${stats.minSample}.`}
        </p>
      )}

      {doZamkniecia.length > 0 && (
        <p className="note late">
          {doZamkniecia.length === 1
            ? "Jedno spotkanie czeka na zamknięcie."
            : `${doZamkniecia.length} spotkania czekają na zamknięcie.`}
        </p>
      )}

      {tryb === "miesiac" && (
        <section className="miesiac">
          <div className="bar">
            <button
              onClick={() =>
                setMiesiac(new Date(miesiac.getFullYear(), miesiac.getMonth() - 1, 1))
              }
              aria-label="Poprzedni miesiąc"
            >
              ‹
            </button>
            <span className="counter">
              {miesiac.toLocaleDateString("pl-PL", { month: "long", year: "numeric" })}
            </span>
            <button
              onClick={() =>
                setMiesiac(new Date(miesiac.getFullYear(), miesiac.getMonth() + 1, 1))
              }
              aria-label="Następny miesiąc"
            >
              ›
            </button>
          </div>
          <div className="siatka">
            {DNI.map((dzien) => (
              <span key={dzien} className="naglowek">
                {dzien}
              </span>
            ))}
            {kratki.map((pole, index) => {
              if (!pole.klucz) return <span key={`pusta-${index}`} className="kratka pusta" />;
              const ile = dni.get(pole.klucz)?.length ?? 0;
              return (
                <button
                  key={pole.klucz}
                  className={`kratka${ile ? " ma" : ""}${wybranyDzien === pole.klucz ? " wybrany" : ""}`}
                  onClick={() => setWybranyDzien(wybranyDzien === pole.klucz ? null : pole.klucz)}
                  aria-label={`${pole.numer}, terminów: ${ile}`}
                >
                  {pole.numer}
                  {ile > 0 && <span className="kropka" aria-hidden="true" />}
                </button>
              );
            })}
          </div>
        </section>
      )}

      {(() => {
        const widoczne =
          tryb === "miesiac" && wybranyDzien
            ? (dni.get(wybranyDzien) ?? [])
            : tryb === "miesiac"
              ? []
              : entries;

        if (tryb === "miesiac" && !wybranyDzien) {
          return <p className="empty">Tapnij dzień, żeby zobaczyć jego terminy.</p>;
        }
        if (widoczne.length === 0) {
          return <p className="empty">Nic na ten czas nie jest zaplanowane.</p>;
        }

        let ostatniDzien = "";
        return widoczne.map((entry) => {
          const dzien = dzienKlucz(entry.startsAt);
          const naglowek = dzien !== ostatniDzien;
          ostatniDzien = dzien;
          return (
            <div key={`${entry.kind}-${entry.id}`}>
              {naglowek && <h2 className="dzien">{dzien}</h2>}
              <article
                className={`card${entry.past && !entry.outcome ? " overdue" : ""}`}
              >
                <h3>
                  <span className="godzina">{godzina(entry.startsAt)}</span> {entry.name}
                </h3>
                <div className="tags">
                  <span className={`tag${entry.kind === "callback" ? "" : " opener"}`}>
                    {entry.kind === "meeting" ? "spotkanie" : "oddzwonić"}
                  </span>
                  {entry.outcome && (
                    <span className="tag">
                      {WYNIKI.find((w) => w.key === entry.outcome)?.label ?? entry.outcome}
                    </span>
                  )}
                  {entry.price && (
                    <span className="tag">{entry.price.toLocaleString("pl-PL")} zł</span>
                  )}
                </div>
                <p className="meta">{entry.address || "brak adresu"}</p>
                {entry.note && <p className="note">{entry.note}</p>}

                <div className="actions">
                  {entry.phone && (
                    <a className="call" href={`tel:${entry.phone}`}>
                      Dzwoń · {entry.phone}
                    </a>
                  )}
                  {entry.listingUrl && (
                    <a
                      className="offer"
                      href={entry.listingUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      Oferta ↗
                    </a>
                  )}
                </div>

                {entry.kind === "meeting" && entry.past && !entry.outcome && (
                  <div className="zamkniecie">
                    {zamykany === entry.id ? (
                      <>
                        <div className="outcomes">
                          {WYNIKI.map((pozycja) => (
                            <button
                              key={pozycja.key}
                              className={wynik === pozycja.key ? "done" : ""}
                              onClick={() => setWynik(pozycja.key)}
                            >
                              {pozycja.label}
                            </button>
                          ))}
                        </div>
                        <label className="field">
                          <span>
                            {wynik === "failed" ? "Powód (wymagany)" : "Notatka (opcjonalnie)"}
                          </span>
                          <textarea
                            value={notatka}
                            onChange={(event) => setNotatka(event.target.value)}
                            rows={2}
                          />
                        </label>
                        <div className="actions">
                          <button
                            className="primary"
                            disabled={pending || (wynik === "failed" && !notatka.trim())}
                            onClick={() => zamknij(entry)}
                          >
                            Zapisz wynik
                          </button>
                          <button className="secondary" onClick={() => setZamykany(null)}>
                            Anuluj
                          </button>
                        </div>
                      </>
                    ) : (
                      <button className="primary" onClick={() => setZamykany(entry.id)}>
                        Jak poszło?
                      </button>
                    )}
                  </div>
                )}
              </article>
            </div>
          );
        });
      })()}
    </>
  );
}
