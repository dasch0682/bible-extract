"""Tests for literary.py (task 6, literary context). The model is always a fake."""
import json
from pathlib import Path

import pytest

import literary
import provenance as pv
import validate

ROOT = Path(__file__).resolve().parent.parent
FR = {"dataset": "lsg1910", "prompt_lang": "French", "translation": "Louis Segond 1910"}
REG = pv.load_registry()
CORPUS = {"JHN": {"14": {str(n): f"texte du verset {n}" for n in range(1, 11)}, "15": {"1": "premier verset du chapitre 15"}}}


def answer(text="Jésus répond à Thomas.", cited=("JHN.14.5",), confidence="high"):
    return json.dumps({"text": text, "cited_verses": list(cited), "confidence": confidence}, ensure_ascii=False)


class Fake:
    """A model that returns the given raw answers in turn and records the prompts."""

    def __init__(self, *raws):
        self.raws, self.prompts = list(raws), []

    def __call__(self, system, user):
        self.prompts.append((system, user))
        return self.raws.pop(0) if self.raws else None


def run(fake, verses=("JHN.14.6",), tmp=None, window=3):
    return literary.literary_context(list(verses), CORPUS, "fr", FR, fake, "m/x", tmp, REG, window)


# --- window ---

def test_window_is_the_excerpt_plus_neighbours_inside_the_chapter():
    ids = [v for v, _ in literary.window_verses(["JHN.14.6"], CORPUS, 2)]
    assert ids == ["JHN.14.4", "JHN.14.5", "JHN.14.6", "JHN.14.7", "JHN.14.8"]


def test_window_stops_at_chapter_edges_and_covers_a_multi_verse_excerpt():
    assert [v for v, _ in literary.window_verses(["JHN.14.1"], CORPUS, 2)] == ["JHN.14.1", "JHN.14.2", "JHN.14.3"]
    assert [v for v, _ in literary.window_verses(["JHN.14.9", "JHN.14.10"], CORPUS, 1)] == \
        ["JHN.14.8", "JHN.14.9", "JHN.14.10"]
    assert [v for v, _ in literary.window_verses(["JHN.15.1"], CORPUS, 3)] == ["JHN.15.1"]


# --- the answer is checked by the code ---

SHOWN = {"JHN.14.4", "JHN.14.5", "JHN.14.6"}


@pytest.mark.parametrize("raw,fragment", [
    ("no json at all", "not a JSON object"),
    ("{broken", "not a JSON object"),
    ('{"text": "x", "cited_verses": ["JHN.14.5"]}', "exactly"),
    (answer(cited=()), "at least one"),
    (answer(cited=("JHN.14.9",)), "taken from the list"),
    (answer(cited=("JHN.14.5", "JHN.14.9")), "taken from the list"),
    (answer(confidence="certain"), "high, medium or low"),
    (answer(confidence=None), "high, medium or low"),
    (answer(text=" ".join(["mot"] * 61)), "longer than"),
    (answer(text="deux\nlignes"), "one short paragraph"),
    (answer(text=""), "one short paragraph"),
    (json.dumps({"text": None, "cited_verses": ["JHN.14.5"], "confidence": "high"}), "null text"),
])
def test_bad_answers_are_refused_with_a_reason(raw, fragment):
    got, problem = literary.check_answer(raw, SHOWN)
    assert got is None and fragment in problem


def test_good_answers_pass_and_citations_are_deduplicated():
    got, problem = literary.check_answer(answer(cited=("JHN.14.5", "JHN.14.5", "JHN.14.4")), SHOWN)
    assert problem is None and got["cited_verses"] == ["JHN.14.5", "JHN.14.4"]
    assert literary.check_answer(answer(text=" ".join(["mot"] * 60)), SHOWN)[1] is None      # exactly the limit


def test_a_null_answer_is_a_valid_answer():
    raw = json.dumps({"text": None, "cited_verses": [], "confidence": None})
    assert literary.check_answer(raw, SHOWN) == ({"text": None, "cited_verses": [], "confidence": None}, None)


# --- the field ---

def test_field_has_sources_confidence_and_who_judged(tmp_path):
    out = run(Fake(answer(cited=("JHN.14.5", "JHN.14.6"), confidence="medium")), tmp=tmp_path)
    f = out["literary"]
    assert f == {"text": "Jésus répond à Thomas.", "confidence": "medium", "sources": ["JHN.14.5", "JHN.14.6"],
                 "confidence_by": "model", "model": "m/x", "prompt_version": literary.PROMPT_VERSION}
    assert [s["id"] for s in out["sources"]] == f["sources"] and out["flags"] == []
    assert all(s["type"] == "bible_text" and s["dataset"] == "lsg1910" for s in out["sources"])
    assert validate._check_literary(f) == []


def test_prompt_shows_only_the_window_and_tells_the_model_to_cite_from_it(tmp_path):
    fake = Fake(answer())
    run(fake, tmp=tmp_path, window=1)
    system, user = fake.prompts[0]
    assert "French" in system and "Louis Segond 1910" in system and "ONLY" in system
    assert "JHN.14.5: texte du verset 5" in user and "JHN.14.7: texte du verset 7" in user
    assert "JHN.14.4" not in user and "JHN.14.8" not in user          # outside the window
    assert user.startswith("Excerpt: JHN.14.6")


def test_citing_a_verse_not_shown_triggers_one_retry_with_the_reason(tmp_path):
    fake = Fake(answer(cited=("JHN.14.10",)), answer(cited=("JHN.14.5",)))     # 14,10 is outside the window of 3
    out = run(fake, tmp=tmp_path)
    assert out["literary"]["sources"] == ["JHN.14.5"] and out["flags"] == []
    assert len(fake.prompts) == 2 and "taken from the list shown" in fake.prompts[1][1]


def test_two_bad_answers_give_null_no_source_and_a_review_flag(tmp_path):
    fake = Fake("nonsense", answer(cited=()))
    out = run(fake, tmp=tmp_path)
    assert out["literary"] == {"text": None, "reason": "no_source"} and out["flags"] == ["literary_failed"]
    assert out["sources"] == [] and len(fake.prompts) == 2
    assert validate._check_literary(out["literary"]) == []
    assert not list(tmp_path.rglob("*.json"))                           # nothing invalid is cached


def test_no_answer_from_the_model_is_a_failure_not_a_crash(tmp_path):
    out = run(Fake(), tmp=tmp_path)
    assert out["flags"] == ["literary_failed"]


def test_a_null_answer_is_no_source_without_a_flag(tmp_path):
    out = run(Fake(json.dumps({"text": None, "cited_verses": [], "confidence": None})), tmp=tmp_path)
    assert out == {"literary": {"text": None, "reason": "no_source"}, "sources": [], "flags": []}


# --- cache ---

def test_valid_answer_is_cached_per_excerpt_model_and_window(tmp_path):
    fake = Fake(answer())
    first = run(fake, tmp=tmp_path)
    second = run(fake, tmp=tmp_path)
    assert first == second and len(fake.prompts) == 1
    run(Fake(answer()), verses=("JHN.14.7",), tmp=tmp_path)             # another excerpt: new file
    run(Fake(answer()), tmp=tmp_path, window=2)                          # another window: new file
    assert len(list((tmp_path / "literary" / "fr").glob("*.json"))) == 3


def test_a_cached_answer_that_no_longer_fits_the_window_is_ignored(tmp_path):
    run(Fake(answer(cited=("JHN.14.4",))), tmp=tmp_path)
    cached = next((tmp_path / "literary" / "fr").glob("*.json"))
    cached.write_text(answer(cited=("JHN.14.10",)), encoding="utf-8")   # a stale or edited file
    fake = Fake(answer(cited=("JHN.14.5",)))
    assert run(fake, tmp=tmp_path)["literary"]["sources"] == ["JHN.14.5"] and len(fake.prompts) == 1
