"""Tests for dating.py and data/date_rules.yml (task 6, dates)."""
from pathlib import Path

import pytest
import yaml

import datasets as ds
import dating
import provenance as pv
import validate

ROOT = Path(__file__).resolve().parent.parent
RULES = dating.load_rules()
REG = pv.load_registry()


def event(eid, title, year):
    return {"id": eid, "title": title, "year": year, "precision": "year", "places": []}


def th(vid, *events):
    return {"events": {ds.verse_key(vid): list(events)}, "places": {}}


# --- rules file ---

def test_real_rules_file_loads():
    assert RULES["margin_years"]["theographic"] == 2
    assert RULES["max_span"] == {"certain": 2, "probable": 10, "approximate": 25}


@pytest.mark.parametrize("patch", [
    {"margin_years": {"theographic": -1}},
    {"margin_years": "x"},
    {"max_span": {"certain": 5, "probable": 3, "approximate": 25}},
    {"max_span": {"certain": 2, "probable": 10}},
    {"certain_min_sources": 1},
])
def test_bad_rules_are_refused(tmp_path, patch):
    rules = dict(yaml.safe_load((ROOT / "data" / "date_rules.yml").read_text(encoding="utf-8")), **patch)
    p = tmp_path / "r.yml"
    p.write_text(yaml.safe_dump(rules), encoding="utf-8")
    with pytest.raises(dating.RulesError):
        dating.load_rules(p)


# --- years ---

def test_year_range_and_schema_ce():
    assert dating.year_range(30, 2) == (28, 32)
    assert dating.to_schema(28, 32) == {"from": 28, "to": 32, "era": "CE"}


def test_astronomical_years_become_bce_with_the_dataset_convention():
    # Theographic: -3 is 4 BCE; with a margin of 2 the range is 5..1 -> 6 BCE to 2 BCE
    low, high = dating.year_range(-3, 2)
    assert dating.to_schema(low, high) == {"from": 2, "to": 6, "era": "BCE"}
    assert dating.to_schema(0, 0) == {"from": 1, "to": 1, "era": "BCE"}     # year 0 is 1 BCE
    assert dating.to_schema(1, 1) == {"from": 1, "to": 1, "era": "CE"}


def test_range_crossing_the_era_boundary_is_not_representable():
    assert dating.to_schema(-1, 2) is None


def test_schema_round_trip():
    for rng in ({"from": 28, "to": 32, "era": "CE"}, {"from": 2, "to": 6, "era": "BCE"}):
        assert dating.to_schema(*dating.from_schema(rng)) == rng


# --- levels ---

def est(source, low, high, anchored=False, debate=False):
    return {"event": "e", "source": source, "record": f"{source}:x", "label": "L", "range": (low, high),
            "anchored": anchored, "debate": debate}


def level(e, group):
    return dating.rate(e, group, RULES)


def test_a_lone_chronology_never_goes_above_probable():
    e = est("theographic", 30, 30)            # even a span of 0
    assert level(e, [e]) == "probable"


def test_certain_needs_anchor_or_two_datasets_and_a_narrow_span():
    a, b = est("theographic", 30, 31), est("anchors", 30, 32, anchored=True)
    assert level(a, [a, b]) == "certain"
    c, d = est("theographic", 30, 31), est("other", 30, 32)
    assert level(c, [c, d]) == "certain"
    wide = est("theographic", 28, 32)         # span 4: too wide for certain even when anchored
    assert level(wide, [wide, est("anchors", 28, 32, anchored=True)]) == "probable"


def test_span_thresholds():
    e = est("t", 0, 10)
    assert level(e, [e]) == "probable"                                              # span 10
    e = est("t", 0, 11)
    assert level(e, [e]) == "approximate"                                           # span 11
    e = est("t", 0, 25)
    assert level(e, [e]) == "approximate"                                           # span 25
    e = est("t", 0, 26)
    assert level(e, [e]) == "disputed"                                              # span 26


def test_sources_that_do_not_overlap_are_disputed_both_ways():
    a, b = est("theographic", 28, 32), est("anchors", 40, 42, anchored=True)
    assert level(a, [a, b]) == level(b, [a, b]) == "disputed"


def test_a_flagged_debate_makes_the_event_disputed():
    a, b = est("theographic", 30, 30), est("anchors", 30, 30, debate=True)
    assert level(a, [a, b]) == "disputed"


# --- build_temporal ---

def test_theographic_event_gives_one_probable_entry():
    out = dating.build_temporal(["ACT.2.1"], th("ACT.2.1", event("308", "Peter preaches at Pentecost", 30)),
                                [], RULES, REG, localize_label=lambda s: "Pierre prêche à la Pentecôte")
    assert out["flags"] == []
    (item,) = out["temporal"]
    assert item["label"] == "Pierre prêche à la Pentecôte"
    assert item["date_range"] == {"from": 28, "to": 32, "era": "CE"}
    assert item["confidence"] == "probable" and item["sources"] == ["theographic:event:308"]
    assert out["sources"] == [{"id": "theographic:event:308", "type": "event_data", "dataset": "theographic",
                               "license": REG["theographic"]["license"]}]


def test_same_event_on_several_verses_is_listed_once():
    e = event("459", "Crucifixion and Burial", 30)
    theo = {"events": {ds.verse_key("JHN.19.14"): [e], ds.verse_key("JHN.19.15"): [e]}, "places": {}}
    out = dating.build_temporal(["JHN.19.14", "JHN.19.15"], theo, [], RULES, REG)
    assert len(out["temporal"]) == 1


def test_unlocalized_label_is_kept_and_flagged():
    out = dating.build_temporal(["ACT.2.1"], th("ACT.2.1", event("308", "Peter preaches", 30)), [], RULES, REG)
    assert out["temporal"][0]["label"] == "Peter preaches"
    assert out["flags"] == ["label_not_localized:theographic:event:308"]


def test_numeric_anchor_naming_the_event_is_a_separate_entry_and_can_make_it_certain():
    anchor = {"id": "a1", "date_range": {"from": 30, "to": 31, "era": "CE", "basis": "x"}, "applies_to": ["459"]}
    theo = th("JHN.19.14", event("459", "Crucifixion and Burial", 30))
    rules = dict(RULES, margin_years={"theographic": 0})
    out = dating.build_temporal(["JHN.19.14"], theo, [anchor], rules, REG)
    by_source = {i["sources"][0]: i for i in out["temporal"]}
    assert set(by_source) == {"theographic:event:459", "anchors:a1"}          # never merged
    assert all(i["confidence"] == "certain" for i in out["temporal"])
    assert {s["type"] for s in out["sources"]} == {"event_data", "anchor"}


def test_anchor_without_numeric_range_or_applies_to_is_ignored():
    theo = th("JHN.19.14", event("459", "Crucifixion and Burial", 30))
    anchors = [{"id": "a1", "date_range": None, "reason": "r", "applies_to": ["459"]},
               {"id": "a2", "date_range": {"from": 30, "to": 31, "era": "CE", "basis": "x"}}]
    out = dating.build_temporal(["JHN.19.14"], theo, anchors, RULES, REG)
    assert [i["sources"] for i in out["temporal"]] == [["theographic:event:459"]]


def test_disagreeing_anchor_and_dataset_are_both_kept_as_disputed():
    anchor = {"id": "a1", "date_range": {"from": 36, "to": 37, "era": "CE", "basis": "x"}, "applies_to": ["459"]}
    out = dating.build_temporal(["JHN.19.14"], th("JHN.19.14", event("459", "Crucifixion", 30)), [anchor], RULES, REG)
    assert len(out["temporal"]) == 2 and {i["confidence"] for i in out["temporal"]} == {"disputed"}


def test_range_crossing_the_boundary_is_dropped_and_flagged():
    out = dating.build_temporal(["MAT.2.1"], th("MAT.2.1", event("1", "Edge case", 0)), [], RULES,
                                REG, localize_label=lambda s: s)
    assert out["temporal"] == [] and out["flags"] == ["date_era_straddle:theographic:event:1"]


def test_bce_event_passes_validate():
    out = dating.build_temporal(["MAT.2.1"], th("MAT.2.1", event("254", "Birth of Jesus", -3)), [], RULES, REG,
                                localize_label=lambda s: s)
    (item,) = out["temporal"]
    assert item["date_range"] == {"from": 2, "to": 6, "era": "BCE"}
    assert validate._check_temporal_item(0, item) == []


def test_no_event_gives_no_entry():
    out = dating.build_temporal(["ROM.3.7"], {"events": {}, "places": {}}, [], RULES, REG)
    assert out == {"temporal": [], "sources": [], "flags": []}


# --- smoke test on the real data ---

real = pytest.mark.skipif(not (ROOT / "tmp" / "theographic").exists(), reason="tmp/ datasets not fetched")


@real
def test_real_acts_2_1_is_one_probable_entry_28_to_32():
    out = dating.build_temporal(["ACT.2.1"], ds.load_theographic(), [], RULES, REG, localize_label=lambda s: s)
    (item,) = out["temporal"]
    assert item["sources"] == ["theographic:event:307"]
    assert item["date_range"] == {"from": 28, "to": 32, "era": "CE"} and item["confidence"] == "probable"
    assert validate._check_temporal_item(0, item) == []
