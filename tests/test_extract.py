"""Tests for extract.py (task 8): the pipeline end to end with fake models, checked by validate.py itself.

No network and no model identifier: every model is a fake keyed on the prompt it receives.
"""
import json
from pathlib import Path

import pytest

import context
import datasets as ds
import discovery as dv
import extract
import paraphrase
import provenance
import validate

ROOT = Path(__file__).resolve().parent.parent
LANGS = {k: v for k, v in extract.load_languages().items() if k in ("fr", "en")}
REG = provenance.load_registry()

CORPORA = {
    "fr": {"JHN": {"14": {"5": "Thomas lui dit: Seigneur, nous ne savons où tu vas.",
                          "6": "Jésus lui dit: Je suis le chemin, la vérité, et la vie.",
                          "7": "Si vous me connaissez, vous connaîtrez aussi mon Père."}}},
    "en": {"JHN": {"14": {"5": "Thomas saith unto him, Lord, we know not whither thou goest.",
                          "6": "Jesus saith unto him, I am the way, the truth, and the life.",
                          "7": "If ye had known me, ye should have known my Father also."}}},
}
TOPIC = {"_id": "t", "label": "la vérité", "label_fr": "la vérité", "label_en": "truth", "strongs": ["G225"],
         "patterns_fr": {"verit": r"\bverit"}, "patterns_en": {"truth": r"\btruth"},
         "exclude_phrases_fr": {"amen_formula": r"\ben verite\b"},
         "extra_instructions_fr": "Nuance fr."}
PARA = {
    "fr": {"close": "Jésus déclare qu'il est le chemin, la vérité et la vie, et que connaître Jésus, c'est connaître le Père.",
           "condensed": "Jésus affirme qu'il est le chemin vers le Père.",
           "free": "Connaître Jésus, qui est la voie, la vérité et la vie, c'est connaître le Père."},
    "en": {"close": "Jesus declares that he is the way, the truth and the life, and that knowing Jesus means knowing the Father.",
           "condensed": "Jesus says he is the only way to the Father.",
           "free": "Whoever knows Jesus, the way, the truth and the life, knows the Father."},
}
KEEP = json.dumps({"relevant": True, "cited_verses": ["JHN.14.6"], "start": "JHN.14.6", "end": "JHN.14.7"})
DROP = json.dumps({"relevant": False, "cited_verses": [], "start": None, "end": None})


def fake_model(relevance=KEEP):
    """One fake for every role: it recognises the prompt, and the language from the prompt itself."""
    def call(system, user):
        lang = "fr" if "French" in system else "en"
        if "You judge whether" in system:
            return relevance
        if "literary context" in system:
            return json.dumps({"text": "Jésus répond à Thomas." if lang == "fr" else "Jesus answers Thomas.",
                               "cited_verses": ["JHN.14.5"], "confidence": "high"}, ensure_ascii=False)
        if "You paraphrase" in system:
            return json.dumps({"genre": "discourse", "candidates": PARA[lang]}, ensure_ascii=False)
        if "You check paraphrases" in system:
            block = user.split("Candidates:\n", 1)[1]
            return json.dumps({line.split(": ", 1)[0]: {"fidelity": 5, "completeness": 4, "issues": []}
                               for line in block.splitlines()})
        label = user.split("\n")[0].removeprefix("Label: ")
        return {"Jesus": "Jésus"}.get(label, label) if lang == "fr" else label
    return call


def calls_for(model):
    return {"speaker": (model, "m/speaker"), "context": (model, "m/context"),
            "paraphrase_generation": (model, "gen-co/model"), "paraphrase_verification": (model, "ver-co/model"),
            "relevance": (model, "m/relevance")}


def shared(speakers=()):
    d = {"theographic": {"events": {}, "places": {}}, "openbible": {}, "acai": {"people": {}, "places": {}},
         "speakers": list(speakers), "anchors": []}
    return {"data": d, "rules": context.load_rules(), "paraphrase_rules": paraphrase.load_rules(), "registry": REG}


JESUS = [{"start": ds.verse_key("JHN.14.6"), "end": ds.verse_key("JHN.14.7"), "speaker": "Jesus", "type": "Dialogue"}]
RULES = dv.load_rules()


@pytest.fixture
def disc(tmp_path):
    d = tmp_path / "byz" / "csv-unicode" / "strongs" / "with-parsing"
    d.mkdir(parents=True)
    (d / "JHN.csv").write_text("14,6,αληθεια 225 {N-NSF}\n", encoding="utf-8")
    return dv.discover(TOPIC, CORPORA, ["JHN"], tmp_path / "byz")


def plan_for(disc, mode, tmp_path, model=None):
    return extract.plan_ranges(disc, disc["candidates"], mode, "fr", LANGS, CORPORA, TOPIC, RULES, JESUS,
                               calls_for(model or fake_model()), tmp_path / "cache", 1)


def produce(disc, plan, mode, tmp_path, model=None):
    return extract.produce(plan, disc, mode, LANGS, CORPORA, shared(JESUS), calls_for(model or fake_model()),
                           tmp_path / "cache", ["JHN"], 1)


# --- model calls over HTTP ---

class Resp:
    def __init__(self, status=200, text="hello"):
        self.status_code, self.text = status, text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return {"choices": [{"message": {"content": self.text}}]}


def test_make_call_posts_the_prompts_to_the_model_and_returns_the_text():
    seen = {}

    def post(url, headers, json, timeout):
        seen.update(url=url, headers=headers, body=json)
        return Resp(text="the answer")
    call = extract.make_call("KEY", "https://example.test/api/", "some/model", post=post)
    assert call("sys", "usr") == "the answer"
    assert seen["url"] == "https://example.test/api/chat/completions"
    assert seen["headers"]["Authorization"] == "Bearer KEY"
    assert seen["body"]["model"] == "some/model" and seen["body"]["max_tokens"] == extract.MAX_TOKENS
    assert seen["body"]["messages"] == [{"role": "system", "content": "sys"}, {"role": "user", "content": "usr"}]
    assert "response_format" not in seen["body"]                  # plain texts and JSON answers share the same call


def test_make_call_waits_and_retries_on_429():
    answers, waits = [Resp(429), Resp(429), Resp(200, "ok")], []
    call = extract.make_call("K", "https://x.test", "m", post=lambda *a, **k: answers.pop(0), sleep=waits.append)
    assert call("s", "u") == "ok" and waits == [5, 10]


def test_make_call_gives_up_after_four_rate_limits_and_returns_none_on_errors():
    waits = []
    call = extract.make_call("K", "https://x.test", "m", post=lambda *a, **k: Resp(429), sleep=waits.append)
    assert call("s", "u") is None and waits == [5, 10, 20, 40]
    assert extract.make_call("K", "https://x.test", "m", post=lambda *a, **k: Resp(500))("s", "u") is None

    def boom(*a, **k):
        raise ConnectionError("down")
    assert extract.make_call("K", "https://x.test", "m", post=boom)("s", "u") is None


def test_build_calls_maps_every_role_to_the_model_of_models_yml():
    roles = {"speaker": "a/1", "context": "a/2", "paraphrase_generation": "a/3", "paraphrase_verification": "b/4",
             "relevance": "a/5", "escalation": "a/6"}
    calls = extract.build_calls(roles, lambda model: f"call-for-{model}")
    assert calls["relevance"] == ("call-for-a/5", "a/5") and calls["paraphrase_verification"][1] == "b/4"
    assert set(calls) == set(extract.CALL_ROLES) and "escalation" not in calls


# --- references ---

@pytest.mark.parametrize("lang, ids, label", [
    ("fr", ["JHN.14.6"], "Jean 14,6"),
    ("fr", ["JHN.14.6", "JHN.14.7", "JHN.14.8"], "Jean 14,6-8"),
    ("fr", ["JHN.14.30", "JHN.15.1", "JHN.15.2"], "Jean 14,30-15,2"),
    ("en", ["JHN.14.6", "JHN.14.7"], "John 14:6-7"),
])
def test_reference_labels(lang, ids, label):
    assert extract.ref_label(lang, LANGS[lang], ids) == label


# --- selection and bounds ---

def test_rules_mode_keeps_every_candidate_and_bounds_it_inside_its_quotation(disc, tmp_path):
    plan = plan_for(disc, "rules", tmp_path)
    assert [r["verses"] for r in plan["ranges"]] == [["JHN.14.6", "JHN.14.7"]]
    assert plan["verdicts"] == {} and plan["not_relevant"] == [] and plan["no_verdict"] == []


def test_model_mode_keeps_what_the_model_judges_relevant_with_its_bounds(disc, tmp_path):
    plan = plan_for(disc, "model", tmp_path)
    assert [r["verses"] for r in plan["ranges"]] == [["JHN.14.6", "JHN.14.7"]]
    v = plan["verdicts"][("JHN", "14", "6")]
    assert v["model"] == "m/relevance" and v["cited_verses"] == ["JHN.14.6"]


def test_model_mode_lists_the_candidates_it_does_not_keep(disc, tmp_path):
    no = plan_for(disc, "model", tmp_path, fake_model(DROP))
    assert no["ranges"] == [] and no["not_relevant"] == disc["candidates"] and no["no_verdict"] == []
    silent = plan_for(disc, "model", tmp_path / "other", fake_model("not json"))
    assert silent["ranges"] == [] and silent["no_verdict"] == disc["candidates"] and silent["not_relevant"] == []


def test_the_verse_that_the_model_judged_cannot_be_a_verse_it_was_not_shown(disc, tmp_path):
    bad = json.dumps({"relevant": True, "cited_verses": ["JHN.14.6"], "start": "JHN.14.6", "end": "JHN.14.9"})
    plan = plan_for(disc, "model", tmp_path, fake_model(bad))
    assert plan["ranges"] == [] and plan["no_verdict"] == disc["candidates"]


# --- the whole entry, in both languages ---

def test_rules_mode_entries_validate_in_both_languages_and_agree_on_neutral_fields(disc, tmp_path):
    plan = plan_for(disc, "rules", tmp_path)
    built = produce(disc, plan, "rules", tmp_path)
    for lang in ("fr", "en"):
        ((entry, errs),) = built[lang]
        assert errs == []
        assert entry["schema_version"] == "2" and entry["language"] == lang
        assert entry["translation"] == LANGS[lang]["version_label"]
        assert entry["excerpt"]["verses"] == ["JHN.14.6", "JHN.14.7"]
        assert entry["excerpt"]["text"] == " ".join(CORPORA[lang]["JHN"]["14"][v] for v in ("6", "7"))
        assert entry["paraphrase"]["text"] and len(entry["paraphrase"]["history"]) == 3
        assert entry["speaker"]["role"] == "speaker" and entry["speaker"]["confidence"] == "medium"
        assert entry["discovery"]["mode"] == "rules"
        assert entry["review"] == {"status": None, "note": None, "flags": entry["review"]["flags"], "required": False}
    fr, en = built["fr"][0][0], built["en"][0][0]
    assert fr["reference"] == {"book": "JHN", "start": "14.6", "end": "14.7", "label": "Jean 14,6-7"}
    assert en["reference"]["label"] == "John 14:6-7"
    assert fr["speaker"]["value"] == "Jésus" and en["speaker"]["value"] == "Jesus"
    assert validate.check_cross_language({"fr": [fr], "en": [en]}) == []


def test_the_entry_records_the_discovery_steps_and_cites_the_concordance(disc, tmp_path):
    built = produce(disc, plan_for(disc, "rules", tmp_path), "rules", tmp_path)
    fr, en = built["fr"][0][0], built["en"][0][0]
    assert [s["step"] for s in fr["discovery"]["steps"]] == ["union", "strongs", "pattern", "exclusion_check"]
    assert [s["step"] for s in en["discovery"]["steps"]] == ["union", "strongs", "pattern"]
    assert fr["discovery"]["steps"][2]["matched"] == "vérité" and en["discovery"]["steps"][2]["matched"] == "truth"
    for entry in (fr, en):
        s = next(s for s in entry["sources"] if s["id"] == "G225")
        assert s == {"id": "G225", "type": "concordance", "dataset": "byztxt", "license": "Unlicense (public domain)"}
        assert {"JHN.14.6", "JHN.14.7", "JHN.14.5"} <= {x["id"] for x in entry["sources"]}


def test_model_mode_entries_carry_the_llm_relevance_step_and_validate(disc, tmp_path):
    plan = plan_for(disc, "model", tmp_path)
    built = produce(disc, plan, "model", tmp_path)
    for lang in ("fr", "en"):
        ((entry, errs),) = built[lang]
        assert errs == [] and entry["discovery"]["mode"] == "model"
        step = entry["discovery"]["steps"][-1]
        assert step == {"step": "llm_relevance", "verse": "JHN.14.6", "model": "m/relevance",
                        "prompt_version": "relevance-1", "verdict": "relevant", "cited_verses": ["JHN.14.6"]}


def test_an_ambiguous_speaker_puts_the_entry_in_review_with_its_flags(disc, tmp_path):
    two = JESUS + [{"start": ds.verse_key("JHN.14.7"), "end": ds.verse_key("JHN.14.7"), "speaker": "Thomas",
                    "type": "Dialogue"}]
    plan = plan_for(disc, "rules", tmp_path)
    built = extract.produce(plan, disc, "rules", LANGS, CORPORA, shared(two), calls_for(fake_model()),
                            tmp_path / "cache", ["JHN"], 1)
    entry = built["fr"][0][0]
    assert entry["speaker"] == {"value": None, "reason": "not_identified"}
    assert entry["review"]["required"] is True and "speaker_ambiguous" in entry["review"]["flags"]


def test_a_failing_model_does_not_stop_the_batch_and_the_entry_stays_valid(disc, tmp_path):
    down = lambda system, user: None                                       # noqa: E731
    built = produce(disc, plan_for(disc, "rules", tmp_path), "rules", tmp_path / "down", down)
    ((entry, errs),) = built["fr"]
    assert errs == [] and entry["paraphrase"]["text"] is None and entry["paraphrase"]["reason"] == "no_faithful_version"
    assert entry["review"]["required"] is True


def test_an_exception_while_building_one_entry_is_reported_not_raised(disc, tmp_path, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("bug")
    monkeypatch.setattr(extract, "build_entry", boom)
    built = produce(disc, plan_for(disc, "rules", tmp_path), "rules", tmp_path)
    assert built["fr"][0][0] is None and built["fr"][0][1] == ["exception: RuntimeError: bug"]


# --- intersection and report ---

def test_a_range_is_kept_only_when_valid_in_every_language():
    plan = {"ranges": [{}, {}, {}]}
    built = {"fr": [("e", []), ("e", ["excerpt.text: not_exact_concatenation"]), ("e", [])],
             "en": [("e", []), ("e", []), (None, ["exception: X"])]}
    kept, dropped = extract.intersect(plan, built)
    assert kept == [0] and dropped == {1: ["fr: excerpt.text: not_exact_concatenation"], 2: ["en: exception: X"]}


def report_info(disc, plan, built, mode, tmp_path):
    kept, dropped = extract.intersect(plan, built)
    return {"topic": TOPIC, "mode": mode, "langs": LANGS, "pivot": "fr", "disc": disc,
            "summary": dv.summarize(disc, disc["candidates"]), "candidates": disc["candidates"], "absent": [],
            "strongs_used": True, "versification": {}, "plan": plan, "rules": RULES, "built": built, "kept": kept,
            "dropped": dropped, "cross_errors": [], "price_report": "## Price check\n- Result: OK\n"}


def test_the_report_lists_routes_excerpts_and_review(disc, tmp_path):
    plan = plan_for(disc, "model", tmp_path)
    built = produce(disc, plan, "model", tmp_path)
    text = extract.build_report(report_info(disc, plan, built, "model", tmp_path))
    for needle in ("# Report: la vérité", "## Price check", "- Mode: model", '- Labels: fr="la vérité", en="truth"',
                   "- Found by both routes: 1", "TVTMS has a rule for 0 candidate verse(s)",
                   "## Relevance judgement (pivot language: fr)", "- Relevant: 1", "- Excerpts: 1",
                   "- kept in all languages: 1", "neutral fields identical in every language file"):
        assert needle in text


def test_the_report_names_what_was_not_kept_and_what_failed(disc, tmp_path):
    plan = plan_for(disc, "model", tmp_path, fake_model(DROP))
    built = produce(disc, plan, "model", tmp_path)
    info = report_info(disc, plan, built, "model", tmp_path)
    info.update(cross_errors=["cross:en[0].verses: differs_from_fr"], versification=None)
    text = extract.build_report(info)
    assert "### Not relevant\n  - JHN.14.6" in text and "TVTMS not found" in text
    assert "## Cross-language check: FAILED" in text and "cross:en[0].verses" in text


# --- the command, on the real data (skipped when the datasets are not fetched) ---

needs_data = pytest.mark.skipif(
    not all((ROOT / p).exists() for p in ("data/fr.json", "data/en.json", "tmp/byztxt")),
    reason="corpora and byztxt not fetched (scripts/fetch_sources.py, scripts/build_corpus.py)")


@needs_data
def test_dry_run_on_the_real_topic_lists_candidates_with_their_routes(capsys):
    assert extract.main(["--topic", "verite", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "Candidates:" in out and "JHN.14.6" in out and "strongs+pattern:fr+pattern:en" in out
    assert "[single route]" in out and "excerpt JHN.14.6" in out


@needs_data
def test_dry_run_in_model_mode_makes_no_model_call(capsys, monkeypatch):
    monkeypatch.setattr(extract, "make_call", lambda *a, **k: pytest.fail("a model call was prepared"))
    assert extract.main(["--topic", "verite", "--dry-run", "--mode", "model", "--limit", "5"]) == 0


# --- the workflow ---

def test_workflow_fetches_the_datasets_before_extraction_and_offers_the_discovery_mode():
    import yaml
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "extract.yml").read_text(encoding="utf-8"))
    inputs = wf[True]["workflow_dispatch"]["inputs"]
    assert inputs["mode"]["options"] == ["rules", "model"] and inputs["mode"]["default"] == "rules"
    assert "check_links" not in inputs                           # schema 2 has no link field
    runs = [s.get("run", "") for s in wf["jobs"]["run"]["steps"]]
    fetch = next(i for i, r in enumerate(runs) if "fetch_sources.py --fetch" in r)
    run = next(i for i, r in enumerate(runs) if "python extract.py" in r)
    assert fetch < run and "--mode" in runs[run] and "--check-links" not in runs[run]


# --- shared cache files written by several threads ---

def test_a_shared_cache_file_is_written_atomically(tmp_path):
    import localize
    target = tmp_path / "speaker-name" / "fr" / "jesus-12345678.v.m.json"
    localize.write_atomic(target, '{"text": "Jésus"}')
    localize.write_atomic(target, '{"text": "Jésus 2"}')
    assert json.loads(target.read_text(encoding="utf-8")) == {"text": "Jésus 2"}
    assert [p.name for p in target.parent.iterdir()] == [target.name]          # no temporary file is left behind
