"""Kontrakt adaptera oraz wspólny pobieracz stron: robots.txt, opóźnienia, wykrywanie blokad.

Adapter zwraca iterator RawListing i nic więcej: nie normalizuje, nie klasyfikuje, nie pisze do bazy.
Fetcher.get() zwraca treść HTML albo podnosi Blocked, gdy portal odmawia obsługi.
"""

from __future__ import annotations

import random
import time
import urllib.robotparser
from typing import Iterator, Protocol
from urllib.parse import urljoin, urlsplit

import httpx

from ..config import SearchConfig
from ..models import RawListing

BLOCK_STATUS = {401, 403, 407, 429, 451}
CAPTCHA_MARKERS = (
    "captcha",
    "px-captcha",
    "cf-challenge",
    "just a moment",
    "attention required",
    "verify you are human",
)


class Blocked(RuntimeError):
    """Portal odmówił obsługi: status blokujący, captcha albo pusta odpowiedź."""


class Adapter(Protocol):
    name: str

    def search(self, cfg: SearchConfig) -> Iterator[RawListing]: ...


class Fetcher:
    def __init__(
        self,
        user_agent: str,
        delay_seconds: tuple[float, float] = (3.0, 8.0),
        timeout: float = 30.0,
        respect_robots: bool = True,
        client: httpx.Client | None = None,
        sleep=time.sleep,
    ) -> None:
        self.user_agent = user_agent
        self.delay_seconds = delay_seconds
        self.respect_robots = respect_robots
        self._sleep = sleep
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self._first_request = True
        self._client = client or httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.6",
            },
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "Fetcher":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def allowed(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        parser = self._robots_for(url)
        if parser is None:
            return True
        return parser.can_fetch(self.user_agent, url)

    def get(self, url: str) -> str:
        if not self.allowed(url):
            raise Blocked(f"robots.txt zabrania pobrania {url}")
        self._wait()
        try:
            response = self._client.get(url)
        except httpx.HTTPError as exc:
            raise Blocked(f"błąd sieci przy {url}: {exc}") from exc
        if response.status_code in BLOCK_STATUS:
            raise Blocked(f"status {response.status_code} przy {url}")
        if response.status_code >= 500:
            raise Blocked(f"status {response.status_code} przy {url}")
        body = response.text
        if _looks_like_captcha(body):
            raise Blocked(f"captcha / challenge przy {url}")
        return body

    def _wait(self) -> None:
        if self._first_request:
            self._first_request = False
            return
        low, high = self.delay_seconds
        self._sleep(random.uniform(low, high))

    def _robots_for(self, url: str) -> urllib.robotparser.RobotFileParser | None:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin in self._robots:
            return self._robots[origin]
        parser: urllib.robotparser.RobotFileParser | None
        try:
            response = self._client.get(urljoin(origin, "/robots.txt"))
            if response.status_code >= 400:
                parser = None
            else:
                parser = urllib.robotparser.RobotFileParser()
                parser.parse(response.text.splitlines())
        except httpx.HTTPError:
            parser = None
        self._robots[origin] = parser
        return parser


def _looks_like_captcha(body: str) -> bool:
    if not body or len(body) < 512:
        return bool(body) and any(marker in body.lower() for marker in CAPTCHA_MARKERS)
    head = body[:4000].lower()
    return any(marker in head for marker in CAPTCHA_MARKERS)
