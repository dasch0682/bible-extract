"""Tests for provenance.py and speaker.py (task 6, speaker).

All logic runs on tiny in-memory fixtures; the smoke test on the real datasets is
skipped when tmp/ has not been fetched.
"""
import json
from pathlib import Path

import pytest
import yaml

import datasets as ds
import provenance as pv
import speaker as sp
import validate

ROOT = Path(__file__).resolve().parent.parent
FR = {"dataset": "lsg1910", "prompt_lang": "French", "translation": "Louis Segond 1910"}
REG = pv.load_registry()


def rng(start, end, speaker, qtype="Normal"):
    return {"start": ds.verse_key(start), "end": ds.verse_key(end), "speaker": speaker, "type": qtype}


def people(*items):
    """{'people': {verse key: [entity]}} from (verse id, id, label) triples."""
    out = {}
    for vid, pid, label in items:
        out.setdefault(ds.verse_key(vid), []).append({"id": pid, "label": label})
    return {"people": out, "places": {}}


# --- provenance ---

def test_verse_source_takes_license_from_registry():
    rec = pv.verse_source("JHN.14.6", "lsg1910", REG)
    assert rec == {"id": "JHN.14.6", "type": "bible_text", "dataset": "lsg1910", "license": REG["lsg1910"]["license"]}


def test_unknown_dataset_is_refused():
    with pytest.raises(KeyError):
        pv.dataset_source("x", "no-such-dataset", "speaker_data", REG)


def test_merge_sources_keeps_first_of_each_id():
    a = {"id": "A", "type": "t", "dataset": "d", "license": "l"}
    b = {"id": "B", "type": "t", "dataset": "d", "license": "l"}
    assert pv.merge_sources([a, b], [dict(a, license="other")]) == [a, b]


def test_known_datasets_cover_the_speaker_datasets():
    assert {"speaker-quotations", "acai", "lsg1910", "kjv"} <= pv.known_datasets(REG)


def test_languages_yml_names_a_registered_dataset_per_language():
    langs = yaml.safe_load((ROOT / "languages.yml").read_text(encoding="utf-8"))
    for cfg in langs.values():
        assert cfg["dataset"] in REG


# --- identification ---

def test_single_speaker_confirmed_by_acai_is_high():
    ident = sp.identify(["JHN.14.6"], [rng("JHN.14.6", "JHN.14.7", "Jesus", "Dialogue")],
                        people(("JHN.14.6", "person:Jesus.2", "Jesus")))
    assert (ident["label"], ident["role"], sp.rate(ident), ident["flags"]) == ("Jesus", "speaker", "high", [])


def test_dataset_alone_is_medium_whatever_the_undocumented_type():
    for qtype in ("Normal", "Implicit", "Quotation"):
        ident = sp.identify(["MAT.5.18"], [rng("MAT.5.3", "MAT.7.27", "Jesus", qtype)], {"people": {}, "places": {}})
        assert sp.rate(ident) == "medium"
        assert ident["types"] == [qtype]


def test_hypothetical_quotation_is_low():
    ident = sp.identify(["LUK.15.18"], [rng("LUK.15.18", "LUK.15.19", "prodigal son", "Hypothetical")],
                        {"people": {}, "places": {}})
    assert sp.rate(ident) == "low" and "speaker_hypothetical" in ident["flags"]


def test_acai_match_uses_the_verse_before_the_quotation():
    ident = sp.identify(["JHN.18.38"], [rng("JHN.18.38", "JHN.18.39", "Pilate")],
                        people(("JHN.18.37", "person:Pilate", "Pilate")))
    assert sp.rate(ident) == "high"


def test_acai_match_is_exact_not_fuzzy():
    # 'John' must not confirm 'John (the Baptist)'; the parenthetical form does match
    acai = people(("MAT.11.11", "person:John", "John"))
    ident = sp.identify(["MAT.11.11"], [rng("MAT.11.4", "MAT.11.19", "John (the Baptist)")], acai)
    assert ident["agreement"] == [] and sp.rate(ident) == "medium"
    acai = people(("1JN.5.6", "person:Christ", "Christ (Jesus)"))
    assert sp.acai_agreement("Jesus", acai["people"][ds.verse_key("1JN.5.6")])


def test_partial_coverage_lowers_the_level():
    ranges = [rng("JHN.14.6", "JHN.14.6", "Jesus")]
    with_acai = sp.identify(["JHN.14.5", "JHN.14.6"], ranges, people(("JHN.14.6", "person:Jesus.2", "Jesus")))
    assert "speaker_partial_coverage" in with_acai["flags"] and sp.rate(with_acai) == "medium"
    without = sp.identify(["JHN.14.5", "JHN.14.6"], ranges, {"people": {}, "places": {}})
    assert sp.rate(without) == "low"


def test_two_speakers_in_one_excerpt_is_ambiguous_and_null():
    ranges = [rng("JHN.18.37", "JHN.18.37", "Jesus"), rng("JHN.18.38", "JHN.18.38", "Pilate")]
    ident = sp.identify(["JHN.18.37", "JHN.18.38"], ranges, {"people": {}, "places": {}})
    built = sp.build_speaker(ident, None, FR, REG)
    assert built["speaker"] == {"value": None, "reason": "not_identified"}
    assert built["candidates"] == ["Jesus", "Pilate"] and "speaker_ambiguous" in built["flags"]
    assert set(built["flags"]) & sp.REVIEW_FLAGS


def test_nobody_identified_is_not_identified():
    ident = sp.identify(["ACT.2.1"], [], {"people": {}, "places": {}})
    built = sp.build_speaker(ident, None, FR, REG)
    assert built["speaker"] == {"value": None, "reason": "not_identified"} and built["sources"] == []
    assert built["flags"] == ["speaker_not_identified"]


def test_narrator_label_gives_role_narrator():
    ident = sp.identify(["JHN.13.21"], [rng("JHN.13.11", "JHN.13.21", "narrator-JHN", "Quotation")],
                        {"people": {}, "places": {}})
    assert ident["role"] == "narrator" and sp.rate(ident) == "medium"


# --- the schema-2 field ---

def test_built_speaker_passes_validate_and_lists_its_sources():
    ident = sp.identify(["JHN.14.6"], [rng("JHN.14.6", "JHN.14.7", "Jesus", "Dialogue")],
                        people(("JHN.14.6", "person:Jesus.2", "Jesus")))
    built = sp.build_speaker(ident, "Jésus", FR, REG)
    field = built["speaker"]
    assert field["value"] == "Jésus" and field["confidence"] == "high"
    assert field["sources"] == ["JHN.14.6", "speaker-quotations:JHN.14.6-JHN.14.7", "acai:person:Jesus.2"]
    assert [s["id"] for s in built["sources"]] == field["sources"]
    assert validate.check_speaker(field) == []
    # every cited source is listed with type, dataset and license
    assert all(s["type"] and s["dataset"] in pv.known_datasets(REG) and s["license"] for s in built["sources"])


def test_missing_localized_name_keeps_the_label_and_flags_review():
    ident = sp.identify(["JHN.14.6"], [rng("JHN.14.6", "JHN.14.7", "Jesus")], {"people": {}, "places": {}})
    built = sp.build_speaker(ident, None, FR, REG)
    assert built["speaker"]["value"] == "Jesus" and "name_not_localized" in built["flags"]
    assert validate.check_speaker(built["speaker"]) == []


# --- name rendering (model injected, cached) ---

@pytest.mark.parametrize("raw,expected", [
    ("Jésus", "Jésus"), ('  "Pilate"\n', "Pilate"), ("«Pierre»", "Pierre"),
    ("", None), (None, None), ("Jésus\nou Christ", None), ("a b c d e f g h i j k l m", None), ("{name}", None),
])
def test_clean_name(raw, expected):
    assert sp.clean_name(raw) == expected


def test_render_name_calls_the_model_once_then_uses_the_cache(tmp_path):
    calls = []

    def call(system, user):
        calls.append((system, user))
        return "Ponce Pilate"

    args = ("Pilate", "JHN", "fr", FR, ["JHN.18.38: Pilate lui dit: Qu'est-ce que la vérité?"], call,
            "deepseek/deepseek-v4.1-flash", tmp_path)
    assert sp.render_name(*args) == "Ponce Pilate"
    assert sp.render_name(*args) == "Ponce Pilate"
    assert len(calls) == 1
    assert "French" in calls[0][0] and "Pilate" in calls[0][1]
    cached = list((tmp_path / "speaker-name" / "fr").glob("*.json"))
    assert len(cached) == 1 and json.loads(cached[0].read_text(encoding="utf-8"))["prompt_version"] == sp.NAME_PROMPT_VERSION


def test_render_name_does_not_cache_an_invalid_answer(tmp_path):
    out = sp.render_name("Jesus", "JHN", "fr", FR, [], lambda s, u: "two\nlines", "m", tmp_path)
    assert out is None and not list(tmp_path.rglob("*.json"))


def test_cache_key_depends_on_model_and_language(tmp_path):
    sp.render_name("Jesus", "JHN", "fr", FR, [], lambda s, u: "Jésus", "model/a", tmp_path)
    sp.render_name("Jesus", "JHN", "fr", FR, [], lambda s, u: "Jésus", "model/b", tmp_path)
    assert len(list((tmp_path / "speaker-name" / "fr").glob("*.json"))) == 2


# --- smoke test on the real datasets ---

real = pytest.mark.skipif(not (ROOT / "tmp" / "speaker-quotations").exists() or not (ROOT / "tmp" / "acai").exists(),
                          reason="tmp/ datasets not fetched")


@real
def test_real_data_john_14_6_is_jesus_high():
    ident = sp.identify(["JHN.14.6"], ds.load_speakers(), ds.load_acai())
    assert ident["label"] == "Jesus" and sp.rate(ident) == "high"
