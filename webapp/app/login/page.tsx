/**
 * Ekran logowania: PIN wymieniany na ciasteczko sesji.
 */

import LoginForm from "@/components/LoginForm";

export default function Page() {
  return (
    <>
      <h1>OCRM</h1>
      <p className="note">Wpisz PIN, żeby wejść na listę.</p>
      <LoginForm />
    </>
  );
}
