"use client";

/**
 * Lista leadów w toku z akcjami: umów termin, oznacz stracony, nie kontaktować.
 */

import { useCallback, useEffect, useState } from "react";

type Lead = {
  id: number;
  contact_id: number;
  name: string;
  phone: string;
  status: string;
  next_step_at: string | null;
  overdue: boolean;
  calls: number;
  city: string | null;
  district: string | null;
  price: number | null;
  area_m2: number | null;
};

const STATUS_LABEL: Record<string, string> = {
  new: "nowy",
  called_no_answer: "nie odebrał",
  talked: "rozmowa",
  callback: "oddzwonić",
  meeting: "spotkanie",
  contract: "umowa",
  lost: "stracony",
  dnc: "nie kontaktować",
};

export default function LeadsView() {
  const [leads, setLeads] = useState<Lead[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const response = await fetch("/api/leads", { cache: "no-store" });
      if (!response.ok) throw new Error("Nie udało się pobrać leadów.");
      const { data } = await response.json();
      setLeads(data.items);
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

  async function schedule(lead: Lead) {
    const when = window.prompt("Kiedy oddzwonić? (RRRR-MM-DD)", nextBusinessDay());
    if (!when) return;
    await send(`/api/leads/${lead.id}/status`, {
      status: "callback",
      next_step: "oddzwonić",
      next_step_at: new Date(`${when}T09:00:00`).toISOString(),
    });
  }

  async function lose(lead: Lead) {
    const reason = window.prompt("Powód (obowiązkowy — po miesiącu to materiał na poprawę skryptu):");
    if (!reason) return;
    await send(`/api/leads/${lead.id}/status`, { status: "lost", lost_reason: reason });
  }

  async function block(lead: Lead) {
    if (!window.confirm(`Oznaczyć ${lead.phone} jako „nie kontaktować"? Tego się nie cofa z telefonu.`)) return;
    await send(`/api/contacts/${lead.contact_id}/dnc`, {});
  }

  async function send(url: string, body: Record<string, unknown>) {
    try {
      const response = await fetch(url, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!response.ok) {
        const parsed = await response.json().catch(() => ({}));
        throw new Error(parsed.error ?? "Nie udało się zapisać.");
      }
      await load();
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : "Błąd zapisu.");
    }
  }

  if (loading) return <p className="empty">Ładuję…</p>;

  return (
    <>
      {error && <p className="error">{error}</p>}
      {leads.length === 0 && <p className="empty">Nic w toku. Wszystko domknięte albo jeszcze nie zaczęte.</p>}
      {leads.map((lead) => (
        <article key={lead.id} className={`card${lead.overdue ? " overdue" : ""}`}>
          <h2>{lead.name}</h2>
          <p className="meta">
            {[lead.district, lead.city].filter(Boolean).join(", ") || "brak lokalizacji"}
            {lead.area_m2 && <span className="dot">{lead.area_m2} m²</span>}
            {lead.price && <span className="dot">{lead.price.toLocaleString("pl-PL")} zł</span>}
          </p>
          <div className="tags">
            <span className="tag">{STATUS_LABEL[lead.status] ?? lead.status}</span>
            <span className="tag">{lead.calls} poł.</span>
            {lead.next_step_at && (
              <span className={`tag${lead.overdue ? " late" : ""}`}>
                {new Date(lead.next_step_at).toLocaleDateString("pl-PL")}
              </span>
            )}
          </div>
          <a className="call" href={`tel:${lead.phone}`}>
            Dzwoń · {lead.phone}
          </a>
          <div className="outcomes">
            <button onClick={() => schedule(lead)}>termin</button>
            <button onClick={() => lose(lead)}>stracony</button>
            <button onClick={() => block(lead)}>nie dzwonić</button>
            <a className="call" style={{ height: "auto" }} href={`sms:${lead.phone}`}>
              SMS
            </a>
          </div>
        </article>
      ))}
    </>
  );
}

function nextBusinessDay(): string {
  const date = new Date();
  date.setDate(date.getDate() + (date.getDay() === 5 ? 3 : date.getDay() === 6 ? 2 : 1));
  return date.toISOString().slice(0, 10);
}
