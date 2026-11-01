"""Loads firmable_ontology.yaml and exposes the canonical targets + identifier checksums."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

from .paths import ONTOLOGY_DIR

ONTOLOGY_PATH = ONTOLOGY_DIR / "firmable_ontology.yaml"
# Sections a mapping config may target; each becomes a node/edge rule in the graph loader.
SECTIONS = ("entity", "address", "person", "licence", "ban", "related_party")


@lru_cache
def load() -> dict:
    return yaml.safe_load(ONTOLOGY_PATH.read_text())


@lru_cache
def raw_text() -> str:
    return ONTOLOGY_PATH.read_text()


@lru_cache
def targets() -> dict[str, dict]:
    """Mappable canonical fields, e.g. {'entity.abn': {...}, 'licence.status': {...}}."""
    o = load()
    return {f"{section}.{name}": spec for section in SECTIONS
            for name, spec in o[section].items()}


def enum_values(target: str) -> list[str] | None:
    return targets().get(target, {}).get("values")


def abn_valid(abn: str) -> bool:
    """ATO algorithm: subtract 1 from the first digit, weight, sum, divisible by 89."""
    if len(abn) != 11 or not abn.isdigit():
        return False
    weights = [10, 1, 3, 5, 7, 9, 11, 13, 15, 17, 19]
    digits = [int(c) for c in abn]
    digits[0] -= 1
    return sum(d * w for d, w in zip(digits, weights)) % 89 == 0


def acn_valid(acn: str) -> bool:
    """ASIC algorithm: weights 8..1 over the first 8 digits; check digit = (10 - sum % 10) % 10."""
    if len(acn) != 9 or not acn.isdigit():
        return False
    total = sum(int(c) * w for c, w in zip(acn[:8], range(8, 0, -1)))
    return (10 - total % 10) % 10 == int(acn[8])
