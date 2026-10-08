"""Tests for paraphrase.py (task 7). The models are always fakes: no network, no model identifier in the code."""
import json

import pytest

import paraphrase as pp
import validate

FR = {"prompt_lang": "French", "translation": "Louis Segond 1910"}
VERSES = ["JHN.14.6"]
RULES = pp.load_rules()
GEN, VER = "deepseek/gen-model", "mistralai/ver-model"

# Short excerpt (13 words, <= free_max_words=20): all three styles are generated.
EXCERPT_SHORT = "Jésus lui dit : Je suis le chemin, la vérité et la vie."
# Long excerpt (21 words, > free_max_words=20): only close and condensed are generated.
EXCERPT_LONG = "Jésus lui dit : Je suis le chemin, la vérité, et la vie. Nul ne vient au Père que par moi."
EXCERPT = EXCERPT_SHORT   # default for most tests

CLOSE = "Jésus dit qu'il est le chemin, la vérité et la vie."           # 12 words
CONDENSED = "Jésus est le seul chemin vers le Père."                    # 8 words
FREE = "Par Jésus seul on accède au chemin, à la vérité et à la vie."   # 13 words

CLOSE_LONG = "Jésus déclare qu'il est le chemin, la vérité et la vie, et que nul ne va au Père sans lui."
CONDENSED_LONG = "Jésus affirme qu'il est le seul chemin vers le Père."


def gen_answer(close=CLOSE, condensed=CONDENSED, free=FREE, genre="discourse"):
    return json.dumps({"genre": genre, "candidates": {"close": close, "condensed": condensed, "free": free}},
                      ensure_ascii=False)


def gen_answer_long(close=CLOSE_LONG, condensed=CONDENSED_LONG, genre="discourse"):
    return json.dumps({"genre": genre, "candidates": {"close": close, "condensed": condensed}},
                      ensure_ascii=False)


def score(fidelity=5, completeness=4, issues=()):
    return {"fidelity": fidelity, "completeness": completeness, "issues": list(issues)}


class Gen:
    """Fake generator: returns the raw answers in turn and records the prompts."""

    def __init__(self, *raws):
        self.raws, self.prompts = list(raws), []

    def __call__(self, system, user):
        self.prompts.append((system, user))
        return self.raws.pop(0) if self.raws else None


class Ver(Gen):
    """Fake verifier: `by_style` maps a style to its score; it reads the letters from the prompt it receives.

    text_to_style: explicit {text: style} map used to resolve labels; defaults to the 3-style map.
    """

    def __init__(self, by_style=None, raws=(), text_to_style=None):
        super().__init__(*raws)
        self.by_style = by_style
        self.text_to_style = text_to_style or {CLOSE: "close", CONDENSED: "condensed", FREE: "free"}

    def __call__(self, system, user):
        self.prompts.append((system, user))
        if self.raws:
            return self.raws.pop(0)
        out = {}
        block = user.split("Candidates:\n", 1)[1].split("\n\n", 1)[0]
        for line in block.splitlines():
            label, text = line.split(": ", 1)
            style = self.text_to_style.get(text)
            out[label] = (self.by_style or {}).get(style, score())
        return json.dumps(out)


def run(gen, ver, tmp, role=None, excerpt=EXCERPT, gen_model=GEN, ver_model=VER):
    calls = {"paraphrase_generation": (gen, gen_model), "paraphrase_verification": (ver, ver_model)}
    return pp.build_paraphrase(excerpt, VERSES, "fr", FR, calls, tmp, RULES, role)


def assert_valid(result, excerpt=EXCERPT):
    assert validate.check_paraphrase(result["paraphrase"], excerpt) == []


# --- rules ---

def test_rules_load_and_drop_words_shared_by_languages():
    assert RULES["min_fidelity"] == 4
    assert "a" not in RULES["markers"]["fr"] and "a" not in RULES["markers"]["en"]
    assert "le" in RULES["markers"]["fr"] and "the" in RULES["markers"]["en"]


@pytest.mark.parametrize("content", ["min_fidelity: 9\nlanguage_markers: {fr: [le]}",
                                     "min_fidelity: 4\nlanguage_markers: {fr: []}",
                                     "min_fidelity: 4"])
def test_bad_rules_are_refused(tmp_path, content):
    f = tmp_path / "r.yml"
    f.write_text(content, encoding="utf-8")
    with pytest.raises(pp.RulesError):
        pp.load_rules(f)


# --- generation format ---

@pytest.mark.parametrize("raw,fragment", [
    ("nothing", "not a JSON object"),
    ("{broken", "not a JSON object"),
    ('{"candidates": {}}', "exactly genre and candidates"),
    (gen_answer(genre="poem"), "genre must be one of"),
    (json.dumps({"genre": "discourse", "candidates": {"close": "a", "condensed": "b"}}), "exactly close"),
    (json.dumps({"genre": "discourse", "candidates": {"close": "a", "condensed": "b", "free": 3}}), "as strings"),
    (json.dumps({"genre": "discourse", "candidates": {"close": "a", "condensed": "b", "free": "c", "x": "d"}}), "exactly close"),
])
def test_generation_format_is_checked(raw, fragment):
    answer, problem = pp.check_generation(raw)
    assert answer is None and fragment in problem


def test_generation_accepts_text_around_the_json():
    answer, problem = pp.check_generation("Voici :\n" + gen_answer() + "\nFin")
    assert problem is None and answer["candidates"]["close"] == CLOSE


def test_generation_format_two_styles():
    answer, problem = pp.check_generation(gen_answer_long(), ("close", "condensed"))
    assert problem is None and set(answer["candidates"]) == {"close", "condensed"}
    _, prob = pp.check_generation(gen_answer(), ("close", "condensed"))
    assert prob is not None and "exactly close, condensed" in prob


def test_generation_is_retried_once_with_the_reason(tmp_path):
    gen = Gen("garbage", gen_answer())
    res = run(gen, Ver(), tmp_path)
    assert len(gen.prompts) == 2 and "previous answer rejected" in gen.prompts[1][1]
    assert res["paraphrase"]["text"] is not None


def test_generation_failing_twice_gives_null_and_review(tmp_path):
    gen, ver = Gen("garbage", "garbage again"), Ver()
    res = run(gen, ver, tmp_path)
    p = res["paraphrase"]
    assert p["text"] is None and p["reason"] == "no_faithful_version" and p["history"] == []
    assert pp.review_required(res["flags"]) and "generation_failed" in res["flags"]
    assert ver.prompts == []          # nothing to verify, no second model call
    assert_valid(res)


def test_the_generation_prompt_states_the_rules_and_the_word_limit(tmp_path):
    gen = Gen(gen_answer())
    run(gen, Ver(), tmp_path)
    system, user = gen.prompts[0]
    assert "present tense" in system and "NO information" in system and "use at most 11 words" in system
    assert all(s in system for s in pp.STYLES) and EXCERPT in user


def test_long_excerpt_excludes_free_style(tmp_path):
    gen = Gen(gen_answer_long())
    ver = Ver(text_to_style={CLOSE_LONG: "close", CONDENSED_LONG: "condensed"})
    res = run(gen, ver, tmp_path, excerpt=EXCERPT_LONG)
    system = gen.prompts[0][0]
    styles_section = system.split("Styles - ", 1)[1]
    assert "free" not in styles_section   # free style rule absent from Styles section
    assert "Write 2 candidates" in system
    assert [h["style"] for h in res["paraphrase"]["history"]] == ["close", "condensed"]


# --- code checks ---

def test_code_checks():
    ok = pp.code_checks(CLOSE, EXCERPT, "fr", RULES)
    assert ok == {"non_empty": True, "not_longer_than_excerpt": True, "target_language": True, "tense_present": True}
    assert pp.code_checks("  ", EXCERPT, "fr", RULES)["non_empty"] is False
    assert pp.code_checks(EXCERPT + " et encore un mot", EXCERPT, "fr", RULES)["not_longer_than_excerpt"] is False
    assert pp.code_checks("Jesus says that he is the way and the truth.", EXCERPT, "fr", RULES)["target_language"] is False
    assert pp.code_checks("Il vint à Jérusalem.", EXCERPT, "fr", RULES)["tense_present"] is False
    assert pp.code_checks("Il vient à Jérusalem.", EXCERPT, "fr", RULES)["tense_present"] is True
    assert pp.code_checks("Ils ne l'ont pas reconnu.", EXCERPT, "fr", RULES)["tense_present"] is True
    assert pp.code_checks("D'autres travaillaient dans ce champ.", EXCERPT, "fr", RULES)["tense_present"] is False
    assert pp.code_checks("Il fait la vérité.", EXCERPT, "fr", RULES)["tense_present"] is True
    assert pp.code_checks("tense check skipped for en", EXCERPT, "en", RULES)["tense_present"] is None


def test_a_paraphrase_as_long_as_the_excerpt_passes():
    assert pp.code_checks(EXCERPT, EXCERPT, "fr", RULES)["not_longer_than_excerpt"] is True


def test_language_not_configured_is_unchecked():
    assert pp.language_check("das ist gut", "de", RULES["markers"]) is None
    assert pp.language_check("Amen", "fr", RULES["markers"]) is True    # no marker at all: not clearly another language


# --- verification ---

def test_verification_format_is_checked():
    good = json.dumps({"A": score(), "B": score(3, 2, ["addition"]), "C": score()})
    scores, problem = pp.check_verification(good, ["A", "B", "C"])
    assert problem is None and scores["B"]["issues"] == ["addition"]
    for raw, fragment in [("x", "not a JSON"), (json.dumps({"A": score()}), "exactly the keys"),
                          (json.dumps({"A": score(6), "B": score(), "C": score()}), "integer from 1 to 5"),
                          (json.dumps({"A": score(issues=["bad"]), "B": score(), "C": score()}), "list of"),
                          (json.dumps({"A": {"fidelity": 5}, "B": score(), "C": score()}), "exactly fidelity"),
                          (json.dumps({"A": score(True), "B": score(), "C": score()}), "integer from 1 to 5")]:
        assert pp.check_verification(raw, ["A", "B", "C"])[0] is None
        assert fragment in pp.check_verification(raw, ["A", "B", "C"])[1]


def test_the_verifier_sees_shuffled_neutral_letters_and_no_style(tmp_path):
    ver = Ver()
    run(Gen(gen_answer()), ver, tmp_path)
    system, user = ver.prompts[0]
    assert all(s not in user for s in pp.STYLES)
    block = user.split("Candidates:\n", 1)[1]
    assert [line.split(": ", 1)[0] for line in block.splitlines()] == ["A", "B", "C"]
    assert EXCERPT in user


def test_the_verifier_sees_two_labels_for_long_excerpt(tmp_path):
    ver = Ver(text_to_style={CLOSE_LONG: "close", CONDENSED_LONG: "condensed"})
    run(Gen(gen_answer_long()), ver, tmp_path, excerpt=EXCERPT_LONG)
    block = ver.prompts[0][1].split("Candidates:\n", 1)[1]
    assert [line.split(": ", 1)[0] for line in block.splitlines()] == ["A", "B"]


def test_shuffle_is_reproducible_and_covers_all_styles():
    seed = pp.shuffle_seed(VERSES, "fr", [CLOSE, CONDENSED, FREE])
    a, b = pp.shuffled_labels(list(pp.STYLES), seed), pp.shuffled_labels(list(pp.STYLES), seed)
    assert a == b and sorted(s for _, s in a) == sorted(pp.STYLES) and [l for l, _ in a] == ["A", "B", "C"]
    orders = {tuple(s for _, s in pp.shuffled_labels(list(pp.STYLES), n)) for n in range(40)}
    assert len(orders) > 1


def test_verification_is_retried_once(tmp_path):
    ver = Ver(raws=["nonsense"])      # first answer invalid, then the fake answers properly
    res = run(Gen(gen_answer()), ver, tmp_path)
    assert len(ver.prompts) == 2 and "previous answer rejected" in ver.prompts[1][1]
    assert res["paraphrase"]["text"] is not None


def test_verification_failing_gives_null_and_review(tmp_path):
    res = run(Gen(gen_answer()), Ver(raws=["x", "y"]), tmp_path)
    p = res["paraphrase"]
    assert p["text"] is None and p["reason"] == "no_faithful_version"
    assert "verification_failed" in res["flags"] and pp.review_required(res["flags"])
    assert all(h["verification"]["verdict"] == "not_verified" for h in p["history"])
    assert_valid(res)


# --- arbitration ---

def hist(style, fidelity=5, completeness=4, issues=(), words=5, checks=None, verdict="pass", attempt=None):
    return {"attempt": attempt or pp.STYLES.index(style) + 1, "style": style, "text": " ".join(["mot"] * words),
            "code_checks": checks or {"non_empty": True, "not_longer_than_excerpt": True, "target_language": True, "tense_present": True},
            "verification": {"verdict": verdict, "fidelity": fidelity, "completeness": completeness,
                             "issues": list(issues)}}


def test_best_sum_wins():
    n, _ = pp.arbitrate([hist("close", 5, 3), hist("condensed", 5, 5), hist("free", 4, 4)], 4)
    assert n == 2


def test_tie_goes_to_the_shortest_then_to_close():
    assert pp.arbitrate([hist("close", words=8), hist("condensed", words=4), hist("free", words=6)], 4)[0] == 2
    assert pp.arbitrate([hist("close", words=5), hist("condensed", words=5), hist("free", words=5)], 4)[0] == 1
    assert pp.arbitrate([hist("condensed", words=5), hist("free", words=5)], 4)[0] == 2


def test_failed_check_problem_low_fidelity_and_unverified_are_dropped():
    bad = {"non_empty": True, "not_longer_than_excerpt": False, "target_language": True, "tense_present": True}
    n, _ = pp.arbitrate([hist("close", 5, 5, checks=bad), hist("condensed", 5, 5, ["addition"], verdict="fail"),
                         hist("free", 3, 5)], 4)
    assert n is None
    n, reason = pp.arbitrate([hist("close", 5, 5, checks=bad), hist("condensed", 5, 2), hist("free", 5, 5,
                                                                                            verdict="not_verified")], 4)
    assert n == 2 and "condensed selected" in reason


def test_other_issue_alone_is_not_blocking():
    n, reason = pp.arbitrate([hist("close", 4, 4, ["other"], verdict="pass"),
                               hist("condensed", 5, 5, ["addition"], verdict="fail")], 4)
    assert n == 1 and "close selected" in reason


def test_other_issue_with_blocking_issue_is_still_dropped():
    n, _ = pp.arbitrate([hist("close", 4, 4, ["addition", "other"], verdict="fail")], 4)
    assert n is None


def test_unchecked_language_does_not_discard():
    checks = {"non_empty": True, "not_longer_than_excerpt": True, "target_language": None}
    assert pp.arbitrate([hist("close", checks=checks)], 4)[0] == 1


def test_no_candidate_passes_gives_a_reason():
    n, reason = pp.arbitrate([hist("close", 2, 5)], 4)
    assert n is None and "fidelity 2 below 4" in reason


# --- the whole flow ---

def test_selected_candidate_and_full_history(tmp_path):
    ver = Ver({"close": score(5, 3), "condensed": score(5, 5), "free": score(4, 4)})
    res = run(Gen(gen_answer()), ver, tmp_path)
    p = res["paraphrase"]
    assert p["text"] == CONDENSED and p["genre"] == "discourse" and p["genre_by"] == "model"
    assert [h["style"] for h in p["history"]] == list(pp.STYLES)
    assert [h["attempt"] for h in p["history"]] == [1, 2, 3]
    assert p["arbitration"]["selected_attempt"] == 2 and "condensed selected" in p["arbitration"]["reason"]
    assert isinstance(p["arbitration"]["shuffle_seed"], int)
    h = p["history"][1]
    assert h["model"] == GEN and h["prompt_version"] == pp.GENERATION_VERSION
    assert h["verification"]["model"] == VER and h["verification"]["verdict"] == "pass"
    assert h["verification"]["prompt_version"] == pp.VERIFICATION_VERSION
    assert res["flags"] == []
    assert_valid(res)


def test_a_candidate_longer_than_the_excerpt_is_never_selected(tmp_path):
    long_close = " ".join(["mot"] * 40)
    res = run(Gen(gen_answer(close=long_close)), Ver(), tmp_path)
    p = res["paraphrase"]
    assert p["history"][0]["code_checks"]["not_longer_than_excerpt"] is False
    assert p["arbitration"]["selected_attempt"] != 1 and p["text"] != long_close
    assert_valid(res)


def test_empty_candidate_is_not_sent_to_the_verifier(tmp_path):
    ver = Ver()
    res = run(Gen(gen_answer(free="   ")), ver, tmp_path)
    user = ver.prompts[0][1]
    assert user.count("\n") >= 3 and "C: " not in user
    assert res["paraphrase"]["history"][2]["code_checks"]["non_empty"] is False
    assert res["paraphrase"]["history"][2]["verification"]["verdict"] == "not_verified"
    assert_valid(res)


def test_every_candidate_rejected_gives_null_with_the_history_kept(tmp_path):
    ver = Ver({s: score(5, 5, ["addition"]) for s in pp.STYLES})
    res = run(Gen(gen_answer()), ver, tmp_path)
    p = res["paraphrase"]
    assert p["text"] is None and p["reason"] == "no_faithful_version" and len(p["history"]) == 3
    assert p["arbitration"]["selected_attempt"] is None and "no candidate passes" in p["arbitration"]["reason"]
    assert "paraphrase_failed" in res["flags"] and pp.review_required(res["flags"])
    assert_valid(res)


def test_all_candidates_in_the_wrong_language_give_null(tmp_path):
    en = "Jesus says that he is the way."
    res = run(Gen(gen_answer(en, en + " Yes.", en + " Indeed.")), Ver(), tmp_path)
    assert res["paraphrase"]["text"] is None
    assert all(h["code_checks"]["target_language"] is False for h in res["paraphrase"]["history"])


def test_genre_conflicting_with_the_speaker_role_is_flagged(tmp_path):
    res = run(Gen(gen_answer(genre="discourse")), Ver(), tmp_path, role="narrator")
    assert "genre_conflict:narrator:discourse" in res["flags"] and pp.review_required(res["flags"])
    ok = run(Gen(gen_answer(genre="discourse")), Ver(), tmp_path / "b", role="speaker")
    assert ok["flags"] == []
    prayer = run(Gen(gen_answer(genre="prayer")), Ver(), tmp_path / "c", role="speaker")
    assert prayer["flags"] == [] and prayer["paraphrase"]["genre"] == "prayer"


def test_same_family_models_are_refused(tmp_path):
    with pytest.raises(ValueError, match="another family"):
        run(Gen(gen_answer()), Ver(), tmp_path, ver_model="~deepseek/pro-latest")


def test_language_without_markers_is_flagged_but_not_blocked(tmp_path):
    calls = {"paraphrase_generation": (Gen(gen_answer()), GEN), "paraphrase_verification": (Ver(), VER)}
    rules = {"min_fidelity": 4, "markers": {"en": RULES["markers"]["en"]}}
    res = pp.build_paraphrase(EXCERPT, VERSES, "fr", FR, calls, tmp_path, rules)
    assert "language_unchecked" in res["flags"] and res["paraphrase"]["text"] is not None
    assert not pp.review_required(res["flags"])
    assert_valid(res)


def test_cache_avoids_a_second_call(tmp_path):
    gen, ver = Gen(gen_answer()), Ver()
    first = run(gen, ver, tmp_path)
    gen2, ver2 = Gen(), Ver()
    second = run(gen2, ver2, tmp_path)
    assert gen2.prompts == [] and ver2.prompts == []
    assert second["paraphrase"] == first["paraphrase"]


def test_a_new_model_does_not_reuse_the_cache(tmp_path):
    run(Gen(gen_answer()), Ver(), tmp_path)
    gen2 = Gen(gen_answer())
    run(gen2, Ver(), tmp_path, gen_model="deepseek/other-model")
    assert len(gen2.prompts) == 1


def test_short_excerpt_may_be_paraphrased_at_equal_length(tmp_path):
    short = "Dieu est amour."
    res = run(Gen(gen_answer("Dieu est amour.", "Dieu aime.", "L'amour est Dieu.", "discourse")), Ver(), tmp_path,
              excerpt=short)
    assert res["paraphrase"]["text"] is not None
    assert validate.word_count(res["paraphrase"]["text"]) <= 3
    assert_valid(res, short)
