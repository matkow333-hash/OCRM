/**
 * Ekran „Debrief": trzy pytania na koniec dnia i skuteczność otwarć A/B/C.
 */

import DebriefView from "@/components/DebriefView";

export const dynamic = "force-dynamic";

export default function Page() {
  return (
    <>
      <h1>Debrief</h1>
      <p className="note">Trzy pytania na koniec dnia. Zajmuje minutę, po tygodniu widać wzorzec.</p>
      <DebriefView />
    </>
  );
}
