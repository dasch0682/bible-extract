"""Tests for narrative.py. No network calls — the model is always a fake."""
import json
from pathlib import Path

import pytest

import narrative as nv
import provenance as pv
import validate

FR = {"dataset": "lsg1910", "prompt_lang": "French", "translation": "Louis Segond 1910"}
REG = pv.load_registry()
MODEL = "deepseek/deepseek-v4.1-flash"

# Corpus: JHN 14 with verses 1–10, and a sparse JHN 15 for edge cases
CORPUS = {
    "JHN": {
        "14": {str(n): f"texte du verset {n}" for n in range(1, 11)},
        "15": {"1": "Je suis le vrai cep."},
    }
}

RULES = nv.load_rules()

GOOD_ANSWER = {
    "situation": "Jésus répond à Thomas qui lui demande le chemin.",
    "place": "Salle haute à Jérusalem, lors du repas d'adieu.",
    "arc_position": "Après l'annonce de la trahison de Judas, avant la prière sacerdotale.",
    "cited_verses": ["JHN.14.5", "JHN.14.6"],
    "confidence": "high",
}

PERICOPE = {
    "narrative_arc": "Jésus prend congé de ses disciples et leur promet de préparer une place.",
    "scene_location": "Salle haute, Jérusalem.",
    "book_position": "Après l'entrée triomphale, avant la passion.",
    "chapter_id": "JHN.14",
}


def good_raw():
    return json.dumps(GOOD_ANSWER, ensure_ascii=False)


class Fake:
    def __init__(self, *raws):
        self.raws = list(raws)
        self.calls = []

    def __call__(self, system, user):
        self.calls.append((system, user))
        return self.raws.pop(0) if self.raws else None


def run(fake, verses=("JHN.14.6",), tmp=None, pericope=None, rules=None):
    return nv.build_narrative(list(verses), CORPUS, "fr", FR, fake, MODEL,
                              tmp, REG, rules or RULES, pericope_summary=pericope)


# --- load_rules ---

def test_load_rules_returns_all_keys():
    r = nv.load_rules()
    for field in nv.FIELDS:
        assert f"max_words_{field}" in r
    assert "window" in r and r["window"] > 0


def test_load_rules_rejects_missing_field(tmp_path):
    yml = "max_words_situation: 80\nmax_words_place: 40\nnarrative_window: 10\n"
    (tmp_path / "r.yml").write_text(yml, encoding="utf-8")
    with pytest.raises(nv.RulesError):
        nv.load_rules(tmp_path / "r.yml")


def test_load_rules_rejects_missing_window(tmp_path):
    yml = "max_words_situation: 80\nmax_words_place: 40\nmax_words_arc_position: 50\n"
    (tmp_path / "r.yml").write_text(yml, encoding="utf-8")
    with pytest.raises(nv.RulesError):
        nv.load_rules(tmp_path / "r.yml")


def test_load_rules_rejects_boolean(tmp_path):
    yml = ("max_words_situation: true\nmax_words_place: 40\n"
           "max_words_arc_position: 50\nnarrative_window: 10\n")
    (tmp_path / "r.yml").write_text(yml, encoding="utf-8")
    with pytest.raises(nv.RulesError):
        nv.load_rules(tmp_path / "r.yml")


# --- check_answer ---

SHOWN = {"JHN.14.4", "JHN.14.5", "JHN.14.6", "JHN.14.7", "JHN.14.8"}


def test_check_answer_valid():
    answer, problem = nv.check_answer(good_raw(), SHOWN, RULES)
    assert problem is None
    assert answer["situation"] == GOOD_ANSWER["situation"]
    assert answer["confidence"] == "high"


def test_check_answer_not_json():
    a, p = nv.check_answer("not json", SHOWN, RULES)
    assert a is None and p


@pytest.mark.parametrize("raw,fragment", [
    ('{"situation": "x"}', "exactly"),
    (json.dumps({**GOOD_ANSWER, "situation": ""}), "situation"),
    (json.dumps({**GOOD_ANSWER, "cited_verses": []}), "at least one"),
    (json.dumps({**GOOD_ANSWER, "cited_verses": ["JHN.14.99"]}), "taken from"),
    (json.dumps({**GOOD_ANSWER, "confidence": "certain"}), "high, medium or low"),
])
def test_bad_answers_refused(raw, fragment):
    a, p = nv.check_answer(raw, SHOWN, RULES)
    assert a is None and fragment in p


def test_check_answer_field_too_long():
    long_rules = {**RULES, "max_words_situation": 3}
    a, p = nv.check_answer(good_raw(), SHOWN, long_rules)
    assert a is None and "situation" in p


def test_check_answer_deduplicates_citations():
    dup = {**GOOD_ANSWER, "cited_verses": ["JHN.14.5", "JHN.14.5", "JHN.14.6"]}
    a, _ = nv.check_answer(json.dumps(dup), SHOWN, RULES)
    assert a["cited_verses"] == ["JHN.14.5", "JHN.14.6"]


def test_check_answer_strips_whitespace():
    padded = {**GOOD_ANSWER, "situation": "  texte  ", "place": "  lieu  ", "arc_position": "  arc  "}
    a, _ = nv.check_answer(json.dumps(padded), SHOWN, RULES)
    assert a["situation"] == "texte" and a["place"] == "lieu" and a["arc_position"] == "arc"


# --- build_narrative: result structure ---

def test_result_contains_all_fields(tmp_path):
    out = run(Fake(good_raw()), tmp=tmp_path)
    f = out["narrative"]
    assert f["situation"] and f["place"] and f["arc_position"]
    assert f["confidence"] == "high" and f["confidence_by"] == "model"
    assert f["model"] == MODEL and f["prompt_version"] == nv.PROMPT_VERSION
    assert f["sources"] == ["JHN.14.5", "JHN.14.6"]
    assert out["flags"] == []


def test_sources_are_bible_text_records(tmp_path):
    out = run(Fake(good_raw()), tmp=tmp_path)
    assert all(s["type"] == "bible_text" and s["dataset"] == "lsg1910" for s in out["sources"])


def test_failure_gives_no_source_and_flag(tmp_path):
    out = run(Fake("bad", "also bad"), tmp=tmp_path)
    assert out["narrative"] == {"text": None, "reason": "no_source"}
    assert "narrative_failed" in out["flags"] and out["sources"] == []


def test_no_model_answer_does_not_crash(tmp_path):
    out = run(Fake(), tmp=tmp_path)
    assert "narrative_failed" in out["flags"]


# --- prompt structure ---

def test_prompt_shows_window_around_excerpt(tmp_path):
    tight_rules = {**RULES, "window": 1}
    fake = Fake(good_raw())
    run(fake, tmp=tmp_path, rules=tight_rules)
    _, user = fake.calls[0]
    assert "JHN.14.5: texte du verset 5" in user
    assert "JHN.14.7: texte du verset 7" in user
    assert "JHN.14.4" not in user and "JHN.14.8" not in user


def test_prompt_without_pericope_has_no_background_block(tmp_path):
    fake = Fake(good_raw())
    run(fake, tmp=tmp_path, pericope=None)
    _, user = fake.calls[0]
    assert "Chapter background" not in user


def test_prompt_with_pericope_injects_background(tmp_path):
    fake = Fake(good_raw())
    run(fake, tmp=tmp_path, pericope=PERICOPE)
    _, user = fake.calls[0]
    assert "Chapter background" in user
    assert PERICOPE["narrative_arc"] in user
    assert PERICOPE["scene_location"] in user
    assert PERICOPE["book_position"] in user


def test_system_prompt_contains_lang_and_translation(tmp_path):
    fake = Fake(good_raw())
    run(fake, tmp=tmp_path)
    system, _ = fake.calls[0]
    assert "French" in system and "Louis Segond 1910" in system


# --- retry ---

def test_retries_once_on_bad_answer(tmp_path):
    fake = Fake("not json at all", good_raw())
    out = run(fake, tmp=tmp_path)
    assert out["narrative"]["situation"] and len(fake.calls) == 2
    assert "previous answer rejected" in fake.calls[1][1]


# --- cache ---

def test_valid_answer_is_cached(tmp_path):
    fake = Fake(good_raw())
    first = run(fake, tmp=tmp_path)
    second = run(Fake(), tmp=tmp_path)
    assert second["narrative"]["situation"] == first["narrative"]["situation"]
    assert len(list((tmp_path / "narrative" / "fr").glob("*.json"))) == 1


def test_different_pericope_uses_different_cache(tmp_path):
    run(Fake(good_raw()), tmp=tmp_path, pericope=None)
    run(Fake(good_raw()), tmp=tmp_path, pericope=PERICOPE)
    assert len(list((tmp_path / "narrative" / "fr").glob("*.json"))) == 2


def test_different_excerpt_uses_different_cache(tmp_path):
    run(Fake(good_raw()), verses=("JHN.14.6",), tmp=tmp_path)
    run(Fake(good_raw()), verses=("JHN.14.7",), tmp=tmp_path)
    assert len(list((tmp_path / "narrative" / "fr").glob("*.json"))) == 2


def test_stale_cache_with_invalid_citation_is_ignored(tmp_path):
    run(Fake(good_raw()), tmp=tmp_path)
    cf = next((tmp_path / "narrative" / "fr").glob("*.json"))
    stale = {**GOOD_ANSWER, "cited_verses": ["JHN.14.99"]}
    cf.write_text(json.dumps(stale), encoding="utf-8")
    fake = Fake(good_raw())
    out = run(fake, tmp=tmp_path)
    assert out["narrative"]["situation"] and len(fake.calls) == 1


def test_nothing_cached_on_failure(tmp_path):
    run(Fake("bad", "bad"), tmp=tmp_path)
    assert not list(tmp_path.rglob("*.json"))
