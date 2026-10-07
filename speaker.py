"""Speaker or narrator of an excerpt (schema 2 `speaker` field).

Identification is done by the code from the speaker-quotations dataset, cross-checked
with the ACAI people of the verses around the quotation. The confidence level is
computed here, never by a model. A model only writes the speaker's name in the target
language (role `speaker` in models.yml); it is never a source.

An ambiguous case (several different speakers in one excerpt) gives a null speaker
with reason `not_identified`, the candidates, and the review flag `speaker_ambiguous`.
"""
from __future__ import annotations

import re
import unicodedata

import datasets as ds
import localize
from provenance import dataset_source, merge_sources, verse_source

NAME_PROMPT_VERSION = "speaker-name-1"

# Flags that force a human decision in the review page.
REVIEW_FLAGS = {"speaker_ambiguous", "name_not_localized"}

_PAREN = re.compile(r"\(([^)]*)\)")


# --- matching with ACAI ---

def _norm(s: str) -> str:
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    return re.sub(r"\s+", " ", s).strip().lower()


def _forms(label: str) -> set:
    """Comparable forms of a label: the whole label and each parenthetical.

    The label without its parentheses is deliberately not a form: the parenthetical is what
    tells people apart ('John (the Baptist)' must not match a plain 'John').
    """
    forms = {_norm(label)}
    forms.update(_norm(m) for m in _PAREN.findall(label))
    return {f for f in forms if f}


def acai_agreement(label: str, people: list) -> list:
    """ACAI people whose label has a form equal to a form of the speaker label (exact, no fuzzy match)."""
    want = _forms(label)
    return [p for p in people if want & _forms(p.get("label") or "")]


# --- identification (code only) ---

def _previous_key(key: str):
    """Key of the previous verse in the same chapter, or None at a chapter start."""
    return f"{key[:5]}{int(key[5:]) - 1:03d}" if int(key[5:]) > 1 else None


def ranges_at(ranges: list, key: str) -> list:
    return [r for r in ranges if r["start"] <= key <= r["end"]]


def identify(verses: list, ranges: list, acai_people: dict) -> dict:
    """Who speaks in the excerpt `verses` (ids like 'JHN.14.6'), according to the datasets.

    Returns {label, role, hypothetical, types, records, agreement, keys, covered, total, candidates, flags}.
    `label` is None when nobody is identified or several speakers compete.
    """
    keys = [ds.verse_key(v) for v in verses]
    per_label = {}                      # label -> ranges covering at least one verse of the excerpt
    covered = 0
    for k in keys:
        here = ranges_at(ranges, k)
        covered += bool(here)
        for r in here:
            per_label.setdefault(r["speaker"], [])
            if r not in per_label[r["speaker"]]:
                per_label[r["speaker"]].append(r)
    out = {"label": None, "role": None, "hypothetical": False, "types": [], "records": [], "agreement": [], "keys": keys,
           "covered": covered, "total": len(keys), "candidates": sorted(per_label), "flags": []}
    if not per_label:
        out["flags"].append("speaker_not_identified")
        return out
    if len(per_label) > 1:
        out["flags"].append("speaker_ambiguous")
        return out
    (label, recs), = per_label.items()
    out.update(label=label, role="narrator" if label.lower().startswith("narrator") else "speaker",
               hypothetical=all(r["type"] == "Hypothetical" for r in recs),
               types=sorted({r["type"] for r in recs}),
               records=[(r["start"], r["end"]) for r in recs])
    window = set(keys)
    before = _previous_key(min(r["start"] for r in recs))     # the verse that introduces the quotation
    if before:
        window.add(before)
    people = [p for k in sorted(window) for p in acai_people.get("people", {}).get(k, [])]
    out["agreement"] = acai_agreement(label, people)
    if out["hypothetical"]:
        out["flags"].append("speaker_hypothetical")
    if covered < len(keys):
        out["flags"].append("speaker_partial_coverage")
    return out


def rate(ident: dict):
    """Confidence computed by the code: high, medium or low (None when nobody is identified).

    high   one speaker, confirmed by ACAI, whole excerpt inside the quotation
    medium one speaker given by the dataset alone
    low    the quotation is hypothetical, or the excerpt is only partly inside the quotation
           without ACAI confirmation

    The dataset does not document its other quote types (Implicit, Quotation...), so they
    are recorded in `types` but never change the level. Levels are to be confirmed on a sample.
    """
    if ident["label"] is None:
        return None
    if ident["hypothetical"]:
        return "low"
    partial = "speaker_partial_coverage" in ident["flags"]
    if ident["agreement"]:
        return "medium" if partial else "high"
    return "low" if partial else "medium"


# --- name in the target language (the only model use) ---

def render_name(label: str, book: str, lang: str, lang_cfg: dict, verse_lines: list,
                call, model: str, cache_dir):
    """Name of the speaker in the target language (see localize.localize), or None if no valid name."""
    return localize.localize(
        "speaker-name", label, "name of a biblical speaker", lang, lang_cfg, verse_lines, call, model, cache_dir,
        NAME_PROMPT_VERSION,
        extra=f"A label such as narrator-XXX means 'the narrator' of the book {book}: answer with the usual word for it.",
    )


# --- the schema-2 field ---

def build_speaker(ident: dict, name, lang_cfg: dict, registry: dict) -> dict:
    """{'speaker': field, 'sources': records, 'flags': [...], 'candidates': [...]} for the entry.

    `name` is the localized name (None if the model gave none: the dataset label is kept and flagged).
    """
    flags = list(ident["flags"])
    if ident["label"] is None:
        return {"speaker": {"value": None, "reason": "not_identified"}, "sources": [],
                "flags": flags, "candidates": ident["candidates"]}
    if name is None:
        name = ident["label"]
        flags.append("name_not_localized")
    covered_verses = [ds.key_to_id(k) for k in _covered_keys(ident)]
    records = [dataset_source(f"speaker-quotations:{ds.key_to_id(s)}-{ds.key_to_id(e)}",
                              "speaker-quotations", "speaker_data", registry) for s, e in ident["records"]]
    people = [dataset_source(f"acai:{p['id']}", "acai", "entity_data", registry) for p in ident["agreement"]]
    verses = [verse_source(v, lang_cfg["dataset"], registry) for v in covered_verses]
    sources = merge_sources(verses, records, people)
    return {"speaker": {"value": name, "role": ident["role"], "confidence": rate(ident),
                        "sources": [s["id"] for s in sources]},
            "sources": sources, "flags": flags, "candidates": ident["candidates"]}


def _covered_keys(ident: dict) -> list:
    """Verse keys of the excerpt inside a quotation range of the speaker."""
    keys = []
    for s, e in ident["records"]:
        for k in ident.get("keys", []):
            if s <= k <= e and k not in keys:
                keys.append(k)
    return keys
