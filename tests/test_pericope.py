"""Tests for pericope.py. No network calls — the model is always a fake."""
import json
from pathlib import Path

import pytest

import pericope as pc

LANG_CFG = {"prompt_lang": "French", "translation": "Louis Segond 1910"}
MODEL = "deepseek/deepseek-v4.1-flash"

RULES = pc.load_rules()

# Minimal corpus: book MAT, chapters 1 and 9
CORPUS = {
    "MAT": {
        "1": {"1": "Abraham engendra Isaac.", "2": "Isaac engendra Jacob.", "3": "Jacob engendra Juda."},
        "9": {
            "36": "Il vit les foules et fut ému de compassion.",
            "37": "La moisson est grande, mais il y a peu d'ouvriers.",
            "38": "Priez le maître de la moisson d'envoyer des ouvriers.",
        },
    }
}

GOOD_ANSWER = {
    "narrative_arc": "Jésus voit les foules et envoie des ouvriers pour la moisson.",
    "scene_location": "Galilée, lors d'un parcours des villes et villages.",
    "book_position": "Après la guérison de deux aveugles, avant l'envoi des Douze.",
}


def good_raw():
    return json.dumps(GOOD_ANSWER, ensure_ascii=False)


class FakeCall:
    def __init__(self, *raws):
        self.raws = list(raws)
        self.calls = []

    def __call__(self, system, user):
        self.calls.append((system, user))
        return self.raws.pop(0) if self.raws else None


# --- load_rules ---

def test_load_rules_returns_three_limits():
    r = pc.load_rules()
    for field in pc.FIELDS:
        assert isinstance(r[f"max_words_{field}"], int)
        assert r[f"max_words_{field}"] > 0


def test_load_rules_rejects_missing_key(tmp_path):
    (tmp_path / "bad.yml").write_text("max_words_narrative_arc: 60\n", encoding="utf-8")
    with pytest.raises(pc.RulesError):
        pc.load_rules(tmp_path / "bad.yml")


def test_load_rules_rejects_boolean(tmp_path):
    yml = "max_words_narrative_arc: true\nmax_words_scene_location: 30\nmax_words_book_position: 40\n"
    (tmp_path / "bad.yml").write_text(yml, encoding="utf-8")
    with pytest.raises(pc.RulesError):
        pc.load_rules(tmp_path / "bad.yml")


# --- chapter_verses ---

def test_chapter_verses_order():
    verses = pc.chapter_verses("MAT", "9", CORPUS)
    assert [v for v, _ in verses] == ["MAT.9.36", "MAT.9.37", "MAT.9.38"]


def test_chapter_verses_texts():
    verses = pc.chapter_verses("MAT", "9", CORPUS)
    assert verses[0] == ("MAT.9.36", "Il vit les foules et fut ému de compassion.")


# --- check_answer ---

def test_check_answer_valid():
    answer, problem = pc.check_answer(good_raw(), RULES)
    assert problem is None
    assert answer == GOOD_ANSWER


def test_check_answer_not_json():
    answer, problem = pc.check_answer("not json", RULES)
    assert answer is None and problem


def test_check_answer_wrong_keys():
    bad = json.dumps({"narrative_arc": "x", "scene_location": "y"})
    answer, problem = pc.check_answer(bad, RULES)
    assert answer is None and "exactly" in problem


def test_check_answer_empty_field():
    bad = {**GOOD_ANSWER, "scene_location": "   "}
    answer, problem = pc.check_answer(json.dumps(bad), RULES)
    assert answer is None and "scene_location" in problem


def test_check_answer_too_long(tmp_path):
    tight_rules = {**RULES, "max_words_narrative_arc": 3}
    answer, problem = pc.check_answer(good_raw(), tight_rules)
    assert answer is None and "narrative_arc" in problem


def test_check_answer_strips_whitespace():
    padded = {k: f"  {v}  " for k, v in GOOD_ANSWER.items()}
    answer, _ = pc.check_answer(json.dumps(padded), RULES)
    assert all(v == v.strip() for v in answer.values())


def test_check_answer_json_embedded_in_text():
    raw = f"Voici le résumé : {good_raw()} — fin."
    answer, problem = pc.check_answer(raw, RULES)
    assert problem is None and answer == GOOD_ANSWER


# --- build_pericope ---

def test_build_pericope_returns_all_fields(tmp_path):
    call = FakeCall(good_raw())
    result = pc.build_pericope(["MAT.9.37"], CORPUS, "fr", LANG_CFG, call, MODEL, tmp_path, RULES)
    assert result is not None
    assert result["chapter_id"] == "MAT.9"
    for field in pc.FIELDS:
        assert field in result and result[field]


def test_build_pericope_calls_model_once(tmp_path):
    call = FakeCall(good_raw())
    pc.build_pericope(["MAT.9.37"], CORPUS, "fr", LANG_CFG, call, MODEL, tmp_path, RULES)
    assert len(call.calls) == 1


def test_build_pericope_caches_result(tmp_path):
    call = FakeCall(good_raw())
    pc.build_pericope(["MAT.9.37"], CORPUS, "fr", LANG_CFG, call, MODEL, tmp_path, RULES)
    # Second call: no model call, result from cache
    call2 = FakeCall()
    result = pc.build_pericope(["MAT.9.37"], CORPUS, "fr", LANG_CFG, call2, MODEL, tmp_path, RULES)
    assert result is not None and len(call2.calls) == 0


def test_build_pericope_same_chapter_hits_cache(tmp_path):
    """Any verse from the same chapter reuses the chapter cache."""
    call = FakeCall(good_raw())
    pc.build_pericope(["MAT.9.37"], CORPUS, "fr", LANG_CFG, call, MODEL, tmp_path, RULES)
    call2 = FakeCall()
    result = pc.build_pericope(["MAT.9.38"], CORPUS, "fr", LANG_CFG, call2, MODEL, tmp_path, RULES)
    assert result is not None and len(call2.calls) == 0


def test_build_pericope_retries_once_on_bad_answer(tmp_path):
    call = FakeCall("not json at all", good_raw())
    result = pc.build_pericope(["MAT.9.37"], CORPUS, "fr", LANG_CFG, call, MODEL, tmp_path, RULES)
    assert result is not None
    assert len(call.calls) == 2
    _, retry_user = call.calls[1]
    assert "previous answer rejected" in retry_user


def test_build_pericope_returns_none_after_two_failures(tmp_path):
    call = FakeCall("bad", "also bad")
    result = pc.build_pericope(["MAT.9.37"], CORPUS, "fr", LANG_CFG, call, MODEL, tmp_path, RULES)
    assert result is None


def test_build_pericope_none_call_returns_none(tmp_path):
    result = pc.build_pericope(["MAT.9.37"], CORPUS, "fr", LANG_CFG, lambda s, u: None, MODEL, tmp_path, RULES)
    assert result is None


def test_build_pericope_prompt_contains_all_chapter_verses(tmp_path):
    call = FakeCall(good_raw())
    pc.build_pericope(["MAT.9.37"], CORPUS, "fr", LANG_CFG, call, MODEL, tmp_path, RULES)
    _, user = call.calls[0]
    assert "MAT.9.36" in user and "MAT.9.37" in user and "MAT.9.38" in user


def test_build_pericope_prompt_contains_chapter_position(tmp_path):
    call = FakeCall(good_raw())
    pc.build_pericope(["MAT.9.37"], CORPUS, "fr", LANG_CFG, call, MODEL, tmp_path, RULES)
    _, user = call.calls[0]
    # chapter 9 of 2 (MAT corpus has chapters 1 and 9)
    assert "chapter 9" in user and "of 2" in user


def test_build_pericope_different_langs_have_separate_caches(tmp_path):
    call_fr = FakeCall(good_raw())
    call_en = FakeCall(good_raw())
    pc.build_pericope(["MAT.9.37"], CORPUS, "fr", LANG_CFG, call_fr, MODEL, tmp_path, RULES)
    pc.build_pericope(["MAT.9.37"], CORPUS, "en", LANG_CFG, call_en, MODEL, tmp_path, RULES)
    assert len(call_fr.calls) == 1 and len(call_en.calls) == 1
