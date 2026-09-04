"""Wysyłka ogłoszeń ze skanera do aplikacji na Vercelu (POST /api/ingest).

Zwraca PushResult z liczbami: wysłane / dodane / zaktualizowane / założone leady.
Adres i token biorą się z .env (OCRM_APP_URL, INGEST_TOKEN). Bez nich push nie rusza.
"""

from __future__ import annotations

import json
import os
import sqlite3
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

BATCH_SIZE = 200
TIMEOUT_SECONDS = 60

COLUMNS = (
    "source",
    "source_id",
    "url",
    "deal_type",
    "city",
    "district",
    "street",
    "price",
    "area_m2",
    "rooms",
    "floor",
    "title",
    "description",
    "content_hash",
    "phone_e164",
    "seller_type",
    "agency_score",
    "dedup_group",
    "first_seen_at",
    "last_seen_at",
    "is_active",
)


class PushError(RuntimeError):
    pass


@dataclass
class PushResult:
    sent: int = 0
    inserted: int = 0
    updated: int = 0
    leads_created: int = 0
    batches: int = 0


def load_env(path: str | Path = ".env") -> None:
    """Wczytuje proste pary KLUCZ=wartość z .env, nie nadpisując istniejących zmiennych."""
    file = Path(path)
    if not file.exists():
        return
    for line in file.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def pending_listings(conn: sqlite3.Connection, since: str | None = None, limit: int | None = None) -> list[dict]:
    clauses = ["is_active = 1"]
    params: list[object] = []
    if since:
        clauses.append("last_seen_at >= ?")
        params.append(since)
    query = f"SELECT {', '.join(COLUMNS)} FROM listings WHERE {' AND '.join(clauses)} ORDER BY id"
    if limit:
        query += " LIMIT ?"
        params.append(limit)
    return [_row_to_payload(row) for row in conn.execute(query, params).fetchall()]


def push(conn: sqlite3.Connection, since: str | None = None, limit: int | None = None) -> PushResult:
    base_url = os.environ.get("OCRM_APP_URL", "").rstrip("/")
    token = os.environ.get("INGEST_TOKEN", "")
    if not base_url:
        raise PushError("Brak OCRM_APP_URL w .env - nie wiem, dokąd wysłać dane.")
    if len(token) < 16:
        raise PushError("Brak INGEST_TOKEN w .env albo token krótszy niż 16 znaków.")

    listings = pending_listings(conn, since=since, limit=limit)
    result = PushResult()
    for start in range(0, len(listings), BATCH_SIZE):
        batch = listings[start : start + BATCH_SIZE]
        answer = _post(f"{base_url}/api/ingest", token, {"listings": batch})
        result.sent += len(batch)
        result.inserted += int(answer.get("inserted", 0))
        result.updated += int(answer.get("updated", 0))
        result.leads_created += int(answer.get("leads_created", 0))
        result.batches += 1
    return result


def _post(url: str, token: str, payload: dict) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise PushError(f"Aplikacja odrzuciła dane ({exc.code}): {detail}") from exc
    except urllib.error.URLError as exc:
        raise PushError(f"Nie mogę połączyć się z {url}: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise PushError("Aplikacja odpowiedziała czymś, co nie jest JSON-em.") from exc
    return body.get("data", body)


def _row_to_payload(row: sqlite3.Row) -> dict:
    payload = {column: row[column] for column in COLUMNS}
    payload["is_active"] = bool(payload["is_active"])
    return payload
