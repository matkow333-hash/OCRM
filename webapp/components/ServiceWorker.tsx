"use client";

/**
 * Rejestruje service workera, żeby aplikację dało się zainstalować na ekranie głównym.
 * Zwraca null - nic nie renderuje.
 */

import { useEffect } from "react";

export default function ServiceWorker() {
  useEffect(() => {
    if (!("serviceWorker" in navigator)) return;
    navigator.serviceWorker.register("/sw.js").catch(() => undefined);
  }, []);
  return null;
}
