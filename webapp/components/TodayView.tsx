"use client";

/**
 * Widok „Dziś": licznik wykonanych połączeń i karty do obdzwonienia.
 * Jedno tapnięcie w wynik zapisuje call_log i podbija licznik - także przy odmowie.
 */

import { useCallback, useEffect, useState } from "react";
import type { TodayItem } from "@/lib/scoring";

type Counter = { made: number; target: number; meetings: number };

const OUTCOMES: Array<{ key: string; label: string }> = [
  { key: "no_answer", label: "nie odebrał" },
  { key: "talked", label: "rozmowa" },
  { key: "refused", label: "odmowa" },
  { key: "meeting", label: "spotkanie" },
];

export default function TodayView() {
  const [items, setItems] = useState<TodayItem[]>([]);
  const [counter, setCounter] = useState<Counter>({ made: 0, target: 10, meetings: 0 });
  const [done, setDone] = useState<Record<number, string>>({});
  const [pending, setPending] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const response = await fetch("/api/today", { cache: "no-store" });
      if (!response.ok) throw new Error("Nie udało się pobrać listy.");
      const { data } = await response.json();
      setItems(data.items);
      setCounter(data.counter);
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

  async function record(item: TodayItem, outcome: string) {
    setPending(item.leadId);
    setCounter((current) => ({ ...current, made: current.made + 1 }));
    setDone((current) => ({ ...current, [item.leadId]: outcome }));
    try {
      const response = await fetch(`/api/leads/${item.leadId}/call`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ outcome, opener_used: item.opener }),
      });
      if (!response.ok) throw new Error("Nie udało się zapisać wyniku.");
    } catch (problem) {
      setCounter((current) => ({ ...current, made: Math.max(0, current.made - 1) }));
      setDone((current) => {
        const next = { ...current };
        delete next[item.leadId];
        return next;
      });
      setError(problem instanceof Error ? problem.message : "Błąd zapisu.");
    } finally {
      setPending(null);
    }
  }

  const progress = Math.min(100, Math.round((counter.made / Math.max(1, counter.target)) * 100));

  return (
    <>
      <div className="counter">
        <b>{counter.made}</b>
        <span className="of">/ {counter.target}</span>
        <span className="label">
          wykonane połączenia
          <br />
          {counter.meetings} spotkań
        </span>
      </div>
      <div className="bar">
        <i style={{ width: `${progress}%` }} />
      </div>

      {error && <p className="error">{error}</p>}
      {loading && <p className="empty">Ładuję listę…</p>}
      {!loading && items.length === 0 && (
        <p className="empty">
          Brak pozycji na dziś.
          <br />
          Uruchom skaner na laptopie, żeby dosypać świeże ogłoszenia.
        </p>
      )}

      {items.map((item) => (
        <article key={item.leadId} className={`card${item.overdue ? " overdue" : ""}`}>
          <h2>{item.name}</h2>
          <p className="meta">
            {[item.district, item.city].filter(Boolean).join(", ") || "brak lokalizacji"}
            {item.areaM2 && <span className="dot">{item.areaM2} m²</span>}
            {item.rooms && <span className="dot">{item.rooms} pok.</span>}
            {item.price && <span className="dot">{item.price.toLocaleString("pl-PL")} zł</span>}
          </p>
          <div className="tags">
            <span className="tag opener">otwarcie {item.opener}</span>
            <span className="tag">{item.dealType === "rent" ? "wynajem" : "sprzedaż"}</span>
            <span className={`tag${item.ageDays >= 10 ? " tired" : ""}`}>
              {item.ageDays <= 0 ? "dzisiaj" : `${item.ageDays} dni`}
            </span>
            {item.overdue && <span className="tag late">zaległy follow-up</span>}
          </div>

          <div className="actions">
            <a className="call" href={`tel:${item.phone}`}>
              Dzwoń · {item.phone}
            </a>
            {item.url && (
              <a
                className="offer"
                href={item.url}
                target="_blank"
                rel="noopener noreferrer"
                aria-label="Otwórz ogłoszenie w przeglądarce"
              >
                Oferta ↗
              </a>
            )}
          </div>

          <div className="outcomes">
            {OUTCOMES.map((outcome) => (
              <button
                key={outcome.key}
                className={done[item.leadId] === outcome.key ? "done" : ""}
                disabled={pending === item.leadId || Boolean(done[item.leadId])}
                onClick={() => record(item, outcome.key)}
              >
                {outcome.label}
              </button>
            ))}
          </div>
        </article>
      ))}
    </>
  );
}
