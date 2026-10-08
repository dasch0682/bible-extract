"""Tests for validate.py guardrails (schema 2)."""
import copy

from validate import (
    norm, build_link, word_count, check_excerpt, check_paraphrase, check_speaker,
    check_context, check_discovery, check_sources, validate_entry, check_cross_language,
)

CORPUS = {
    "JHN": {
        "14": {
            "5": "Thomas lui dit: Seigneur, nous ne savons où tu vas; comment pourrions-nous connaître le chemin?",
            "6": "Jésus lui dit: Je suis le chemin, la vérité, et la vie.",
            "7": "Si vous me connaissiez, vous connaîtriez aussi mon Père.",
        },
        "15": {"1": "Je suis le vrai cep, et mon Père est le vigneron."},
    },
    "MAT": {"5": {"3": "Heureux les pauvres en esprit."}},
}
KNOWN = {"lsg1910", "strongs-numbers", "theographic", "openbible"}
PARA = "Jésus se présente comme la voie vers Dieu."


def make_entry(verses=("JHN.14.6",)):
    """A fully valid schema-2 entry for the given contiguous verses."""
    texts = []
    for v in verses:
        book, c, n = v.split(".")
        texts.append(CORPUS[book][c][n])
    sources = [{"id": v, "type": "bible_text", "dataset": "lsg1910", "license": "public domain"}
               for v in verses]
    sources += [
        {"id": "G225", "type": "concordance", "dataset": "strongs-numbers", "license": "public domain"},
        {"id": "theographic", "type": "dataset", "dataset": "theographic", "license": "CC BY 4.0"},
        {"id": "openbible", "type": "dataset", "dataset": "openbible", "license": "CC BY 4.0"},
    ]
    return {
        "schema_version": "2",
        "language": "fr",
        "translation": "LSG 1910",
        "reference": {"book": "JHN", "start": "14.6", "end": "14.6", "label": "Jean 14,6"},
        "excerpt": {"text": " ".join(texts), "verses": list(verses)},
        "paraphrase": {
            "text": PARA,
            "genre": "discourse",
            "history": [{
                "attempt": 1, "style": "close", "text": PARA,
                "model": "vendor/gen", "prompt_version": "1",
                "code_checks": {"not_longer_than_excerpt": True},
                "verification": {"model": "other/ver", "verdict": "pass",
                                 "fidelity": 5, "completeness": 4, "issues": []},
            }],
            "arbitration": {"selected_attempt": 1, "reason": "best score"},
        },
        "speaker": {"value": "Jésus", "role": "speaker", "confidence": "high", "sources": [verses[0]]},
        "context": {
            "literary": {"text": "Réponse à Thomas.", "confidence": "high", "sources": [verses[0]]},
            "temporal": [{
                "kind": "scholarly_estimate", "label": "dernière semaine",
                "date_range": {"from": 28, "to": 30, "era": "CE"},
                "confidence": "probable", "sources": ["theographic"],
            }],
            "places": [{"name": "Jérusalem", "place_id": "jerusalem",
                        "confidence": "probable", "sources": ["openbible"]}],
        },
        "discovery": {
            "mode": "rules",
            "steps": [
                {"step": "strongs", "numbers": ["G225"], "verse": verses[0]},
                {"step": "pattern", "rule": "verit", "matched": "vérité"},
            ],
        },
        "review": {"status": None, "note": None},
        "sources": sources,
    }


def errs(entry):
    return validate_entry(entry, CORPUS, KNOWN)


# --- norm ---

def test_norm_strips_accents():
    assert norm("vérité") == "verite"

def test_norm_smart_quote():
    assert norm("l’homme") == "l'homme"

def test_norm_nbsp():
    assert norm("a b") == "a b"

def test_norm_lowercase():
    assert norm("Jésus") == "jesus"

def test_norm_collapses_spaces():
    assert norm("a  b   c") == "a b c"


# --- whole entry ---

def test_valid_entry_passes():
    assert errs(make_entry()) == []

def test_valid_multi_verse_entry_passes():
    assert errs(make_entry(("JHN.14.5", "JHN.14.6"))) == []

def test_not_an_object():
    assert errs(None) == ["entry: not_an_object"]

def test_wrong_schema_version():
    e = make_entry()
    e["schema_version"] = "1"
    assert "schema_version: must_be_2" in errs(e)

def test_no_dataset_check_without_known_datasets():
    e = make_entry()
    e["sources"][-1]["dataset"] = "mystery"
    assert "sources[3].dataset: unknown_dataset" in errs(e)
    assert validate_entry(e, CORPUS) == []


# --- excerpt ---

def test_excerpt_has_no_word_limit():
    e = make_entry(("JHN.14.5",))
    assert word_count(e["excerpt"]["text"]) > 14
    assert errs(e) == []

def test_excerpt_contiguous_across_chapters():
    verses = ["JHN.14.7", "JHN.15.1"]
    text = CORPUS["JHN"]["14"]["7"] + " " + CORPUS["JHN"]["15"]["1"]
    assert check_excerpt({"text": text, "verses": verses}, CORPUS) == []

def test_excerpt_not_contiguous():
    verses = ["JHN.14.5", "JHN.14.7"]
    text = CORPUS["JHN"]["14"]["5"] + " " + CORPUS["JHN"]["14"]["7"]
    assert "excerpt.verses: not_contiguous" in check_excerpt({"text": text, "verses": verses}, CORPUS)

def test_excerpt_verses_out_of_order():
    verses = ["JHN.14.6", "JHN.14.5"]
    text = CORPUS["JHN"]["14"]["6"] + " " + CORPUS["JHN"]["14"]["5"]
    assert "excerpt.verses: not_contiguous" in check_excerpt({"text": text, "verses": verses}, CORPUS)

def test_excerpt_not_same_book():
    out = check_excerpt({"text": "x", "verses": ["JHN.14.6", "MAT.5.3"]}, CORPUS)
    assert out == ["excerpt.verses: not_same_book"]

def test_excerpt_verse_not_in_corpus():
    out = check_excerpt({"text": "x", "verses": ["JHN.14.99"]}, CORPUS)
    assert out == ["excerpt.verses: not_in_corpus"]

def test_excerpt_malformed_verse_id():
    assert check_excerpt({"text": "x", "verses": ["Jean 14,6"]}, CORPUS) == ["excerpt.verses: malformed_id"]

def test_excerpt_empty_verses():
    assert check_excerpt({"text": "x", "verses": []}, CORPUS) == ["excerpt.verses: empty"]

def test_excerpt_missing():
    assert check_excerpt(None, CORPUS) == ["excerpt: missing"]

def test_excerpt_partial_verse_rejected():
    out = check_excerpt({"text": "Je suis le chemin, la vérité, et la vie.", "verses": ["JHN.14.6"]}, CORPUS)
    assert out == ["excerpt.text: not_exact_concatenation"]

def test_excerpt_empty_text_rejected():
    out = check_excerpt({"text": "  ", "verses": ["JHN.14.6"]}, CORPUS)
    assert out == ["excerpt.text: empty"]

def test_excerpt_whitespace_is_normalised():
    text = "Jésus  lui dit: Je suis le chemin, la vérité, et la vie."
    assert check_excerpt({"text": text, "verses": ["JHN.14.6"]}, CORPUS) == []

def test_excerpt_typographic_variant_rejected():
    corpus = {"JHN": {"1": {"1": "C’est la vérité."}}}
    out = check_excerpt({"text": "C'est la vérité.", "verses": ["JHN.1.1"]}, corpus)
    assert out == ["excerpt.text: not_exact_concatenation"]


# --- paraphrase ---

def test_paraphrase_equal_length_accepted():
    e = make_entry(("JHN.15.1",))
    words = word_count(e["excerpt"]["text"])
    text = " ".join(["mot"] * words)
    e["paraphrase"]["text"] = text
    e["paraphrase"]["history"][0]["text"] = text
    assert check_paraphrase(e["paraphrase"], e["excerpt"]["text"]) == []

def test_paraphrase_longer_than_excerpt_rejected():
    e = make_entry(("JHN.15.1",))
    text = " ".join(["mot"] * (word_count(e["excerpt"]["text"]) + 3))
    e["paraphrase"]["text"] = text
    e["paraphrase"]["history"][0]["text"] = text
    assert "paraphrase.text: longer_than_excerpt" in check_paraphrase(e["paraphrase"], e["excerpt"]["text"])


def test_paraphrase_longer_by_two_accepted():
    e = make_entry(("JHN.15.1",))
    text = " ".join(["mot"] * (word_count(e["excerpt"]["text"]) + 2))
    e["paraphrase"]["text"] = text
    e["paraphrase"]["history"][0]["text"] = text
    assert "paraphrase.text: longer_than_excerpt" not in check_paraphrase(e["paraphrase"], e["excerpt"]["text"])

def test_paraphrase_null_with_reason_accepted():
    p = {"text": None, "reason": "no_faithful_version"}
    assert check_paraphrase(p, "x") == []

def test_paraphrase_null_without_reason_rejected():
    assert check_paraphrase({"text": None}, "x") == ["paraphrase.reason: missing_or_unknown"]

def test_paraphrase_null_unknown_reason_rejected():
    assert check_paraphrase({"text": None, "reason": "because"}, "x") == ["paraphrase.reason: missing_or_unknown"]

def test_paraphrase_empty_text_rejected():
    assert check_paraphrase({"text": " "}, "x") == ["paraphrase.text: empty"]

def test_paraphrase_unknown_genre():
    e = make_entry()
    e["paraphrase"]["genre"] = "poem"
    assert "paraphrase.genre: unknown" in check_paraphrase(e["paraphrase"], e["excerpt"]["text"])

def test_paraphrase_history_required():
    e = make_entry()
    e["paraphrase"]["history"] = []
    assert "paraphrase.history: empty" in check_paraphrase(e["paraphrase"], e["excerpt"]["text"])

def test_paraphrase_history_item_incomplete():
    e = make_entry()
    del e["paraphrase"]["history"][0]["prompt_version"]
    assert "paraphrase.history[0]: incomplete" in check_paraphrase(e["paraphrase"], e["excerpt"]["text"])

def test_paraphrase_arbitration_required():
    e = make_entry()
    e["paraphrase"]["arbitration"] = {"selected_attempt": 1}
    assert "paraphrase.arbitration: incomplete" in check_paraphrase(e["paraphrase"], e["excerpt"]["text"])

def test_paraphrase_selected_attempt_must_exist():
    e = make_entry()
    e["paraphrase"]["arbitration"]["selected_attempt"] = 2
    out = check_paraphrase(e["paraphrase"], e["excerpt"]["text"])
    assert "paraphrase.arbitration: selected_attempt_not_in_history" in out

def test_paraphrase_selected_text_must_match():
    e = make_entry()
    e["paraphrase"]["history"][0]["text"] = "Autre texte."
    out = check_paraphrase(e["paraphrase"], e["excerpt"]["text"])
    assert "paraphrase.arbitration: selected_text_differs" in out


# --- speaker ---

def test_speaker_valid():
    assert check_speaker(make_entry()["speaker"]) == []

def test_speaker_narrator_valid():
    s = make_entry()["speaker"]
    s["role"] = "narrator"
    assert check_speaker(s) == []

def test_speaker_null_with_reason():
    assert check_speaker({"value": None, "reason": "not_identified"}) == []

def test_speaker_null_without_reason():
    assert check_speaker({"value": None}) == ["speaker.reason: must_be_not_identified"]

def test_speaker_null_with_other_reason():
    assert check_speaker({"value": None, "reason": "no_source"}) == ["speaker.reason: must_be_not_identified"]

def test_speaker_unknown_role():
    s = make_entry()["speaker"]
    s["role"] = "witness"
    assert "speaker.role: unknown" in check_speaker(s)

def test_speaker_invalid_confidence():
    s = make_entry()["speaker"]
    s["confidence"] = "certain"
    assert "speaker.confidence: invalid" in check_speaker(s)

def test_speaker_needs_sources():
    s = make_entry()["speaker"]
    s["sources"] = []
    assert "speaker.sources: missing" in check_speaker(s)


# --- context ---

def test_context_valid():
    assert check_context(make_entry()["context"]) == []

def test_literary_null_with_reason():
    ctx = make_entry()["context"]
    ctx["literary"] = {"text": None, "reason": "no_source"}
    assert check_context(ctx) == []

def test_literary_invalid_confidence():
    ctx = make_entry()["context"]
    ctx["literary"]["confidence"] = "probable"
    assert "context.literary.confidence: invalid" in check_context(ctx)

def test_temporal_invalid_confidence():
    ctx = make_entry()["context"]
    ctx["temporal"][0]["confidence"] = "high"
    assert "context.temporal[0].confidence: invalid" in check_context(ctx)

def test_temporal_needs_sources():
    ctx = make_entry()["context"]
    ctx["temporal"][0]["sources"] = []
    assert "context.temporal[0].sources: missing" in check_context(ctx)

def test_temporal_unknown_kind():
    ctx = make_entry()["context"]
    ctx["temporal"][0]["kind"] = "guess"
    assert "context.temporal[0].kind: unknown" in check_context(ctx)

def test_date_range_null_needs_reason():
    ctx = make_entry()["context"]
    ctx["temporal"][0]["date_range"] = {"from": None, "to": None, "era": "CE"}
    assert "context.temporal[0].date_range.reason: missing_or_unknown" in check_context(ctx)

def test_date_range_null_with_reason():
    ctx = make_entry()["context"]
    ctx["temporal"][0]["date_range"] = {"from": None, "to": None, "era": "CE", "reason": "disputed_no_consensus"}
    ctx["temporal"][0]["confidence"] = "disputed"
    assert check_context(ctx) == []

def test_date_range_from_after_to():
    ctx = make_entry()["context"]
    ctx["temporal"][0]["date_range"] = {"from": 33, "to": 30, "era": "CE"}
    assert "context.temporal[0].date_range: from_after_to" in check_context(ctx)

def test_date_range_unknown_era():
    ctx = make_entry()["context"]
    ctx["temporal"][0]["date_range"]["era"] = "AD"
    assert "context.temporal[0].date_range.era: unknown" in check_context(ctx)

def test_date_range_only_one_bound_rejected():
    ctx = make_entry()["context"]
    ctx["temporal"][0]["date_range"] = {"from": 30, "to": None, "era": "CE"}
    assert "context.temporal[0].date_range: bounds_must_be_positive_years" in check_context(ctx)

def _day_candidate():
    return {"date": "0030-04-07", "method": "calendar_computation",
            "assumptions": ["death on 14 Nisan"], "sources": ["theographic"]}

def test_day_candidate_valid():
    ctx = make_entry()["context"]
    ctx["temporal"][0]["day_candidates"] = [_day_candidate()]
    assert check_context(ctx) == []

def test_day_candidate_needs_assumptions():
    ctx = make_entry()["context"]
    d = _day_candidate()
    d["assumptions"] = []
    ctx["temporal"][0]["day_candidates"] = [d]
    assert "context.temporal[0].day_candidates[0].assumptions: missing" in check_context(ctx)

def test_day_candidate_unknown_method():
    ctx = make_entry()["context"]
    d = _day_candidate()
    d["method"] = "dataset"
    ctx["temporal"][0]["day_candidates"] = [d]
    assert "context.temporal[0].day_candidates[0].method: unknown" in check_context(ctx)

def test_day_candidate_invalid_date():
    ctx = make_entry()["context"]
    d = _day_candidate()
    d["date"] = "7 avril 30"
    ctx["temporal"][0]["day_candidates"] = [d]
    assert "context.temporal[0].day_candidates[0].date: invalid" in check_context(ctx)

def test_place_needs_id():
    ctx = make_entry()["context"]
    ctx["places"][0]["place_id"] = ""
    assert "context.places[0]: incomplete" in check_context(ctx)

def test_place_invalid_confidence():
    ctx = make_entry()["context"]
    ctx["places"][0]["confidence"] = "high"
    assert "context.places[0].confidence: invalid" in check_context(ctx)

def test_place_needs_sources():
    ctx = make_entry()["context"]
    ctx["places"][0]["sources"] = []
    assert "context.places[0].sources: missing" in check_context(ctx)


# --- discovery ---

def test_discovery_valid():
    assert check_discovery(make_entry()["discovery"]) == []

def test_discovery_unknown_mode():
    d = make_entry()["discovery"]
    d["mode"] = "magic"
    assert "discovery.mode: unknown" in check_discovery(d)

def test_discovery_steps_required():
    d = make_entry()["discovery"]
    d["steps"] = []
    assert "discovery.steps: empty_or_malformed" in check_discovery(d)

def test_discovery_model_mode_needs_llm_relevance():
    d = make_entry()["discovery"]
    d["mode"] = "model"
    assert "discovery.steps: llm_relevance_missing_in_model_mode" in check_discovery(d)
    d["steps"].append({"step": "llm_relevance", "model": "m", "verdict": "relevant", "verses": ["JHN.14.6"]})
    assert check_discovery(d) == []


# --- sources ---

def test_sources_cited_but_not_listed():
    e = make_entry()
    e["speaker"]["sources"] = ["JHN.14.5"]
    assert "sources: cited_but_not_listed:JHN.14.5" in check_sources(e, CORPUS, KNOWN)

def test_sources_placeholder_license_rejected():
    e = make_entry()
    e["sources"][-1]["license"] = "<à vérifier>"
    assert "sources[3].license: missing_or_placeholder" in check_sources(e, CORPUS, KNOWN)

def test_sources_missing_license_rejected():
    e = make_entry()
    del e["sources"][0]["license"]
    assert "sources[0].license: missing_or_placeholder" in check_sources(e, CORPUS, KNOWN)

def test_sources_verse_must_be_in_corpus():
    e = make_entry()
    e["sources"].append({"id": "JHN.14.99", "type": "bible_text", "dataset": "lsg1910", "license": "public domain"})
    assert "sources[4]: verse_not_in_corpus" in check_sources(e, CORPUS, KNOWN)

def test_sources_empty():
    e = make_entry()
    e["sources"] = []
    assert check_sources(e, CORPUS, KNOWN) == ["sources: empty"]

def test_excerpt_verses_must_be_listed_as_sources():
    e = make_entry(("JHN.14.5", "JHN.14.6"))
    e["sources"] = [s for s in e["sources"] if s["id"] != "JHN.14.5"]
    assert "sources: cited_but_not_listed:JHN.14.5" in errs(e)


# --- cross-language ---

def _en(entry):
    """The same entry in another language: only text fields change."""
    other = copy.deepcopy(entry)
    other["language"] = "en"
    other["excerpt"]["text"] = "Jesus saith unto him, I am the way, the truth, and the life."
    other["speaker"]["value"] = "Jesus"
    other["context"]["literary"]["text"] = "Answer to Thomas."
    other["discovery"]["steps"][1] = {"step": "pattern", "rule": "truth", "matched": "truth"}
    return other

def test_cross_language_ok_when_only_text_differs():
    fr = [make_entry()]
    assert check_cross_language({"fr": fr, "en": [_en(fr[0])]}) == []

def test_cross_language_single_file_is_ok():
    assert check_cross_language({"fr": [make_entry()]}) == []

def test_cross_language_entry_count_differs():
    fr = [make_entry(), make_entry(("JHN.14.5",))]
    assert check_cross_language({"fr": fr, "en": [_en(fr[0])]}) == ["cross:en: entry_count_differs_from_fr"]

def test_cross_language_verses_differ():
    fr = make_entry()
    en = _en(fr)
    en["excerpt"]["verses"] = ["JHN.14.7"]
    assert "cross:en[0].verses: differs_from_fr" in check_cross_language({"fr": [fr], "en": [en]})

def test_cross_language_order_differs():
    a, b = make_entry(), make_entry(("JHN.14.5",))
    b["reference"] = {"book": "JHN", "start": "14.5", "end": "14.5", "label": "Jean 14,5"}
    out = check_cross_language({"fr": [a, b], "en": [_en(b), _en(a)]})
    assert "cross:en[0].verses: differs_from_fr" in out

def test_cross_language_date_range_differs():
    fr = make_entry()
    en = _en(fr)
    en["context"]["temporal"][0]["date_range"]["to"] = 31
    assert "cross:en[0].date_ranges: differs_from_fr" in check_cross_language({"fr": [fr], "en": [en]})

def test_cross_language_place_ids_differ():
    fr = make_entry()
    en = _en(fr)
    en["context"]["places"][0]["place_id"] = "bethany"
    assert "cross:en[0].place_ids: differs_from_fr" in check_cross_language({"fr": [fr], "en": [en]})

def test_cross_language_speaker_role_differs():
    fr = make_entry()
    en = _en(fr)
    en["speaker"]["role"] = "narrator"
    assert "cross:en[0].speaker_role: differs_from_fr" in check_cross_language({"fr": [fr], "en": [en]})

def test_cross_language_source_ids_differ():
    fr = make_entry()
    en = _en(fr)
    en["sources"].append({"id": "extra", "type": "dataset", "dataset": "theographic", "license": "CC BY 4.0"})
    assert "cross:en[0].source_ids: differs_from_fr" in check_cross_language({"fr": [fr], "en": [en]})


# --- build_link ---

def test_build_link():
    url = build_link("lsg", "JHN", "14", "6")
    assert "JHN" in url
    assert "14" in url
    assert "6" in url
