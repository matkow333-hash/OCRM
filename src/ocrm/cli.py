"""Wejście z terminala: `python -m ocrm.cli init` i `python -m ocrm.cli scan --source olx`.

Zwraca kod wyjścia 0 przy powodzeniu, 1 przy błędzie konfiguracji lub zablokowanym źródle.
"""

from __future__ import annotations

import argparse
import sys

from . import db
from .config import ConfigError, load_config
from .pipeline import scan_all


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ocrm", description="OCRM - radar ofert prywatnych")
    parser.add_argument("--config", default=None, help="ścieżka do config.yaml")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="utwórz bazę i schema")

    scan = sub.add_parser("scan", help="jeden przebieg skanera")
    scan.add_argument("--source", action="append", help="źródło, można podać wielokrotnie")
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
        return cmd_scan(cfg, args.source)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
