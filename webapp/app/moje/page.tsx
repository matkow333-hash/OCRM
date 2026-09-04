/**
 * Ekran „Moje": leady w toku, zaległe na górze i na czerwono.
 */

import LeadsView from "@/components/LeadsView";

export const dynamic = "force-dynamic";

export default function Page() {
  return (
    <>
      <h1>Moje leady</h1>
      <p className="note">Sortowane po terminie następnego kroku. Zaległe na górze.</p>
      <LeadsView />
    </>
  );
}
