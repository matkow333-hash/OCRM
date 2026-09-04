"""Wczytanie i walidacja config.yaml.

Zwraca obiekt Config (dataclass) z sekcjami area / search / scan / classify / list /
notify / db oraz SearchConfig przekazywany adapterom. Błędny plik podnosi ConfigError.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

DEAL_TYPES = ("sale", "rent")
NOTIFY_CHANNELS = ("email", "none")


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class AreaConfig:
    cities: list[str]
    districts: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DealFilter:
    price_min: int
    price_max: int
    area_min: float
    area_max: float


@dataclass(frozen=True)
class SearchSettings:
    deal_types: list[str]
    sale: DealFilter
    rent: DealFilter

    def filter_for(self, deal_type: str) -> DealFilter:
        return self.sale if deal_type == "sale" else self.rent


@dataclass(frozen=True)
class ScanSettings:
    interval_minutes: int
    max_pages_per_source: int
    delay_seconds: tuple[float, float]
    sources: list[str]
    fetch_details: bool = True
    fetch_phones: bool = True
    block_cooldown_minutes: int = 60
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )


DEFAULT_CLASSIFY_WEIGHTS = {
    "portal_flag_agency": 0.55,
    "portal_flag_private": -0.45,
    "keyword_hit": 0.15,
    "keyword_hit_max": 0.45,
    "keyword_private_hit": -0.2,
    "keyword_private_max": -0.4,
    "phone_many_listings": 0.5,
    "phone_many_districts": 0.3,
    "long_description": 0.15,
}

DEFAULT_KEYWORDS_PRIVATE = [
    "bezpośrednio",
    "bez pośredników",
    "bez prowizji",
    "od właściciela",
    "prywatnie",
]


@dataclass(frozen=True)
class ClassifySettings:
    agency_threshold: float
    private_threshold: float
    phone_listings_agency_cutoff: int
    keywords_agency: list[str]
    keywords_private: list[str] = field(default_factory=lambda: list(DEFAULT_KEYWORDS_PRIVATE))
    phone_districts_agency_cutoff: int = 2
    long_description_chars: int = 1500
    base_score: float = 0.35
    weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_CLASSIFY_WEIGHTS))


@dataclass(frozen=True)
class ListSettings:
    size: int
    daily_call_target: int


@dataclass(frozen=True)
class NotifySettings:
    time: str
    channel: str


@dataclass(frozen=True)
class SearchConfig:
    """Wycinek konfiguracji, który dostaje adapter. Adapter nie widzi nic więcej."""

    cities: list[str]
    districts: list[str]
    deal_types: list[str]
    filters: dict[str, DealFilter]
    max_pages: int
    delay_seconds: tuple[float, float]
    fetch_details: bool
    fetch_phones: bool
    user_agent: str

    def filter_for(self, deal_type: str) -> DealFilter:
        return self.filters[deal_type]


@dataclass(frozen=True)
class Config:
    area: AreaConfig
    search: SearchSettings
    scan: ScanSettings
    classify: ClassifySettings
    listing: ListSettings
    notify: NotifySettings
    db_path: Path

    def search_config(self) -> SearchConfig:
        return SearchConfig(
            cities=list(self.area.cities),
            districts=list(self.area.districts),
            deal_types=list(self.search.deal_types),
            filters={"sale": self.search.sale, "rent": self.search.rent},
            max_pages=self.scan.max_pages_per_source,
            delay_seconds=self.scan.delay_seconds,
            fetch_details=self.scan.fetch_details,
            fetch_phones=self.scan.fetch_phones,
            user_agent=self.scan.user_agent,
        )


def default_config_path() -> Path:
    return Path(os.environ.get("OCRM_CONFIG", "config.yaml"))


def load_config(path: str | Path | None = None) -> Config:
    path = Path(path) if path else default_config_path()
    if not path.exists():
        example = Path("config.example.yaml")
        raise ConfigError(
            f"Brak pliku konfiguracji: {path}. Skopiuj {example} do {path} i uzupełnij."
        )
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: oczekiwano mapy na najwyższym poziomie.")
    return parse_config(data)


def parse_config(data: dict) -> Config:
    area = _parse_area(_section(data, "area"))
    search = _parse_search(_section(data, "search"))
    scan = _parse_scan(_section(data, "scan"))
    classify = _parse_classify(_section(data, "classify"))
    listing = _parse_list(_section(data, "list"))
    notify = _parse_notify(_section(data, "notify"))
    db_path = Path(
        os.environ.get("OCRM_DB")
        or (data.get("db") or {}).get("path")
        or "data/ocrm.db"
    )
    return Config(
        area=area,
        search=search,
        scan=scan,
        classify=classify,
        listing=listing,
        notify=notify,
        db_path=db_path,
    )


def _section(data: dict, name: str) -> dict:
    value = data.get(name)
    if value is None:
        raise ConfigError(f"Brak sekcji '{name}' w konfiguracji.")
    if not isinstance(value, dict):
        raise ConfigError(f"Sekcja '{name}' musi być mapą.")
    return value


def _parse_area(raw: dict) -> AreaConfig:
    cities = raw.get("cities") or []
    if not isinstance(cities, list) or not cities:
        raise ConfigError("area.cities musi być niepustą listą miast.")
    districts = raw.get("districts") or []
    if not isinstance(districts, list):
        raise ConfigError("area.districts musi być listą (pusta = wszystkie).")
    return AreaConfig(cities=[str(c) for c in cities], districts=[str(d) for d in districts])


def _parse_search(raw: dict) -> SearchSettings:
    deal_types = raw.get("deal_types") or []
    if not isinstance(deal_types, list) or not deal_types:
        raise ConfigError("search.deal_types musi być niepustą listą.")
    unknown = [d for d in deal_types if d not in DEAL_TYPES]
    if unknown:
        raise ConfigError(f"search.deal_types: nieznane wartości {unknown}, dozwolone {list(DEAL_TYPES)}.")
    return SearchSettings(
        deal_types=[str(d) for d in deal_types],
        sale=_parse_deal_filter(raw, "sale"),
        rent=_parse_deal_filter(raw, "rent"),
    )


def _parse_deal_filter(raw: dict, name: str) -> DealFilter:
    block = raw.get(name)
    if not isinstance(block, dict):
        raise ConfigError(f"search.{name} musi być mapą z zakresami ceny i metrażu.")
    price_min = _positive_number(block, f"search.{name}.price_min")
    price_max = _positive_number(block, f"search.{name}.price_max")
    area_min = _positive_number(block, f"search.{name}.area_min")
    area_max = _positive_number(block, f"search.{name}.area_max")
    if price_min > price_max:
        raise ConfigError(f"search.{name}: price_min > price_max.")
    if area_min > area_max:
        raise ConfigError(f"search.{name}: area_min > area_max.")
    return DealFilter(
        price_min=int(price_min),
        price_max=int(price_max),
        area_min=float(area_min),
        area_max=float(area_max),
    )


def _positive_number(block: dict, dotted: str) -> float:
    key = dotted.rsplit(".", 1)[1]
    value = block.get(key)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ConfigError(f"{dotted} musi być liczbą.")
    if value <= 0:
        raise ConfigError(f"{dotted} musi być większe od zera.")
    return float(value)


def _parse_scan(raw: dict) -> ScanSettings:
    interval = raw.get("interval_minutes", 45)
    if not isinstance(interval, int) or interval < 30:
        raise ConfigError("scan.interval_minutes musi być liczbą całkowitą >= 30 (ludzkie tempo).")
    max_pages = raw.get("max_pages_per_source", 5)
    if not isinstance(max_pages, int) or not 1 <= max_pages <= 20:
        raise ConfigError("scan.max_pages_per_source musi być liczbą całkowitą 1..20.")
    delay = raw.get("delay_seconds", [3, 8])
    if not isinstance(delay, list) or len(delay) != 2:
        raise ConfigError("scan.delay_seconds musi być listą [min, max].")
    low, high = float(delay[0]), float(delay[1])
    if low < 1 or high < low:
        raise ConfigError("scan.delay_seconds: wymagane 1 <= min <= max.")
    sources = raw.get("sources") or []
    if not isinstance(sources, list) or not sources:
        raise ConfigError("scan.sources musi być niepustą listą źródeł.")
    cooldown = raw.get("block_cooldown_minutes", 60)
    if not isinstance(cooldown, int) or cooldown < 60:
        raise ConfigError("scan.block_cooldown_minutes musi być liczbą całkowitą >= 60.")
    return ScanSettings(
        interval_minutes=interval,
        max_pages_per_source=max_pages,
        delay_seconds=(low, high),
        sources=[str(s) for s in sources],
        fetch_details=bool(raw.get("fetch_details", True)),
        fetch_phones=bool(raw.get("fetch_phones", True)),
        block_cooldown_minutes=cooldown,
        user_agent=str(raw.get("user_agent") or ScanSettings.user_agent),
    )


def _parse_classify(raw: dict) -> ClassifySettings:
    agency = raw.get("agency_threshold", 0.6)
    private = raw.get("private_threshold", 0.3)
    for name, value in (("agency_threshold", agency), ("private_threshold", private)):
        if not isinstance(value, (int, float)) or not 0.0 <= float(value) <= 1.0:
            raise ConfigError(f"classify.{name} musi mieścić się w 0.0..1.0.")
    if float(private) >= float(agency):
        raise ConfigError("classify.private_threshold musi być mniejszy od agency_threshold.")
    cutoff = raw.get("phone_listings_agency_cutoff", 3)
    if not isinstance(cutoff, int) or cutoff < 1:
        raise ConfigError("classify.phone_listings_agency_cutoff musi być liczbą całkowitą >= 1.")
    keywords = raw.get("keywords_agency") or []
    if not isinstance(keywords, list):
        raise ConfigError("classify.keywords_agency musi być listą.")
    keywords_private = raw.get("keywords_private")
    if keywords_private is None:
        keywords_private = list(DEFAULT_KEYWORDS_PRIVATE)
    if not isinstance(keywords_private, list):
        raise ConfigError("classify.keywords_private musi być listą.")
    weights = dict(DEFAULT_CLASSIFY_WEIGHTS)
    raw_weights = raw.get("weights") or {}
    if not isinstance(raw_weights, dict):
        raise ConfigError("classify.weights musi być mapą nazwa: waga.")
    unknown = set(raw_weights) - set(DEFAULT_CLASSIFY_WEIGHTS)
    if unknown:
        raise ConfigError(f"classify.weights: nieznane wagi {sorted(unknown)}.")
    for key, value in raw_weights.items():
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ConfigError(f"classify.weights.{key} musi być liczbą.")
        weights[key] = float(value)
    base = raw.get("base_score", 0.35)
    if not isinstance(base, (int, float)) or not 0.0 <= float(base) <= 1.0:
        raise ConfigError("classify.base_score musi mieścić się w 0.0..1.0.")
    districts_cutoff = raw.get("phone_districts_agency_cutoff", 2)
    if not isinstance(districts_cutoff, int) or districts_cutoff < 1:
        raise ConfigError("classify.phone_districts_agency_cutoff musi być liczbą całkowitą >= 1.")
    long_chars = raw.get("long_description_chars", 1500)
    if not isinstance(long_chars, int) or long_chars < 200:
        raise ConfigError("classify.long_description_chars musi być liczbą całkowitą >= 200.")
    return ClassifySettings(
        agency_threshold=float(agency),
        private_threshold=float(private),
        phone_listings_agency_cutoff=cutoff,
        keywords_agency=[str(k).lower() for k in keywords],
        keywords_private=[str(k).lower() for k in keywords_private],
        phone_districts_agency_cutoff=districts_cutoff,
        long_description_chars=long_chars,
        base_score=float(base),
        weights=weights,
    )


def _parse_list(raw: dict) -> ListSettings:
    size = raw.get("size", 15)
    target = raw.get("daily_call_target", 10)
    if not isinstance(size, int) or size < 1:
        raise ConfigError("list.size musi być liczbą całkowitą >= 1.")
    if not isinstance(target, int) or target < 1:
        raise ConfigError("list.daily_call_target musi być liczbą całkowitą >= 1.")
    return ListSettings(size=size, daily_call_target=target)


def _parse_notify(raw: dict) -> NotifySettings:
    time_value = str(raw.get("time", "08:00"))
    hhmm = time_value.split(":")
    if len(hhmm) != 2 or not all(part.isdigit() for part in hhmm):
        raise ConfigError("notify.time musi mieć format HH:MM.")
    if not (0 <= int(hhmm[0]) <= 23 and 0 <= int(hhmm[1]) <= 59):
        raise ConfigError("notify.time poza zakresem doby.")
    channel = str(raw.get("channel", "email"))
    if channel not in NOTIFY_CHANNELS:
        raise ConfigError(f"notify.channel: dozwolone {list(NOTIFY_CHANNELS)}.")
    return NotifySettings(time=time_value, channel=channel)
