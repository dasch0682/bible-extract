"""Tests for calendar_calc.py, day_candidates.py and their use in dating.py (task 6, day candidates)."""
import copy
from pathlib import Path

import pytest
import yaml

import calendar_calc as cc
import datasets as ds
import dating
import day_candidates as dc
import provenance as pv
import validate

ROOT = Path(__file__).resolve().parent.parent
RULES = dc.load_rules()
DATE_RULES = dating.load_rules()
REG = pv.load_registry()


# --- Julian day and calendar ---

def test_julian_day_zero_and_j2000():
    assert cc.jd_from_julian_date(-4712, 1, 1.5) == 0.0                   # Meeus: JD 0 is 1 Jan -4712 at noon
    assert cc.jd_from_julian_date(1999, 12, 19.5) == 2451545.0            # J2000.0 = 1 Jan 2000 Gregorian
    assert cc.julian_date_from_jd(2451545.0) == (1999, 12, 19.5)
    assert cc.julian_date_from_jd(0.0) == (-4712, 1, 1.5)


@pytest.mark.parametrize("y,m,d", [(30, 4, 7), (33, 4, 3), (1, 1, 1), (-3, 12, 31), (0, 3, 1), (1500, 2, 29)])
def test_day_number_round_trip(y, m, d):
    assert cc.date_from_day_number(cc.civil_day_number(y, m, d)) == (y, m, d)


def test_weekday_of_known_dates():
    assert cc.weekday(cc.civil_day_number(30, 4, 7)) == "Friday"          # the specification's first candidate
    assert cc.weekday(cc.civil_day_number(33, 4, 3)) == "Friday"          # the specification's second candidate
    assert cc.weekday(cc.civil_day_number(2000, 1, 1)) == "Friday"        # Julian 1 Jan 2000 = Gregorian 14 Jan, a Friday
    n = cc.civil_day_number(30, 4, 7)
    assert [cc.weekday(n + i) for i in (1, 2)] == ["Saturday", "Sunday"]


def test_iso_date_format_matches_validate():
    assert cc.iso_date(cc.civil_day_number(30, 4, 7)) == "0030-04-07"
    assert cc.iso_date(cc.civil_day_number(-3, 12, 31)) == "-0003-12-31"
    assert validate._ISO_DATE.match(cc.iso_date(cc.civil_day_number(33, 4, 3)))


def test_delta_t_polynomial_and_range():
    assert cc.delta_t_seconds(0) == pytest.approx(10583.6)
    assert 9000 < cc.delta_t_seconds(30) < 11000
    with pytest.raises(ValueError):
        cc.delta_t_seconds(900)


# --- new moon ---

def test_meeus_worked_example_49a():
    # Astronomical Algorithms, example 49.a: new moon of February 1977, k = -283, JDE 2443192.65118
    assert cc.new_moon_jde(-283) == pytest.approx(2443192.65118, abs=2e-5)


def test_new_moon_of_6_january_2000_is_about_18_14_ut():
    ut = cc.new_moon_jde(0) - 64 / 86400           # Delta T of about 64 s in 2000
    noon = 2451545.0 + 5                           # J2000.0 is 1 Jan 2000 at 12:00 UT, so this is 6 Jan at 12:00
    assert (ut - noon) * 24 == pytest.approx(6 + 14 / 60, abs=0.1)          # 18:14 UT, within 6 minutes


def test_new_moons_are_about_29_5_days_apart_in_the_first_century():
    moons = cc.new_moons_between(cc.jd_from_julian_date(30, 1, 1), cc.jd_from_julian_date(31, 1, 1))
    assert len(moons) in (12, 13)
    gaps = [b[1] - a[1] for a, b in zip(moons, moons[1:])]
    assert all(29.2 < g < 29.9 for g in gaps)


def test_first_visible_evening_depends_on_the_age_rule():
    conj = cc.jd_from_julian_date(30, 3, 24.0) + 0.3          # a conjunction on 24 March, 07:12 UT
    young = cc.first_visible_evening(conj, 35.2, 6)
    old = cc.first_visible_evening(conj, 35.2, 40)
    assert old > young
    sunset = cc.sunset_jd_ut(old, 35.2)
    assert (sunset - conj) * 24 >= 40 > (cc.sunset_jd_ut(old - 1, 35.2) - conj) * 24


# --- rules file ---

def test_real_rules_load_and_texts_are_complete():
    for lang in ("en", "fr"):
        assert set(RULES["texts"][lang]) == {"calendar", "sunset", "crescent", "equinox", "death_14", "death_15",
                                             "pharisaic", "sunday"}


@pytest.mark.parametrize("mutate", [
    lambda r: r.pop("equinox_julian"),
    lambda r: r.update(crescent_min_age_hours=[]),
    lambda r: r["passion"].update(day_of_nisan=[13]),
    lambda r: r["pentecost"].update(readings=["other"]),
    lambda r: r["events"].update({"1": {"kind": "birth"}}),
    lambda r: r["texts"].pop("en"),
])
def test_bad_calendar_rules_are_refused(tmp_path, mutate):
    rules = yaml.safe_load((ROOT / "data" / "calendar_rules.yml").read_text(encoding="utf-8"))
    mutate(rules)
    p = tmp_path / "r.yml"
    p.write_text(yaml.safe_dump(rules, allow_unicode=True), encoding="utf-8")
    with pytest.raises(dc.RulesError):
        dc.load_rules(p)


# --- Nisan and the Passion ---

def test_nisan_14_is_never_before_the_equinox_date():
    for year in range(26, 37):
        m = dc.nisan(year, 24, RULES)
        assert m["nisan14"] >= cc.civil_day_number(year, 3, 21)
        assert m["nisan1"] == m["evening"] + 1 and m["nisan15"] == m["nisan14"] + 1


def test_the_two_starting_candidates_of_the_specification_are_found():
    dates = [c["date"] for c in dc.passion_candidates(RULES)["candidates"]]
    assert dates == ["0030-04-07", "0033-04-03"]


def test_candidates_are_fridays_and_carry_method_assumptions_and_sources():
    for c in dc.passion_candidates(RULES)["candidates"]:
        y, m, d = (int(x) for x in c["date"].split("-"))
        assert cc.weekday(cc.civil_day_number(y, m, d)) == "Friday"
        assert c["method"] == "calendar_computation"
        assert len(c["assumptions"]) >= 5 and c["sources"] == ["meeus:chapter-49", "calendar-rules:passion"]


def test_derivations_keep_which_assumptions_gave_which_date():
    c30 = dc.passion_candidates(RULES)["candidates"][0]
    deaths = [a for d in c30["derivations"] for a in d if "Nisan" in a and "died" in a]
    assert any("14th" in a for a in deaths) and any("15th" in a for a in deaths)    # John and the Synoptics both give 7 April 30
    assert set(sum(c30["derivations"], [])) == set(c30["assumptions"])


def test_years_set_aside_are_not_computed():
    rules = copy.deepcopy(RULES)
    assert set(rules["passion"]["set_aside"]) == {27, 34}
    assert not {27, 34} & set(rules["passion"]["years"])
    # 27 would give a Friday under the rules (it is set aside by an argument outside the calendar)
    friday27 = [d for d in (14, 15) for age in rules["crescent_min_age_hours"]
                if cc.weekday(dc.nisan(27, age, rules)[f"nisan{d}"]) == "Friday"]
    assert friday27 and not any(c["date"].startswith("0027") for c in dc.passion_candidates(rules)["candidates"])


def test_changing_the_rules_changes_the_candidates():
    rules = copy.deepcopy(RULES)
    rules["passion"]["years"] = [30]
    assert [c["date"] for c in dc.passion_candidates(rules)["candidates"]] == ["0030-04-07"]
    rules["passion"]["day_of_nisan"] = [15]
    rules["crescent_min_age_hours"] = [24]
    assert dc.passion_candidates(rules)["candidates"] == []        # 15 Nisan is a Saturday that year


# --- Pentecost ---

def test_pentecost_readings():
    n15 = cc.civil_day_number(33, 4, 4)                            # a Saturday
    assert cc.weekday(n15) == "Saturday"
    assert cc.iso_date(dc.pentecost_day(n15, "pharisaic")) == "0033-05-24"
    assert cc.iso_date(dc.pentecost_day(n15, "sunday")) == "0033-05-24"      # Sunday 5 April + 49 days
    n15 = cc.civil_day_number(30, 4, 7)                            # a Friday
    assert cc.iso_date(dc.pentecost_day(n15, "pharisaic")) == "0030-05-27"
    sunday = dc.pentecost_day(n15, "sunday")
    assert cc.weekday(sunday) == "Sunday" and cc.iso_date(sunday) == "0030-05-28"


def test_pentecost_candidates_come_from_the_kept_passion_years():
    out = dc.pentecost_candidates(RULES)
    assert [c["date"] for c in out["candidates"]] == ["0030-05-27", "0030-05-28", "0033-05-24"]
    assert all(c["sources"] == ["meeus:chapter-49", "calendar-rules:pentecost"] for c in out["candidates"])


# --- texts and events ---

def test_french_texts_are_used_and_a_missing_language_falls_back_to_english():
    fr = dc.passion_candidates(RULES, "fr")
    assert fr["text_fallback"] is False and "calendrier julien" in fr["candidates"][0]["assumptions"][0]
    de = dc.passion_candidates(RULES, "de")
    assert de["text_fallback"] is True and "Julian calendar" in de["candidates"][0]["assumptions"][0]
    assert [c["date"] for c in fr["candidates"]] == [c["date"] for c in de["candidates"]]   # the dates never depend on the language


def test_only_configured_events_get_candidates():
    assert dc.candidates_for_event("459", RULES)["kind"] == "passion"
    assert dc.candidates_for_event("307", RULES)["kind"] == "pentecost"
    assert dc.candidates_for_event("254", RULES) is None


def test_source_records_are_registered():
    recs = dc.source_records({"passion", "pentecost"}, REG)
    assert [r["id"] for r in recs] == ["meeus:chapter-49", "calendar-rules:passion", "calendar-rules:pentecost"]
    assert all(r["dataset"] in pv.known_datasets(REG) and r["license"] for r in recs)


# --- in the temporal entries ---

def event(eid, title, year):
    return {"id": eid, "title": title, "year": year, "precision": "day", "places": []}


def test_passion_event_carries_candidates_and_is_disputed():
    theo = {"events": {ds.verse_key("JHN.19.14"): [event("459", "Crucifixion and Burial", 30)]}, "places": {}}
    out = dating.build_temporal(["JHN.19.14"], theo, [], DATE_RULES, REG, localize_label=lambda s: s,
                                day_rules=RULES, lang="fr")
    (item,) = out["temporal"]
    assert [c["date"] for c in item["day_candidates"]] == ["0030-04-07", "0033-04-03"]
    assert item["confidence"] == "disputed"                          # two different days: no candidate is a fact
    assert item["date_range"] == {"from": 28, "to": 32, "era": "CE"}
    assert validate._check_temporal_item(0, item) == []
    ids = {s["id"] for s in out["sources"]}
    assert {"theographic:event:459", "meeus:chapter-49", "calendar-rules:passion"} <= ids
    assert out["flags"] == []


def test_a_single_candidate_date_keeps_the_computed_level():
    rules = copy.deepcopy(RULES)
    rules["passion"]["years"] = [30]
    theo = {"events": {ds.verse_key("JHN.19.14"): [event("459", "Crucifixion and Burial", 30)]}, "places": {}}
    out = dating.build_temporal(["JHN.19.14"], theo, [], DATE_RULES, REG, localize_label=lambda s: s, day_rules=rules)
    assert out["temporal"][0]["confidence"] == "probable" and len(out["temporal"][0]["day_candidates"]) == 1


def test_event_outside_the_list_has_no_candidates_and_no_calendar_sources():
    theo = {"events": {ds.verse_key("MAT.2.1"): [event("254", "Birth of Jesus", -3)]}, "places": {}}
    out = dating.build_temporal(["MAT.2.1"], theo, [], DATE_RULES, REG, localize_label=lambda s: s, day_rules=RULES)
    assert "day_candidates" not in out["temporal"][0]
    assert not any(s["id"].startswith(("meeus", "calendar-rules")) for s in out["sources"])


def test_without_day_rules_nothing_is_added():
    theo = {"events": {ds.verse_key("JHN.19.14"): [event("459", "Crucifixion and Burial", 30)]}, "places": {}}
    out = dating.build_temporal(["JHN.19.14"], theo, [], DATE_RULES, REG, localize_label=lambda s: s)
    assert "day_candidates" not in out["temporal"][0]


def test_fallback_texts_are_flagged_in_the_temporal_entry():
    theo = {"events": {ds.verse_key("ACT.2.1"): [event("307", "The Holy Spirit comes", 30)]}, "places": {}}
    out = dating.build_temporal(["ACT.2.1"], theo, [], DATE_RULES, REG, localize_label=lambda s: s,
                                day_rules=RULES, lang="de")
    assert out["flags"] == ["assumptions_in_english:theographic:event:307"]


# --- smoke test on the real data ---

real = pytest.mark.skipif(not (ROOT / "tmp" / "theographic").exists(), reason="tmp/ datasets not fetched")


@real
def test_real_acts_2_1_has_pentecost_candidates():
    out = dating.build_temporal(["ACT.2.1"], ds.load_theographic(), [], DATE_RULES, REG,
                                localize_label=lambda s: s, day_rules=RULES)
    (item,) = out["temporal"]
    assert [c["date"] for c in item["day_candidates"]] == ["0030-05-27", "0030-05-28", "0033-05-24"]
    assert item["confidence"] == "disputed" and validate._check_temporal_item(0, item) == []
