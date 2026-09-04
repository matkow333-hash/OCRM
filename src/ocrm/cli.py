"""Wejście z terminala: init / scan / push / list.

Zwraca kod wyjścia 0 przy powodzeniu, 1 przy błędzie konfiguracji, zablokowanym źródle
lub nieudanej wysyłce do aplikacji.
"""

from __future__ import annotations

import argparse
import sys

from . import db
from .config import ConfigError, load_config
from .pipeline import scan_all
from .push import PushError, load_env, push


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ocrm", description="OCRM - radar ofert prywatnych")
    parser.add_argument("--config", default=None, help="ścieżka do config.yaml")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="utwórz bazę i schema")

    scan = sub.add_parser("scan", help="jeden przebieg skanera")
    scan.add_argument("--source", action="append", help="źródło, można podać wielokrotnie")
    scan.add_argument("--push", action="store_true", help="po przebiegu wyślij dane do aplikacji")

    send = sub.add_parser("push", help="wyślij ogłoszenia do aplikacji na Vercelu")
    send.add_argument("--since", help="tylko widziane od tego znacznika czasu (ISO 8601)")
    send.add_argument("--limit", type=int, help="maksymalna liczba rekordów")

    listing = sub.add_parser("list", help="wypisz ogłoszenia z bazy")
    listing.add_argument("--limit", type=int, default=10)
    listing.add_argument("--private", action="store_true", help="tylko oferty prywatne z numerem")
    return parser


def cmd_init(cfg) -> int:
    conn = db.connect(cfg.db_path)
    try:
        db.init_db(conn)
        tables = [
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
            )
        ]
    finally:
        conn.close()
    print(f"Baza gotowa: {cfg.db_path}")
    print(f"Tabele ({len(tables)}): {', '.join(tables)}")
    return 0


def cmd_push(cfg, since: str | None, limit: int | None) -> int:
    load_env()
    conn = db.connect(cfg.db_path)
    try:
        result = push(conn, since=since, limit=limit)
    except PushError as exc:
        print(f"Push nie przeszedł: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()
    print(
        f"Wysłane: {result.sent} (paczek: {result.batches}) | dodane: {result.inserted} "
        f"| zaktualizowane: {result.updated} | nowe leady: {result.leads_created}"
    )
    return 0


def cmd_list(cfg, limit: int, private_only: bool) -> int:
    conn = db.connect(cfg.db_path)
    try:
        clause = "WHERE is_active = 1"
        if private_only:
            clause += " AND seller_type = 'private' AND phone_e164 IS NOT NULL"
        rows = conn.execute(
            f"""
            SELECT id, deal_type, city, district, price, area_m2, rooms,
                   phone_e164, seller_type, agency_score, substr(title, 1, 40) AS title
              FROM listings {clause} ORDER BY first_seen_at DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        print("Baza pusta. Uruchom `python -m ocrm.cli scan`.")
        return 0
    for row in rows:
        parts = [
            f"#{row['id']}",
            row["deal_type"],
            ", ".join(filter(None, (row["district"], row["city"]))) or "-",
            f"{row['area_m2']} m2" if row["area_m2"] else "-",
            f"{row['price']} zl" if row["price"] else "-",
            row["phone_e164"] or "brak numeru",
            f"{row['seller_type']} ({row['agency_score']})",
        ]
        print(" | ".join(str(part) for part in parts))
    return 0


def cmd_scan(cfg, sources: list[str] | None) -> int:
    conn = db.connect(cfg.db_path)
    try:
        db.init_db(conn)
        results = scan_all(conn, cfg, sources)
    finally:
        conn.close()
    failed = False
    for result in results:
        line = (
            f"[{result.source}] status={result.status} "
            f"znalezione={result.found} nowe={result.new} strony={result.pages}"
        )
        if result.detail:
            line += f" | {result.detail}"
        print(line)
        if result.status in {"blocked", "error"}:
            failed = True
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        print(f"Błąd konfiguracji: {exc}", file=sys.stderr)
        return 1
    if args.command == "init":
        return cmd_init(cfg)
    if args.command == "scan":
        code = cmd_scan(cfg, args.source)
        if code == 0 and args.push:
            return cmd_push(cfg, None, None)
        return code
    if args.command == "push":
        return cmd_push(cfg, args.since, args.limit)
    if args.command == "list":
        return cmd_list(cfg, args.limit, args.private)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
