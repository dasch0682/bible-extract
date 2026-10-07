"""Places of the context (schema 2 `context.places`).

A place comes from OpenBible.info and takes the confidence of that dataset's identification,
mapped to our four levels by data/place_rules.yml (computed by the code, never by a model).
Only the name, the OpenBible id and the Wikidata id are kept: the geometry is never used
(part of it comes from OpenStreetMap, ODbL), so a weak or disputed place is a name without
coordinates by construction. A model only writes the name in the target language.

Theographic and ACAI also list places per verse but give no identification confidence,
so they are not used here.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

import datasets as ds
from provenance import dataset_source, merge_sources

RULES_PATH = Path(__file__).parent / "data" / "place_rules.yml"
LEVELS = {"certain", "probable", "approximate", "disputed"}
SPECIAL_ACTIONS = {"exclude"} | LEVELS
SPECIAL_VALUES = {"not_a_place", "not_a_proper_name", "nonspecific_place", "multiple_locations", "unknown_place",
                  "recursive"}      # the values listed by the dataset (README, "Special resolutions")
_SUFFIX = re.compile(r"\s+\d+$")


class RulesError(ValueError):
    pass


def load_rules(path=RULES_PATH) -> dict:
    r = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    vt = r.get("vote_total") or {}
    if not all(isinstance(vt.get(k), int) for k in ("probable", "approximate")) or vt["approximate"] > vt["probable"]:
        raise RulesError("vote_total: integers probable >= approximate are required")
    if r.get("no_score") not in LEVELS:
        raise RulesError("no_score: must be one of the four levels")
    special = r.get("special") or {}
    if set(special) != SPECIAL_VALUES or not set(special.values()) <= SPECIAL_ACTIONS:
        raise RulesError("special: every value the dataset lists needs `exclude` or a level")
    return r


def display_name(friendly_id: str) -> str:
    """'Ephraim 2' -> 'Ephraim': OpenBible numbers homonyms; the number is for the id, not for the name."""
    return _SUFFIX.sub("", friendly_id or "").strip()


def rate(place: dict, rules: dict):
    """Level of a place, or None when the place is left out (not a place)."""
    if place.get("special"):
        action = rules["special"].get(place["special"])
        if action is None:
            raise RulesError(f"unknown special resolution: {place['special']!r}")
        return None if action == "exclude" else action
    total = place.get("total")
    if total is None:
        return rules["no_score"]
    if total >= rules["vote_total"]["probable"]:
        return "probable"
    if total >= rules["vote_total"]["approximate"]:
        return "approximate"
    return "disputed"


def build_places(verse_ids: list, openbible: dict, rules: dict, registry: dict,
                 localize_name=lambda name: None) -> dict:
    """{'places': [...], 'sources': [...], 'flags': [...]} for an entry, sorted by OpenBible id.

    `localize_name(name)` returns the place name in the target language, or None (the dataset
    name is then kept and the entry is flagged `place_name_not_localized`).
    """
    found = {}
    for vid in verse_ids:
        for p in openbible.get(ds.verse_key(vid), []):
            found.setdefault(p["id"], p)
    places, records, flags = [], [], []
    for pid in sorted(found):
        p = found[pid]
        level = rate(p, rules)
        if level is None:
            continue
        base = display_name(p["name"])
        name = localize_name(base)
        if name is None:
            name = base
            flags.append(f"place_name_not_localized:{pid}")
        record = dataset_source(f"openbible:{pid}", "openbible", "place_data", registry)
        item = {"name": name, "place_id": pid, "confidence": level, "sources": [record["id"]]}
        if p.get("wikidata"):
            item["wikidata"] = p["wikidata"]
        places.append(item)
        records.append(record)
    return {"places": places, "sources": merge_sources(records), "flags": flags}
