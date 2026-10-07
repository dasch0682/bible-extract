"""Source records for an entry's `sources` list (schema 2).

Every cited id (a verse, a dataset record) must be listed once in the entry's
`sources` with its type, dataset id and license. The dataset ids and licenses
come from data/sources.yml, never from the code.
"""
from __future__ import annotations

from pathlib import Path

import yaml

REGISTRY_PATH = Path(__file__).parent / "data" / "sources.yml"


def load_registry(path=REGISTRY_PATH) -> dict:
    """{dataset id: {name, license, attribution, ...}} from data/sources.yml."""
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))["sources"]


def known_datasets(registry: dict) -> set:
    """Dataset ids accepted by validate.check_sources."""
    return set(registry)


def _license(registry: dict, dataset_id: str) -> str:
    if dataset_id not in registry:
        raise KeyError(f"unknown dataset id: {dataset_id!r} (not in data/sources.yml)")
    return str(registry[dataset_id]["license"])


def verse_source(verse_id: str, dataset_id: str, registry: dict) -> dict:
    """Source record of a verse of the language corpus (dataset_id comes from languages.yml)."""
    return {"id": verse_id, "type": "bible_text", "dataset": dataset_id, "license": _license(registry, dataset_id)}


def dataset_source(record_id: str, dataset_id: str, kind: str, registry: dict) -> dict:
    """Source record of one record of an external dataset (kind: e.g. 'speaker_data')."""
    return {"id": record_id, "type": kind, "dataset": dataset_id, "license": _license(registry, dataset_id)}


def merge_sources(*lists) -> list:
    """Concatenate source lists, keeping the first record of each id (order preserved)."""
    seen, out = set(), []
    for records in lists:
        for r in records:
            if r["id"] not in seen:
                seen.add(r["id"])
                out.append(r)
    return out
