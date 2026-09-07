/**
 * Ekran „Kalendarz": nadchodzące spotkania i oddzwonienia w jednym miejscu.
 */

import CalendarView from "@/components/CalendarView";

export const dynamic = "force-dynamic";

export default function Page() {
  return (
    <>
      <h1>Kalendarz</h1>
      <p className="note">Spotkania i terminy oddzwonienia. Numer przy każdym wpisie dzwoni jednym tapnięciem.</p>
      <CalendarView />
    </>
  );
}
