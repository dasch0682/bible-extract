"""Tests for context.py: the four parts assembled, checked by validate.py itself (task 6)."""
import json
from pathlib import Path

import pytest

import context
import datasets as ds
import provenance as pv
import validate

ROOT = Path(__file__).resolve().parent.parent
REG = pv.load_registry()
RULES = context.load_rules()
KNOWN = pv.known_datasets(REG)

LANGS = {
    "fr": {"dataset": "lsg1910", "prompt_lang": "French", "translation": "Louis Segond 1910"},
    "en": {"dataset": "kjv", "prompt_lang": "English", "translation": "King James Version (1769)"},
}
CORPORA = {
    "fr": {"JHN": {"14": {"5": "Thomas lui dit: Seigneur, nous ne savons où tu vas.",
                          "6": "Jésus lui dit: Je suis le chemin, la vérité, et la vie.",
                          "7": "Si vous me connaissez, vous connaîtrez aussi mon Père."}}},
    "en": {"JHN": {"14": {"5": "Thomas saith unto him, Lord, we know not whither thou goest.",
                          "6": "Jesus saith unto him, I am the way, the truth, and the life.",
                          "7": "If ye had known me, ye should have known my Father also."}}},
}
NAMES = {"fr": {"Jesus": "Jésus", "The Holy Spirit comes": "Le Saint-Esprit vient", "Achaia": "Achaïe"},
         "en": {}}


def model(lang):
    """A fake model: translates labels from NAMES, answers the literary prompt with a cited verse."""
    def call(system, user):
        if "literary context" in system:
            return json.dumps({"text": "Jésus répond à Thomas." if lang == "fr" else "Jesus answers Thomas.",
                               "cited_verses": ["JHN.14.5"], "confidence": "high"}, ensure_ascii=False)
        label = user.split("\n")[0].removeprefix("Label: ")
        return NAMES[lang].get(label, label)
    return call


def data(speakers=(), people=(), events=(), places=()):
    acai = {"people": {}, "places": {}}
    for vid, pid, label in people:
        acai["people"].setdefault(ds.verse_key(vid), []).append({"id": pid, "label": label})
    theo = {"events": {}, "places": {}}
    for vid, e in events:
        theo["events"].setdefault(ds.verse_key(vid), []).append(e)
    ob = {}
    for vid, p in places:
        ob.setdefault(ds.verse_key(vid), []).append(p)
    return {"theographic": theo, "openbible": ob, "speakers": list(speakers), "acai": acai, "anchors": []}


JESUS = [{"start": ds.verse_key("JHN.14.6"), "end": ds.verse_key("JHN.14.7"), "speaker": "Jesus", "type": "Dialogue"}]
PEOPLE = [("JHN.14.6", "person:Jesus.2", "Jesus")]
PENTECOST = [("JHN.14.6", {"id": "307", "title": "The Holy Spirit comes", "year": 30, "precision": "day", "places": []})]
ACHAIA = [("JHN.14.6", {"id": "aef4242", "name": "Achaia", "wikidata": "Q192787", "score": 500, "identifications": 1,
                        "total": 500, "count": 1, "special": None})]


def build(lang, tmp, d, verses=("JHN.14.6",)):
    call = model(lang)
    return context.build_context(list(verses), CORPORA[lang], lang, LANGS[lang], d, RULES, REG,
                                 {"speaker": (call, "m/speaker"), "context": (call, "m/context")}, tmp)


def entry(lang, built, verses=("JHN.14.6",), corpus=None):
    """A whole schema-2 entry around the built context; the paraphrase is null (task 7 is not done)."""
    corpus = corpus or CORPORA[lang]
    text = " ".join(corpus[v.split(".")[0]][v.split(".")[1]][v.split(".")[2]] for v in verses)
    verse_sources = [pv.verse_source(v, LANGS[lang]["dataset"], REG) for v in verses]
    return {
        "schema_version": "2", "language": lang,
        "reference": {"book": "JHN", "start": verses[0].split(".", 1)[1], "end": verses[-1].split(".", 1)[1],
                      "label": "Jean 14,6"},
        "excerpt": {"text": text, "verses": list(verses)},
        "paraphrase": {"text": None, "reason": "no_faithful_version"},
        "speaker": built["speaker"], "context": built["context"],
        "discovery": {"mode": "rules", "steps": [{"step": "strongs", "numbers": ["G225"], "verse": "JHN.14.6"}]},
        "review": {"status": None, "note": None},
        "sources": pv.merge_sources(verse_sources, built["sources"]),
    }


# --- one language, everything present ---

def test_full_context_of_john_14_6_validates_as_a_whole_entry(tmp_path):
    d = data(JESUS, PEOPLE, PENTECOST, ACHAIA)
    built = build("fr", tmp_path, d)
    assert built["speaker"]["value"] == "Jésus" and built["speaker"]["confidence"] == "high"
    ctx = built["context"]
    assert ctx["literary"]["text"] == "Jésus répond à Thomas." and ctx["literary"]["confidence_by"] == "model"
    (t,) = ctx["temporal"]
    assert t["label"] == "Le Saint-Esprit vient" and t["day_candidates"] and t["confidence"] == "disputed"
    assert [p["name"] for p in ctx["places"]] == ["Achaïe"]
    assert built["flags"] == [] and built["review_required"] is False
    assert validate.validate_entry(entry("fr", built), CORPORA["fr"], KNOWN) == []


def test_every_cited_source_is_listed_with_type_dataset_and_license(tmp_path):
    built = build("fr", tmp_path, data(JESUS, PEOPLE, PENTECOST, ACHAIA))
    ids = {s["id"] for s in built["sources"]}
    assert {"JHN.14.5", "JHN.14.6", "speaker-quotations:JHN.14.6-JHN.14.7", "acai:person:Jesus.2",
            "theographic:event:307", "meeus:chapter-49", "calendar-rules:pentecost",
            "openbible:aef4242"} <= ids
    assert "calendar-rules:passion" not in ids                            # only the events of the excerpt are cited
    assert all(s["type"] and s["dataset"] in KNOWN and s["license"] for s in built["sources"])
    assert [s["id"] for s in built["sources"]] == [s["id"] for s in pv.merge_sources(built["sources"])]   # no duplicates


# --- nothing known: still a valid entry ---

def test_with_no_dataset_knowledge_the_entry_is_still_valid(tmp_path):
    built = build("fr", tmp_path, data())
    assert built["speaker"] == {"value": None, "reason": "not_identified"}
    assert built["context"]["temporal"] == [] and built["context"]["places"] == []
    assert built["flags"] == ["speaker_not_identified"] and built["review_required"] is False
    assert validate.validate_entry(entry("fr", built), CORPORA["fr"], KNOWN) == []


# --- flags and review ---

def test_ambiguous_speaker_requires_review(tmp_path):
    two = [{"start": ds.verse_key("JHN.14.5"), "end": ds.verse_key("JHN.14.5"), "speaker": "Thomas", "type": "Dialogue"},
           {"start": ds.verse_key("JHN.14.6"), "end": ds.verse_key("JHN.14.6"), "speaker": "Jesus", "type": "Dialogue"}]
    built = build("fr", tmp_path, data(two), verses=("JHN.14.5", "JHN.14.6"))
    assert built["speaker"] == {"value": None, "reason": "not_identified"}
    assert built["speaker_candidates"] == ["Jesus", "Thomas"] and built["review_required"] is True
    assert validate.validate_entry(entry("fr", built, ("JHN.14.5", "JHN.14.6")), CORPORA["fr"], KNOWN) == []


def test_a_failed_literary_answer_requires_review_and_stays_valid(tmp_path):
    call = lambda system, user: None                                      # noqa: E731  the model is down
    built = context.build_context(["JHN.14.6"], CORPORA["fr"], "fr", LANGS["fr"], data(JESUS, PEOPLE), RULES, REG,
                                  {"speaker": (call, "m/s"), "context": (call, "m/c")}, tmp_path)
    assert built["context"]["literary"] == {"text": None, "reason": "no_source"}
    assert "literary_failed" in built["flags"] and "name_not_localized" in built["flags"]
    assert built["speaker"]["value"] == "Jesus"                            # the dataset label is kept, flagged
    assert built["review_required"] is True
    assert validate.validate_entry(entry("fr", built), CORPORA["fr"], KNOWN) == []


@pytest.mark.parametrize("flags,expected", [([], False), (["name_not_localized"], False),
                                            (["label_not_localized:theographic:event:1"], False),
                                            (["speaker_ambiguous"], True), (["x", "literary_failed"], True)])
def test_review_required(flags, expected):
    assert context.review_required(flags) is expected


# --- both languages agree on the neutral fields ---

def test_french_and_english_contexts_pass_the_cross_language_check(tmp_path):
    d = data(JESUS, PEOPLE, PENTECOST, ACHAIA)
    files = {lang: [entry(lang, build(lang, tmp_path, d))] for lang in ("fr", "en")}
    for lang, entries in files.items():
        assert validate.validate_entry(entries[0], CORPORA[lang], KNOWN) == []
    assert validate.check_cross_language(files) == []
    assert files["fr"][0]["context"]["temporal"][0]["label"] != files["en"][0]["context"]["temporal"][0]["label"]


def test_day_candidate_texts_follow_the_language_but_not_the_dates(tmp_path):
    d = data(JESUS, PEOPLE, PENTECOST, ACHAIA)
    fr = build("fr", tmp_path, d)["context"]["temporal"][0]["day_candidates"]
    en = build("en", tmp_path, d)["context"]["temporal"][0]["day_candidates"]
    assert [c["date"] for c in fr] == [c["date"] for c in en]
    assert "julien" in fr[0]["assumptions"][0] and "Julian" in en[0]["assumptions"][0]


# --- rules and data loaders ---

def test_rule_files_load_together():
    assert set(RULES) == {"dates", "calendar", "places"}


real = pytest.mark.skipif(not all((ROOT / "tmp" / d).exists()
                                  for d in ("theographic", "openbible-geocoding", "speaker-quotations", "acai")),
                          reason="tmp/ datasets not fetched")


@real
def test_real_datasets_load_and_give_a_valid_context_for_acts_2_1(tmp_path):
    real_data = context.load_data()
    corpus = {"ACT": {"2": {"1": "Le jour de la Pentecôte, ils étaient tous ensemble."}}}
    call = lambda system, user: (json.dumps({"text": None, "cited_verses": [], "confidence": None})  # noqa: E731
                                 if "literary context" in system else None)
    built = context.build_context(["ACT.2.1"], corpus, "fr", LANGS["fr"], real_data, RULES, REG,
                                  {"speaker": (call, "m/s"), "context": (call, "m/c")}, tmp_path)
    (t,) = built["context"]["temporal"]
    assert t["sources"] == ["theographic:event:307"] and len(t["day_candidates"]) == 3
    e = entry("fr", built, ("ACT.2.1",), corpus)
    e["reference"] = {"book": "ACT", "start": "2.1", "end": "2.1", "label": "Actes 2,1"}
    assert validate.validate_entry(e, corpus, KNOWN) == []
