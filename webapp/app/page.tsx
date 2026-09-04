/**
 * Ekran domyślny: widok „Dziś".
 * Zwraca licznik dnia i listę kart do obdzwonienia.
 */

import TodayView from "@/components/TodayView";

export const dynamic = "force-dynamic";

export default function Page() {
  return <TodayView />;
}
