"use client";

/**
 * Debrief dnia (M4): ile połączeń, na czym się zacięło, co poprawiam jutro.
 * Pokazuje też, które otwarcie A/B/C najczęściej kończy się rozmową.
 */

import { useCallback, useEffect, useState } from "react";

type Entry = { day: string; calls: number; stuck_phrase: string | null; tomorrow_fix: string | null };
type Opener = { opener_used: string; calls: number; talked: number; meetings: number };

export default function DebriefView() {
  const [calls, setCalls] = useState(0);
  const [stuck, setStuck] = useState("");
  const [fix, setFix] = useState("");
  const [openers, setOpeners] = useState<Opener[]>([]);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [debrief, stats] = await Promise.all([
        fetch("/api/debrief", { cache: "no-store" }),
        fetch("/api/stats?days=30", { cache: "no-store" }),
      ]);
      if (debrief.ok) {
        const { data } = await debrief.json();
        setCalls(data.callsToday ?? 0);
        const entry: Entry | null = data.entry;
        setStuck(entry?.stuck_phrase ?? "");
        setFix(entry?.tomorrow_fix ?? "");
      }
      if (stats.ok) {
        const { data } = await stats.json();
        setOpeners(data.openers ?? []);
      }
    } catch {
      setError("Nie udało się pobrać danych.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function save(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      const response = await fetch("/api/debrief", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ stuck_phrase: stuck, tomorrow_fix: fix }),
      });
      if (!response.ok) throw new Error("Nie udało się zapisać.");
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : "Błąd zapisu.");
    }
  }

  return (
    <>
      <article className="card">
        <h2>Dziś wykonane: {calls}</h2>
        <p className="meta">Licznik liczy wykonane połączenia, nie udane. Odmowa liczy się tak samo.</p>
      </article>

      <form onSubmit={save}>
        {error && <p className="error">{error}</p>}
        <label className="note" htmlFor="stuck">
          Na jakim zdaniu się dziś zacięłaś?
        </label>
        <textarea
          id="stuck"
          className="field"
          rows={3}
          value={stuck}
          onChange={(event) => setStuck(event.target.value)}
        />
        <label className="note" htmlFor="fix">
          Co poprawiasz jutro? Jedna rzecz.
        </label>
        <textarea
          id="fix"
          className="field"
          rows={3}
          value={fix}
          onChange={(event) => setFix(event.target.value)}
        />
        <button className="primary" type="submit">
          {saved ? "Zapisane" : "Zapisz debrief"}
        </button>
      </form>

      {openers.length > 0 && (
        <article className="card" style={{ marginTop: 18 }}>
          <h2>Otwarcia, ostatnie 30 dni</h2>
          {openers.map((row) => (
            <p key={row.opener_used} className="meta">
              {row.opener_used}: {row.calls} poł.<span className="dot" />
              {row.talked} rozmów<span className="dot" />
              {row.meetings} spotkań<span className="dot" />
              {row.calls > 0 ? Math.round((row.talked / row.calls) * 100) : 0}% skuteczności
            </p>
          ))}
        </article>
      )}
    </>
  );
}
