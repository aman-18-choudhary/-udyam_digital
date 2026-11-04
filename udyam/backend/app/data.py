"""Loads the case CSVs once and exposes them as plain Python structures."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from functools import lru_cache

from .config import DATA_DIR


def _read(name: str) -> list[dict]:
    with open(DATA_DIR / name, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


@dataclass(frozen=True)
class Product:
    id: str
    category: str
    name: str
    description: str
    unit: str
    price_min: int
    price_max: int
    setup: int
    min_contract: int
    tiers: tuple[int, ...]
    min_employees: int
    min_sites: int
    requires_gstin: bool
    requires_one_of: tuple[str, ...]
    install_days: int
    segments: tuple[str, ...]


@lru_cache(maxsize=1)
def catalogue() -> dict[str, Product]:
    out: dict[str, Product] = {}
    for r in _read("product_catalogue.csv"):
        out[r["product_id"]] = Product(
            id=r["product_id"],
            category=r["category"],
            name=r["product_name"],
            description=r["description"],
            unit=r["unit"],
            price_min=int(r["price_min_inr_per_month"]),
            price_max=int(r["price_max_inr_per_month"]),
            setup=int(r["one_time_setup_inr"]),
            min_contract=int(r["min_contract_months"]),
            tiers=tuple(int(x) for x in r["available_city_tiers"].split(";")),
            min_employees=int(r["min_employees"]),
            min_sites=int(r["min_sites"]),
            requires_gstin=r["requires_gstin"] == "Y",
            requires_one_of=tuple(x for x in r["requires_one_of"].split("|") if x),
            install_days=int(r["typical_install_days"]),
            segments=tuple(r["target_segments"].split(";")),
        )
    return out


@lru_cache(maxsize=1)
def gstin_registry() -> dict[str, dict]:
    return {r["gstin"]: r for r in _read("mock_gstin_registry.csv")}


@lru_cache(maxsize=1)
def udyam_registry() -> dict[str, dict]:
    return {r["udyam_number"]: r for r in _read("mock_udyam_registry.csv")}


@lru_cache(maxsize=1)
def leads() -> list[dict]:
    return _read("smb_leads.csv")


@lru_cache(maxsize=1)
def city_tiers() -> dict[str, int]:
    """city (lower case) -> tier, learned from the lead file."""
    out: dict[str, int] = {}
    for r in leads():
        out[r["city"].strip().lower()] = int(r["city_tier"])
    return out


@lru_cache(maxsize=1)
def city_state() -> dict[str, str]:
    out: dict[str, str] = {}
    for r in leads():
        out[r["city"].strip().lower()] = r["state"].strip()
    return out
