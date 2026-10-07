"""Dates of the context: one `temporal` entry per source, confidence computed by the code.

Rules (specification, "Contexte, dates et lieux"):
- a dataset keeps only its year; the year becomes a range with a margin read from
  data/date_rules.yml, never from the code;
- each source gives its own entry, never an average or a merge;
- the level (certain, probable, approximate, disputed) comes from the width of the range
  and from the agreement of the sources. A model never decides it.

Years are astronomical integers inside the module (0 = 1 BCE). The schema wants CE/BCE
years with from <= to as numbers (validate.py); for BCE that makes `from` the later bound.
"""
from __future__ import annotations

from pathlib import Path

import yaml

import datasets as ds
import day_candidates
from provenance import dataset_source, merge_sources

RULES_PATH = Path(__file__).parent / "data" / "date_rules.yml"
LEVELS = ("certain", "probable", "approximate", "disputed")


class RulesError(ValueError):
    pass


def load_rules(path=RULES_PATH) -> dict:
    """Read and check data/date_rules.yml."""
    rules = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    margins, spans = rules.get("margin_years"), rules.get("max_span")
    if not isinstance(margins, dict) or not all(isinstance(v, int) and not isinstance(v, bool) and v >= 0
                                                for v in margins.values()):
        raise RulesError("margin_years: a dict of non-negative integers is required")
    if not isinstance(spans, dict) or not all(isinstance(spans.get(k), int) for k in ("certain", "probable", "approximate")):
        raise RulesError("max_span: certain, probable and approximate are required")
    if not spans["certain"] <= spans["probable"] <= spans["approximate"]:
        raise RulesError("max_span: must grow from certain to approximate")
    if not isinstance(rules.get("certain_min_sources"), int) or rules["certain_min_sources"] < 2:
        raise RulesError("certain_min_sources: an integer of at least 2 is required")
    return rules


# --- years ---

def year_range(year: int, margin: int) -> tuple:
    """A dataset year (astronomical) and a margin -> (low, high)."""
    return (year - margin, year + margin)


def to_schema(low: int, high: int):
    """Astronomical range -> {'from', 'to', 'era'} with positive years and from <= to, or None.

    None when the range crosses the BCE/CE boundary: the schema has one era per range.
    """
    if low >= 1:
        return {"from": low, "to": high, "era": "CE"}
    if high <= 0:
        return {"from": 1 - high, "to": 1 - low, "era": "BCE"}
    return None


def from_schema(rng: dict) -> tuple:
    """{'from', 'to', 'era'} (an anchor's date_range) -> astronomical (low, high)."""
    if rng["era"] == "CE":
        return (rng["from"], rng["to"])
    return (1 - rng["to"], 1 - rng["from"])


def overlaps(a: tuple, b: tuple) -> bool:
    return a[0] <= b[1] and b[0] <= a[1]


# --- confidence (code only) ---

def rate(est: dict, group: list, rules: dict) -> str:
    """Level of one estimate, given every estimate of the same event (itself included).

    disputed     a source flags a debate, two ranges do not overlap, or the span exceeds the last limit
    certain      span within the first limit, and anchored by data/anchors.yml or confirmed by
                 `certain_min_sources` different datasets
    probable     span within the second limit
    approximate  span within the third limit
    """
    spans = rules["max_span"]
    others = [g for g in group if g is not est]
    low, high = est["range"]
    if any(g["debate"] for g in group) or any(not overlaps(est["range"], g["range"]) for g in others):
        return "disputed"
    if high - low > spans["approximate"]:
        return "disputed"
    anchored = any(g["anchored"] for g in group)
    if high - low <= spans["certain"] and (anchored or len({g["source"] for g in group}) >= rules["certain_min_sources"]):
        return "certain"
    if high - low <= spans["probable"]:
        return "probable"
    return "approximate"


# --- estimates ---

def estimates(verse_ids: list, theographic: dict, anchors: list, rules: dict) -> list:
    """Date estimates for the verses of an excerpt: Theographic events (year only) and the anchors
    that carry a numeric range and name the event in `applies_to`.

    An anchor without `date_range` or without `applies_to` is ignored here: it dates nothing.
    """
    events = {}
    for vid in verse_ids:
        for e in theographic["events"].get(ds.verse_key(vid), []):
            events.setdefault(e["id"], e)
    out = []
    for eid, e in sorted(events.items(), key=lambda kv: (kv[1]["title"] or "", kv[0])):
        out.append({"event": eid, "source": "theographic", "record": f"theographic:event:{eid}",
                    "label": e["title"], "range": year_range(e["year"], rules["margin_years"]["theographic"]),
                    "anchored": False, "debate": False})
        for a in anchors:
            if a.get("date_range") and eid in [str(x) for x in a.get("applies_to") or []]:
                out.append({"event": eid, "source": "anchors", "record": f"anchors:{a['id']}",
                            "label": e["title"], "range": from_schema(a["date_range"]),
                            "anchored": True, "debate": False})
    return out


def build_temporal(verse_ids: list, theographic: dict, anchors: list, rules: dict, registry: dict,
                   localize_label=lambda label: None, day_rules=None, lang: str = "en") -> dict:
    """{'temporal': [...], 'sources': [...], 'flags': [...]} for an entry.

    `localize_label(label)` returns the event label in the target language, or None
    (the dataset label is then kept and the entry is flagged `label_not_localized`).
    `day_rules` (data/calendar_rules.yml, see day_candidates.py): when given, a Theographic event it
    lists (the Passion, Pentecost) also carries `day_candidates`; with several different dates the
    level is `disputed`, because no candidate is a fact.
    """
    ests = estimates(verse_ids, theographic, anchors, rules)
    flags, items, records, kinds = [], [], [], set()
    by_event = {}
    for e in ests:
        by_event.setdefault(e["event"], []).append(e)
    for group in by_event.values():
        for e in group:
            rng = to_schema(*e["range"])
            if rng is None:
                flags.append(f"date_era_straddle:{e['record']}")
                continue
            label = localize_label(e["label"])
            if label is None:
                label = e["label"]
                flags.append(f"label_not_localized:{e['record']}")
            item = {"kind": "scholarly_estimate", "label": label, "date_range": rng,
                    "confidence": rate(e, group, rules), "sources": [e["record"]], "event": e["event"]}
            cand = day_candidates.candidates_for_event(e["event"], day_rules, lang) \
                if day_rules is not None and e["source"] == "theographic" else None
            if cand and cand["candidates"]:
                item["day_candidates"] = cand["candidates"]
                kinds.add(cand["kind"])
                if len({c["date"] for c in cand["candidates"]}) > 1:
                    item["confidence"] = "disputed"
                if cand["text_fallback"]:
                    flags.append(f"assumptions_in_english:{e['record']}")
            items.append(item)
            records.append(dataset_source(e["record"], e["source"],
                                          "anchor" if e["anchored"] else "event_data", registry))
    if kinds:
        records += day_candidates.source_records(kinds, registry)
    return {"temporal": items, "sources": merge_sources(records), "flags": flags}
