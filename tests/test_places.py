"""Tests for places.py and data/place_rules.yml (task 6, places)."""
from pathlib import Path

import pytest
import yaml

import datasets as ds
import places
import provenance as pv
import validate

ROOT = Path(__file__).resolve().parent.parent
RULES = places.load_rules()
REG = pv.load_registry()


def place(pid, name, total, special=None, wikidata=None):
    return {"id": pid, "name": name, "wikidata": wikidata, "score": total, "identifications": 1,
            "total": total, "count": 1, "special": special}


def ob(vid, *items):
    return {ds.verse_key(vid): list(items)}


# --- rules ---

def test_real_rules_load():
    assert RULES["vote_total"] == {"probable": 500, "approximate": 1}
    assert RULES["special"]["not_a_place"] == "exclude"


@pytest.mark.parametrize("patch", [
    {"vote_total": {"probable": 100, "approximate": 200}},
    {"vote_total": {"probable": 500}},
    {"no_score": "maybe"},
    {"special": {"not_a_place": "exclude"}},
    {"special": {k: "wrong" for k in places.SPECIAL_VALUES}},
])
def test_bad_rules_are_refused(tmp_path, patch):
    rules = dict(yaml.safe_load((ROOT / "data" / "place_rules.yml").read_text(encoding="utf-8")), **patch)
    p = tmp_path / "r.yml"
    p.write_text(yaml.safe_dump(rules), encoding="utf-8")
    with pytest.raises(places.RulesError):
        places.load_rules(p)


# --- levels ---

@pytest.mark.parametrize("total,level", [(500, "probable"), (900, "probable"), (499, "approximate"), (1, "approximate"),
                                         (0, "disputed"), (-10, "disputed"), (None, "disputed")])
def test_level_comes_from_the_vote_total(total, level):
    assert places.rate(place("a", "X", total), RULES) == level


def test_a_place_alone_in_one_dataset_is_never_certain():
    assert places.rate(place("a", "X", 10 ** 6), RULES) == "probable"


def test_special_resolutions():
    assert places.rate(place("a", "X", 500, special="not_a_place"), RULES) is None
    assert places.rate(place("a", "X", 500, special="nonspecific_place"), RULES) == "disputed"
    assert places.rate(place("a", "X", 500, special="multiple_locations"), RULES) == "disputed"
    assert places.rate(place("a", "X", 500, special="not_a_proper_name"), RULES) is None
    assert places.rate(place("a", "X", 500, special="unknown_place"), RULES) == "disputed"
    with pytest.raises(places.RulesError):
        places.rate(place("a", "X", 500, special="something_new"), RULES)


def test_display_name_drops_the_homonym_number_only():
    assert places.display_name("Ephraim 2") == "Ephraim"
    assert places.display_name("Bethany") == "Bethany"
    assert places.display_name("Kir 1") == "Kir"
    assert places.display_name("Aram-naharaim") == "Aram-naharaim"


# --- build_places ---

def test_place_entry_has_the_schema_fields_and_passes_validate():
    data = ob("2CO.11.10", place("aef4242", "Achaia", 500, wikidata="Q192787"))
    out = places.build_places(["2CO.11.10"], data, RULES, REG, localize_name=lambda n: "Achaïe")
    assert out["places"] == [{"name": "Achaïe", "place_id": "aef4242", "confidence": "probable",
                              "sources": ["openbible:aef4242"], "wikidata": "Q192787"}]
    assert out["sources"] == [{"id": "openbible:aef4242", "type": "place_data", "dataset": "openbible",
                               "license": REG["openbible"]["license"]}]
    assert out["flags"] == []
    assert validate.check_context({"literary": {"text": None, "reason": "no_source"}, "temporal": [],
                                   "places": out["places"]}) == []


def test_no_geometry_or_coordinates_are_ever_carried():
    data = ob("2CO.11.10", place("aef4242", "Achaia", 500))
    (item,) = places.build_places(["2CO.11.10"], data, RULES, REG)["places"]
    assert not {"lonlat", "geometry", "latitude", "longitude", "coordinates"} & set(item)


def test_unlocalized_name_is_kept_and_flagged():
    out = places.build_places(["2CO.11.10"], ob("2CO.11.10", place("a1", "Ephraim 2", 10)), RULES, REG)
    assert out["places"][0]["name"] == "Ephraim" and out["flags"] == ["place_name_not_localized:a1"]


def test_places_are_deduplicated_sorted_and_not_a_place_is_left_out():
    data = {**ob("ACT.18.12", place("b2", "Corinth", 500), place("a1", "Achaia", 500), place("z9", "Paul?", 500, "not_a_place")),
            **ob("ACT.18.27", place("a1", "Achaia", 500))}
    out = places.build_places(["ACT.18.12", "ACT.18.27"], data, RULES, REG, localize_name=lambda n: n)
    assert [p["place_id"] for p in out["places"]] == ["a1", "b2"]
    assert [s["id"] for s in out["sources"]] == ["openbible:a1", "openbible:b2"]


def test_no_place_gives_an_empty_list():
    assert places.build_places(["ROM.3.7"], {}, RULES, REG) == {"places": [], "sources": [], "flags": []}


# --- smoke test on the real data ---

real = pytest.mark.skipif(not (ROOT / "tmp" / "openbible-geocoding").exists(), reason="tmp/ datasets not fetched")


@real
def test_real_achaia_in_2_corinthians_11_10_is_probable():
    out = places.build_places(["2CO.11.10"], ds.load_openbible(), RULES, REG, localize_name=lambda n: n)
    achaia = [p for p in out["places"] if p["name"] == "Achaia"]
    assert achaia and achaia[0]["confidence"] == "probable" and achaia[0]["place_id"] == "aef4242"
    assert validate.check_context({"literary": {"text": None, "reason": "no_source"}, "temporal": [],
                                   "places": out["places"]}) == []


@real
def test_real_data_never_returns_an_unknown_special_value():
    seen = {p["special"] for items in ds.load_openbible().values() for p in items}
    assert seen <= places.SPECIAL_VALUES | {None}
    assert all(places.rate(p, RULES) in places.LEVELS | {None}
               for items in ds.load_openbible().values() for p in items)
