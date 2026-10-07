"""Tests for the discovery routes (task 8): patterns per language, Strong's numbers, union, recorded steps."""
from pathlib import Path

import pytest
import yaml

import discovery as dv
import strongs
from books import scope_codes

ROOT = Path(__file__).resolve().parent.parent

FR = {"JHN": {"8": {"32": "Et vous connaîtrez la vérité, et la vérité vous affranchira.",
                    "34": "En vérité, en vérité, je vous le dis, quiconque commet le péché est esclave du péché.",
                    "45": "En vérité je vous le dis, mais parce que je dis la vérité, vous ne me croyez pas."},
              "14": {"6": "Jésus lui dit: Je suis le chemin, la vérité, et la vie.",
                     "7": "Si vous me connaissez, vous connaîtrez aussi mon Père."}},
      "ROM": {"1": {"18": "La colère de Dieu se révèle du ciel."}}}
EN = {"JHN": {"8": {"32": "And ye shall know the truth, and the truth shall make you free.",
                    "34": "Verily, verily, I say unto you, Whosoever committeth sin is the servant of sin.",
                    "45": "And because I tell you the truth, ye believe me not."},
              "14": {"6": "Jesus saith unto him, I am the way, the truth, and the life.",
                     "7": "If ye had known me, ye should have known my Father also."}},
      "ROM": {"1": {"18": "For the wrath of God is revealed from heaven."}}}

TOPIC = {"label": "la vérité", "strongs": ["G225"],
         "patterns_fr": {"verit": r"\bverit"},
         "patterns_en": {"truth": r"\btruth"},
         "exclude_phrases_fr": {"amen_formula": r"\ben verite\b"}}


@pytest.fixture
def byztxt(tmp_path):
    d = tmp_path / "csv-unicode" / "strongs" / "with-parsing"
    d.mkdir(parents=True)
    (d / "JHN.csv").write_text("8,32,αληθειαν 225 {N-ASF}\n14,6,αληθεια 225 {N-NSF} ζωη 2222 {N-NSF}\n"
                               "8,34,αμην 281 {HEB}\n", encoding="utf-8")
    return tmp_path


def disc_of(byztxt, topic=TOPIC):
    return dv.discover(topic, {"fr": FR, "en": EN}, ["JHN", "ROM"], byztxt)


# --- rules file ---

def test_rules_file_loads_with_the_agreed_window():
    assert dv.load_rules() == {"excerpt_window": 2, "model_window": 3}


@pytest.mark.parametrize("content", ["excerpt: {window: 2}", "excerpt: {window: -1}\nmodel: {window: 3}",
                                     "excerpt: {window: true}\nmodel: {window: 3}",
                                     "excerpt: {window: 2}\nmodel: {window: 0}", "just text"])
def test_rules_file_errors(tmp_path, content):
    p = tmp_path / "r.yml"
    p.write_text(content, encoding="utf-8")
    with pytest.raises(dv.RulesError):
        dv.load_rules(p)


# --- patterns ---

def test_pattern_match_records_the_rule_and_a_corpus_word_with_its_accents():
    found = dv.find_pattern_matches(FR, ["JHN"], {"verit": r"\bverit"})
    assert found[("JHN", "8", "32")]["matches"] == [{"rule": "verit", "matched": "vérité"}]
    assert found[("JHN", "14", "6")]["lost"] is False
    assert ("JHN", "14", "7") not in found


def test_formula_only_verse_is_lost_but_a_verse_with_another_mention_is_kept():
    found = dv.find_pattern_matches(FR, ["JHN"], {"verit": r"\bverit"}, {"amen_formula": r"\ben verite\b"})
    assert found[("JHN", "8", "34")] == {"matches": [], "found": ["amen_formula"], "lost": True}
    assert found[("JHN", "8", "45")]["matches"] and found[("JHN", "8", "45")]["found"] == ["amen_formula"]


def test_wrapper_keeps_the_list_interface_of_the_old_tests():
    hits, excluded = dv.find_hits_patterns(FR, ["JHN"], [r"\bverit"], [r"\ben verite\b"])
    assert ("JHN", "8", "32") in hits and ("JHN", "8", "34") not in hits and ("JHN", "8", "34") in excluded


def test_topic_rules_reads_a_mapping_per_language():
    assert list(dv.topic_rules(TOPIC, "patterns", "fr")) == ["verit"]
    assert dv.topic_rules(TOPIC, "exclude_phrases", "en") == {}


@pytest.mark.parametrize("bad", [["a regex"], {"x": 3}, {"x": "("}, {"": "a"}])
def test_topic_rules_rejects_bad_rules(bad):
    with pytest.raises(dv.TopicError):
        dv.topic_rules({"patterns_fr": bad}, "patterns", "fr")


def test_the_real_topic_file_has_rules_for_every_language_and_no_boolean_names():
    topic = yaml.safe_load((ROOT / "topics" / "verite.yml").read_text(encoding="utf-8"))
    for lang in ("fr", "en"):
        rules = dv.topic_rules(topic, "patterns", lang)
        assert rules and all(isinstance(name, str) for name in rules)
    assert "amen_formula" in dv.topic_rules(topic, "exclude_phrases", "fr")


# --- Strong's ---

def test_strongs_matches_list_the_labels_found_in_numeric_order(byztxt):
    found = strongs.find_strongs_matches(["G2222", "g225"], ["JHN"], byztxt)
    assert found[("JHN", "14", "6")] == ["G225", "G2222"]
    assert found[("JHN", "8", "32")] == ["G225"]
    assert strongs.find_hits_strongs(["G225"], ["JHN"], byztxt) == {("JHN", "8", "32"), ("JHN", "14", "6")}


# --- union ---

def test_union_keeps_a_verse_found_by_one_route_only(byztxt):
    d = disc_of(byztxt)
    assert d["candidates"] == [("JHN", "8", "32"), ("JHN", "8", "45"), ("JHN", "14", "6")]
    assert dv.routes_of(d, ("JHN", "8", "32")) == ["strongs", "pattern:fr", "pattern:en"]
    assert dv.routes_of(d, ("JHN", "8", "45")) == ["pattern:fr", "pattern:en"]
    assert dv.single_route(d, ("JHN", "8", "45")) is True       # only the pattern family found it
    assert dv.single_route(d, ("JHN", "8", "32")) is False


def test_amen_verse_without_a_truth_word_in_greek_is_not_a_candidate(byztxt):
    assert ("JHN", "8", "34") not in disc_of(byztxt)["candidates"]


def test_a_verse_found_by_strongs_alone_stays_a_candidate_even_when_the_patterns_miss_it(byztxt):
    d = dv.discover({**TOPIC, "patterns_fr": {"x": r"\bzzz"}, "patterns_en": {"y": r"\bzzz"}},
                    {"fr": FR, "en": EN}, ["JHN"], byztxt)
    assert d["candidates"] == [("JHN", "8", "32"), ("JHN", "14", "6")]
    s = dv.summarize(d)
    assert s["only_strongs"] == d["candidates"] and s["only_patterns"] == [] and s["both"] == []


def test_without_the_greek_data_only_the_patterns_run():
    d = dv.discover(TOPIC, {"fr": FR, "en": EN}, ["JHN"], None)
    assert d["strongs"] == {} and ("JHN", "8", "32") in d["candidates"]


def test_formula_verse_found_by_strongs_is_kept_and_its_lost_pattern_is_recorded(byztxt):
    fr = {"JHN": {"4": {"25": "En vérité, je vous le dis, il y avait plusieurs veuves."}}}
    csv = byztxt / "csv-unicode" / "strongs" / "with-parsing" / "JHN.csv"
    csv.write_text("4,25,επ 1909 αληθειας 225 {N-GSF}\n", encoding="utf-8")
    d = dv.discover(TOPIC, {"fr": fr, "en": {"JHN": {"4": {"25": "But I tell you of a truth, many widows."}}}},
                    ["JHN"], byztxt)
    ref = ("JHN", "4", "25")
    assert ref in d["candidates"]
    fr_steps = dv.steps_for(d, ref, "fr")
    assert {"step": "exclusion_check", "verse": "JHN.4.25", "rules": ["amen_formula"], "found": ["amen_formula"],
            "excluded": True} in fr_steps
    assert not any(s["step"] == "pattern" for s in fr_steps)
    assert dv.summarize(d)["lost_by_phrase"]["fr"] == [ref] and dv.summarize(d)["lost_not_candidate"]["fr"] == []


# --- recorded steps ---

def test_steps_are_neutral_for_union_and_strongs_and_per_language_for_patterns(byztxt):
    d = disc_of(byztxt)
    ref = ("JHN", "8", "32")
    fr, en = dv.steps_for(d, ref, "fr"), dv.steps_for(d, ref, "en")
    assert fr[0] == en[0] == {"step": "union", "verse": "JHN.8.32", "routes": ["strongs", "pattern:fr", "pattern:en"],
                              "single_route": False}
    assert fr[1] == en[1] == {"step": "strongs", "numbers": ["G225"], "verse": "JHN.8.32"}
    assert {"step": "pattern", "rule": "verit", "matched": "vérité", "verse": "JHN.8.32"} in fr
    assert {"step": "pattern", "rule": "truth", "matched": "truth", "verse": "JHN.8.32"} in en
    assert not any(s["step"] == "exclusion_check" for s in en)        # no exclusion rule for English
    assert {"step": "exclusion_check", "verse": "JHN.8.32", "rules": ["amen_formula"], "found": [],
            "excluded": False} in fr


def test_a_verse_found_only_by_the_other_language_still_has_a_union_step(byztxt):
    topic = {**TOPIC, "patterns_fr": {"x": r"\bzzz"}}
    d = dv.discover(topic, {"fr": FR, "en": EN}, ["JHN"], byztxt)
    steps = dv.steps_for(d, ("JHN", "8", "45"), "fr")
    assert steps[0]["routes"] == ["pattern:en"] and steps[0]["single_route"] is True
    assert [s["step"] for s in steps] == ["union", "exclusion_check"]


# --- versification (detection only) ---

def test_versification_notes_report_the_candidates_that_the_table_mentions():
    rows = [{"traditions": ["Latin"], "source_ref": "Jhn.6:55", "standard_ref": "Jhn.6:54", "action": "Renumber verse"},
            {"traditions": ["Hebrew"], "source_ref": "Psa.3:1", "standard_ref": "Psa.3:Title", "action": "Merged"}]
    notes = dv.versification_notes([("JHN", "6", "55"), ("JHN", "3", "16")], rows)
    assert list(notes) == ["JHN.6.55"] and notes["JHN.6.55"][0]["standard_ref"] == "Jhn.6:54"
    assert dv.versification_notes([("JHN", "3", "16")], rows) == {}


def test_ref_id_and_order():
    assert dv.ref_id(("JHN", "14", "6")) == "JHN.14.6"
    key = dv.ref_order(scope_codes("NT"))
    assert sorted([("JHN", "14", "6"), ("MAT", "5", "3"), ("JHN", "3", "16")], key=key)[0] == ("MAT", "5", "3")
