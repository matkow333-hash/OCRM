"use client";

/**
 * Formularz PIN-u. Po udanym logowaniu przenosi na widok „Dziś".
 */

import { useRouter } from "next/navigation";
import { useState } from "react";

export default function LoginForm() {
  const router = useRouter();
  const [pin, setPin] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const response = await fetch("/api/auth", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ pin }),
      });
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.error ?? "Zły PIN.");
      }
      router.replace("/");
      router.refresh();
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : "Nie udało się zalogować.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit}>
      {error && <p className="error">{error}</p>}
      <input
        className="field"
        type="password"
        inputMode="numeric"
        autoComplete="current-password"
        placeholder="PIN"
        value={pin}
        onChange={(event) => setPin(event.target.value)}
        required
      />
      <button className="primary" type="submit" disabled={busy}>
        {busy ? "Sprawdzam…" : "Wejdź"}
      </button>
    </form>
  );
}
