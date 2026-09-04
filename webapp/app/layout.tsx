/**
 * Szkielet aplikacji: metadane PWA, dolna nawigacja, rejestracja service workera.
 * Zwraca powłokę wspólną dla wszystkich ekranów.
 */

import type { Metadata, Viewport } from "next";
import Nav from "@/components/Nav";
import ServiceWorker from "@/components/ServiceWorker";
import "./globals.css";

export const metadata: Metadata = {
  title: "OCRM",
  description: "Poranna lista telefonów do właścicieli mieszkań w Trójmieście",
  manifest: "/manifest.json",
  appleWebApp: { capable: true, statusBarStyle: "black-translucent", title: "OCRM" },
};

export const viewport: Viewport = {
  themeColor: "#0f1115",
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  viewportFit: "cover",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="pl">
      <body>
        <div className="wrap">{children}</div>
        <Nav />
        <ServiceWorker />
      </body>
    </html>
  );
}
