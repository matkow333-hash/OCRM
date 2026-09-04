"use client";

/**
 * Dolny pasek nawigacji: Dziś / Moje / Debrief.
 * Zwraca null na ekranie logowania.
 */

import Link from "next/link";
import { usePathname } from "next/navigation";

const TABS = [
  { href: "/", label: "Dziś" },
  { href: "/moje", label: "Moje" },
  { href: "/debrief", label: "Debrief" },
];

export default function Nav() {
  const pathname = usePathname();
  if (pathname === "/login") return null;
  return (
    <nav className="nav">
      {TABS.map((tab) => (
        <Link key={tab.href} href={tab.href} className={pathname === tab.href ? "active" : ""}>
          {tab.label}
        </Link>
      ))}
    </nav>
  );
}
