"""Catalog of licensable module ids (RFC-0087).

Versioned in code and synced into the vendor issuer SQLite catalog on launch.
"""
from __future__ import annotations

from typing import Any

CATALOG_VERSION = 1

LICENSE_MODULES: tuple[dict[str, Any], ...] = (
    {
        "id": "blue-team",
        "label": "Blue team / DFIR",
        "requires_le": False,
        "kind": "runtime",
    },
    {
        "id": "red-team",
        "label": "Red team runtime",
        "requires_le": True,
        "kind": "runtime",
    },
    {
        "id": "hexstrike",
        "label": "HexStrike suite",
        "requires_le": False,
        "kind": "suite",
    },
    {
        "id": "computer-use",
        "label": "Computer use / desktop",
        "requires_le": False,
        "kind": "runtime",
    },
    {
        "id": "specialist.security",
        "label": "Security specialist pack",
        "requires_le": False,
        "kind": "pack",
    },
    {
        "id": "domain.finance",
        "label": "Finance domain pack",
        "requires_le": False,
        "kind": "pack",
    },
)

_KNOWN_IDS = frozenset(str(item["id"]) for item in LICENSE_MODULES)


def module_ids() -> list[str]:
    return [str(item["id"]) for item in LICENSE_MODULES]


def catalog_rows() -> list[dict[str, Any]]:
    return [dict(item) for item in LICENSE_MODULES]


def normalize_module_id(value: str) -> str:
    key = (value or "").strip().lower().replace("_", "-")
    if key in {"blue", "soc", "dfir"}:
        return "blue-team"
    if key in {"red", "pentest"}:
        return "red-team"
    if key in {"hexstrike-suite", "hexstrike_suite"}:
        return "hexstrike"
    if key in {"computer_use", "cua"}:
        return "computer-use"
    return key


def requires_law_enforcement(module_id: str) -> bool:
    key = normalize_module_id(module_id)
    for item in LICENSE_MODULES:
        if item["id"] == key:
            return bool(item["requires_le"])
    return key == "red-team"


def is_known_module(module_id: str) -> bool:
    return normalize_module_id(module_id) in _KNOWN_IDS
