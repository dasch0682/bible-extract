"""Tests for relevance.py (task 8): the model judges and bounds within limits fixed by the code. Fake models only."""
import json

import pytest

import relevance as rl

FR = {"prompt_lang": "French", "translation": "Louis Segond 1910"}
CORPUS = {"JHN": {"14": {str(v): f"verset {v}" for v in range(1, 11)}}}
SHOWN = [f"JHN.14.{v}" for v in range(3, 10)]          # what the model sees around 14.6 with a window of 3
CAND = "JHN.14.6"


def answer(relevant=True, cited=(CAND,), start="JHN.14.6", end="JHN.14.7"):
    return json.dumps({"relevant": relevant, "cited_verses": list(cited), "start": start, "end": end})


NOT = json.dumps({"relevant": False, "cited_verses": [], "start": None, "end": None})


class Model:
    def __init__(self, *raws):
        self.raws, self.prompts = list(raws), []

    def __call__(self, system, user):
        self.prompts.append((system, user))
        return self.raws.pop(0) if self.raws else None


def judge(call, tmp, extra="", window=3):
    return rl.judge(CAND, CORPUS, "fr", FR, "la vérité", extra, call, "m/rel", tmp, window)


# --- the code's checks ---

def test_a_relevant_answer_gives_the_verses_between_the_bounds():
    a, problem = rl.check_answer(answer(cited=["JHN.14.6", "JHN.14.7"]), SHOWN, CAND)
    assert problem is None
    assert a == {"relevant": True, "cited_verses": ["JHN.14.6", "JHN.14.7"], "verses": ["JHN.14.6", "JHN.14.7"]}


def test_a_not_relevant_answer_has_no_citation_and_no_bounds():
    assert rl.check_answer(NOT, SHOWN, CAND) == ({"relevant": False, "cited_verses": [], "verses": []}, None)


@pytest.mark.parametrize("raw, why", [
    ("no json here", "not a JSON object"),
    ("{not json}", "not valid JSON"),
    (json.dumps({"relevant": True}), "exactly relevant"),
    (answer(relevant="yes"), "true or false"),
    (answer(cited=[]), "at least one"),
    (answer(cited=["JHN.14.99"]), "taken from the list"),
    (answer(start="JHN.13.1"), "taken from the list"),
    (answer(end="JHN.15.1"), "taken from the list"),
    (answer(start="JHN.14.7", end="JHN.14.6"), "must not come after"),
    (answer(start="JHN.14.7", end="JHN.14.8", cited=["JHN.14.7"]), "contain the verse to judge"),
    (answer(cited=["JHN.14.8"]), "contain every cited verse"),
    (json.dumps({"relevant": False, "cited_verses": ["JHN.14.6"], "start": None, "end": None}), "no citations"),
    (json.dumps({"relevant": False, "cited_verses": [], "start": "JHN.14.6", "end": "JHN.14.6"}), "no bounds"),
    (None, "not a JSON object"),
])
def test_the_code_rejects_what_the_model_may_not_do(raw, why):
    a, problem = rl.check_answer(raw, SHOWN, CAND)
    assert a is None and why in problem


def test_the_model_cannot_add_a_verse_outside_the_ones_shown():
    a, problem = rl.check_answer(answer(start="JHN.14.6", end="JHN.14.10"), SHOWN, CAND)     # 14.10 was not shown
    assert a is None and "taken from the list" in problem


# --- the call ---

def test_judge_returns_the_verdict_with_the_model_and_prompt_version(tmp_path):
    v = judge(Model(answer(cited=["JHN.14.6"])), tmp_path)
    assert v == {"relevant": True, "cited_verses": ["JHN.14.6"], "verses": ["JHN.14.6", "JHN.14.7"],
                 "model": "m/rel", "prompt_version": rl.PROMPT_VERSION}


def test_the_model_sees_only_the_candidate_window_and_the_topic_instructions(tmp_path):
    m = Model(answer())
    judge(m, tmp_path, extra="Nuance: amen is not relevant.")
    system, user = m.prompts[0]
    assert "Nuance: amen is not relevant." in system and "Theme: la vérité" in user
    shown = [line.split(":")[0] for line in user.split("Verses:\n")[1].splitlines()]
    assert shown == SHOWN and f"Verse to judge: {CAND}" in user


def test_a_bad_answer_is_retried_once_with_the_reason(tmp_path):
    m = Model("oops", answer())
    v = judge(m, tmp_path)
    assert v["relevant"] is True and len(m.prompts) == 2
    assert "IMPORTANT (previous answer rejected)" in m.prompts[1][1] and "JSON" in m.prompts[1][1]


def test_two_bad_answers_give_no_verdict(tmp_path):
    m = Model("oops", answer(cited=[]))
    assert judge(m, tmp_path) is None and len(m.prompts) == 2


def test_a_valid_answer_is_cached_and_not_asked_again(tmp_path):
    m = Model(answer())
    first = judge(m, tmp_path)
    again = judge(Model(), tmp_path)                    # a model that would answer None
    assert again == first and len(m.prompts) == 1


def test_a_not_relevant_verdict_is_cached_too(tmp_path):
    judge(Model(NOT), tmp_path)
    assert judge(Model(), tmp_path)["relevant"] is False


def test_another_wording_of_the_topic_does_not_reuse_the_cache(tmp_path):
    judge(Model(answer()), tmp_path)
    m = Model(answer())
    judge(m, tmp_path, extra="a different instruction")
    assert len(m.prompts) == 1


def test_a_failed_call_is_not_cached(tmp_path):
    assert judge(Model(), tmp_path) is None
    assert not list(tmp_path.rglob("*.json"))
