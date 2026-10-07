"""Day-level date candidates for the Passion and Pentecost (never a single fact).

Each candidate carries its date, the method (calendar_computation), the assumptions it
relies on and its sources. The day is recomputed at every batch from data/calendar_rules.yml,
never copied from a dataset. The level of confidence stays `disputed` while candidates differ
(see dating.py); only a human can designate one in the review page.
"""
from __future__ import annotations

from pathlib import Path

import yaml

import calendar_calc as cc
from provenance import dataset_source, merge_sources

RULES_PATH = Path(__file__).parent / "data" / "calendar_rules.yml"
METHOD = "calendar_computation"
SOURCE_ALGORITHM = "meeus:chapter-49"
SOURCE_RULES = "calendar-rules:{kind}"


class RulesError(ValueError):
    pass


def load_rules(path=RULES_PATH) -> dict:
    r = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    for key in ("place", "sunset_local_hour", "crescent_min_age_hours", "equinox_julian", "events", "passion",
                "pentecost", "texts"):
        if key not in r:
            raise RulesError(f"{key}: missing")
    if not isinstance(r["crescent_min_age_hours"], list) or not r["crescent_min_age_hours"]:
        raise RulesError("crescent_min_age_hours: a non-empty list is required")
    if not all(d in (14, 15) for d in r["passion"]["day_of_nisan"]):
        raise RulesError("passion.day_of_nisan: only 14 and 15 are supported")
    if not set(r["pentecost"]["readings"]) <= {"pharisaic", "sunday"}:
        raise RulesError("pentecost.readings: pharisaic or sunday")
    if any(k["kind"] not in ("passion", "pentecost") for k in r["events"].values()):
        raise RulesError("events: kind must be passion or pentecost")
    if "en" not in r["texts"]:
        raise RulesError("texts.en: the English texts are the fallback and are required")
    return r


# --- computation ---

def nisan(year: int, min_age_hours: float, rules: dict):
    """Civil day numbers of Nisan in a Julian year under the rules, or None if no month qualifies.

    {'evening', 'nisan1', 'nisan14', 'nisan15'}: `evening` is the first visible evening (the month starts
    then), `nisan1` the first daylight of the month. 14 and 15 Nisan are the daylight civil days.
    """
    lon = rules["place"]["longitude_east_deg"]
    start = cc.jd_from_julian_date(year, 2, 1)
    end = cc.jd_from_julian_date(year, 5, 15)
    eq = rules["equinox_julian"]
    equinox_day = cc.civil_day_number(year, eq["month"], eq["day"])
    for _k, conj in cc.new_moons_between(start, end):
        evening = cc.first_visible_evening(conj, lon, min_age_hours, rules["sunset_local_hour"])
        if evening + 14 >= equinox_day:
            return {"evening": evening, "nisan1": evening + 1, "nisan14": evening + 14, "nisan15": evening + 15}
    return None


def pentecost_day(nisan15: int, reading: str) -> int:
    """Civil day number of Pentecost for a reading of Leviticus 23:15-16."""
    if reading == "pharisaic":
        return nisan15 + 50
    # sunday: the first Saturday on or after 15 Nisan, the Sunday after it is day 1, Pentecost is day 50
    n = nisan15
    while cc.weekday(n) != "Saturday":
        n += 1
    return (n + 1) + 49


# --- candidates ---

def _texts(rules: dict, lang: str) -> tuple:
    texts = rules["texts"].get(lang)
    return (texts, False) if texts else (rules["texts"]["en"], True)


def _base_assumptions(rules: dict, texts: dict, age: float) -> list:
    return [
        texts["calendar"],
        texts["sunset"].format(hour=int(rules["sunset_local_hour"]), place=rules["place"]["name"],
                               longitude=rules["place"]["longitude_east_deg"]),
        texts["crescent"].format(hours=age),
        texts["equinox"],
    ]


def _group(derivations: list, kind: str) -> list:
    """One candidate per distinct date. `assumptions` is the ordered union; `derivations` keeps the pairing."""
    by_date, order = {}, []
    for date, assumptions in derivations:
        if date not in by_date:
            by_date[date] = []
            order.append(date)
        by_date[date].append(assumptions)
    out = []
    for date in sorted(order):
        union = []
        for a in by_date[date]:
            union += [x for x in a if x not in union]
        out.append({"date": date, "method": METHOD, "assumptions": union, "derivations": by_date[date],
                    "sources": [SOURCE_ALGORITHM, SOURCE_RULES.format(kind=kind)]})
    return out


def passion_candidates(rules: dict, lang: str = "en") -> dict:
    """Fridays that are 14 or 15 Nisan in the kept years, under every crescent variant."""
    texts, fallback = _texts(rules, lang)
    derivations = []
    for year in rules["passion"]["years"]:
        for age in rules["crescent_min_age_hours"]:
            month = nisan(year, age, rules)
            if month is None:
                continue
            for d in rules["passion"]["day_of_nisan"]:
                n = month[f"nisan{d}"]
                if cc.weekday(n) == "Friday":
                    derivations.append((cc.iso_date(n), _base_assumptions(rules, texts, age) + [texts[f"death_{d}"]]))
    return {"candidates": _group(derivations, "passion"), "text_fallback": fallback}


def pentecost_candidates(rules: dict, lang: str = "en") -> dict:
    """Pentecost for every kept Passion year and crescent variant, under each reading of Leviticus."""
    texts, fallback = _texts(rules, lang)
    derivations = []
    for year in rules["passion"]["years"]:
        for age in rules["crescent_min_age_hours"]:
            month = nisan(year, age, rules)
            if month is None:
                continue
            for reading in rules["pentecost"]["readings"]:
                n = pentecost_day(month["nisan15"], reading)
                derivations.append((cc.iso_date(n), _base_assumptions(rules, texts, age) + [texts[reading]]))
    return {"candidates": _group(derivations, "pentecost"), "text_fallback": fallback}


def candidates_for_event(event_id: str, rules: dict, lang: str = "en"):
    """{'candidates', 'text_fallback', 'kind'} for a configured event id, or None for any other event."""
    spec = rules["events"].get(str(event_id))
    if spec is None:
        return None
    build = passion_candidates if spec["kind"] == "passion" else pentecost_candidates
    return dict(build(rules, lang), kind=spec["kind"])


def source_records(kinds: set, registry: dict) -> list:
    """Source records for the candidates' `sources` ids."""
    recs = [dataset_source(SOURCE_ALGORITHM, "meeus-astronomical-algorithms", "algorithm", registry)]
    recs += [dataset_source(SOURCE_RULES.format(kind=k), "calendar-rules", "rules", registry) for k in sorted(kinds)]
    return merge_sources(recs)
