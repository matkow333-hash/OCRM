"""Rejestr adapterów portali.

Zwraca klasę adaptera po nazwie źródła używanej w config.scan.sources.
"""

from __future__ import annotations

from .base import Adapter, Blocked, Fetcher
from .olx import OlxAdapter
from .otodom import OtodomAdapter

REGISTRY: dict[str, type] = {
    OlxAdapter.name: OlxAdapter,
    OtodomAdapter.name: OtodomAdapter,
}


def get_adapter(name: str):
    try:
        return REGISTRY[name]()
    except KeyError:
        raise KeyError(f"Nieznane źródło '{name}'. Dostępne: {sorted(REGISTRY)}") from None


__all__ = ["Adapter", "Blocked", "Fetcher", "OlxAdapter", "OtodomAdapter", "REGISTRY", "get_adapter"]
