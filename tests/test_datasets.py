"""Tests for the dataset readers, the sources registry, the anchors and the coverage script.

Loaders run on tiny fixtures written to tmp_path. Smoke tests on the real
datasets are skipped when tmp/ has not been fetched.
"""
import importlib.util
import json
from pathlib import Path

import pytest
import yaml

import datasets as ds

ROOT = Path(__file__).resolve().parent.parent


def _load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


fetch_sources = _load_script("fetch_sources")
coverage = _load_script("coverage")


# --- verse keys ---

def test_verse_key_roundtrip():
    assert ds.verse_key("JHN.14.6") == "43014006"
    assert ds.key_to_id("43014006") == "JHN.14.6"
    assert ds.verse_key("GEN.1.1") == "01001001"


@pytest.mark.parametrize("bad", ["JHN.14", "XXX.1.1", "JHN.a.1", "", None, "JHN.1.1.1"])
def test_verse_key_rejects_bad_ids(bad):
    with pytest.raises(ValueError):
        ds.verse_key(bad)


def test_parse_usfm_ref():
    assert ds.parse_usfm_ref("JHN 14:6") == "43014006"
    assert ds.parse_usfm_ref("1CO 13:4") == ds.make_key("1CO", 13, 4)
    assert ds.parse_usfm_ref("XXX 1:1") is None
    assert ds.parse_usfm_ref("JHN 14") is None
    assert ds.parse_usfm_ref(None) is None


# --- Theographic ---

@pytest.mark.parametrize("raw,year,precision", [
    ("-4003", -4003, "year"), ("0030", 30, "year"), ("0030-05-02", 30, "day"), ("-0004-03-01", -4, "day"),
])
def test_parse_theographic_date(raw, year, precision):
    d = ds.parse_theographic_date(raw)
    assert (d["year"], d["precision"], d["raw"]) == (year, precision, raw)


@pytest.mark.parametrize("raw", [None, "", "abc", "30-5-2"])
def test_parse_theographic_date_rejects(raw):
    assert ds.parse_theographic_date(raw) is None


def test_load_theographic(tmp_path):
    j = tmp_path / "json"
    j.mkdir()
    (j / "verses.json").write_text(json.dumps([
        {"id": "recV1", "fields": {"verseID": "44002001"}},
        {"id": "recV2", "fields": {"verseID": "bad"}},
    ]))
    (j / "places.json").write_text(json.dumps([
        {"id": "recP1", "fields": {"displayTitle": "Jerusalem", "placeID": "pl1", "verses": ["recV1", "recV2"]}},
    ]))
    (j / "events.json").write_text(json.dumps([
        {"id": "recE1", "fields": {"title": "Pentecost", "startDate": "0030-05-02", "verses": ["recV1"], "locations": ["recP1"]}},
        {"id": "recE2", "fields": {"title": "No date", "verses": ["recV1"]}},
    ]))
    out = ds.load_theographic(tmp_path)
    ev = out["events"]["44002001"]
    assert len(ev) == 1 and ev[0]["year"] == 30 and ev[0]["places"] == ["Jerusalem"]
    assert out["places"]["44002001"] == [{"name": "Jerusalem", "id": "pl1"}]
    assert list(out["places"]) == ["44002001"]


# --- OpenBible ---

def test_load_openbible(tmp_path):
    f = tmp_path / "ancient.jsonl"
    rec = {"id": "a1", "friendly_id": "Bethany",
           "identifications": [{"score": {"vote_average": 400}}, {"score": {"vote_average": 900}}, {"score": "x"}],
           "linked_data": {"wikidata": {"id": "Q123"}, "other": {"id": "nope"}},
           "verses": [{"sort": "43011001"}, {"sort": "oops"}]}
    f.write_text(json.dumps(rec) + "\n\n")
    out = ds.load_openbible(f)
    assert list(out) == ["43011001"]
    assert out["43011001"][0] | {} == {"id": "a1", "name": "Bethany", "wikidata": "Q123", "score": 900, "identifications": 3}


def test_load_openbible_without_scores(tmp_path):
    f = tmp_path / "a.jsonl"
    f.write_text(json.dumps({"id": "a", "friendly_id": "X", "verses": [{"sort": "01001001"}]}))
    item = ds.load_openbible(f)["01001001"][0]
    assert item["score"] is None and item["wikidata"] is None


# --- speaker-quotations ---

TSV = ("START VS\tEND VS\tSPEAKER (FCBH)\tQUOTE TYPE\n"
       "JHN 14:6\tJHN 14:6\tJesus\tNormal\n"
       "JHN 18:38\tJHN 18:38\tPilate\tNormal\n"
       "JHN 18:38\tJHN 18:39\t\tNormal\n"
       "XXX 1:1\tXXX 1:1\tNobody\tNormal\n"
       "short\n")


def test_load_speakers_and_speakers_at(tmp_path):
    f = tmp_path / "s.tsv"
    f.write_text(TSV)
    rows = ds.load_speakers(f)
    assert [r["speaker"] for r in rows] == ["Jesus", "Pilate"]
    assert rows == sorted(rows, key=lambda r: (r["start"], r["end"]))
    assert ds.speakers_at(rows, ds.verse_key("JHN.14.6")) == ["Jesus"]
    assert ds.speakers_at(rows, ds.verse_key("JHN.14.7")) == []


def test_speakers_at_dedupes_and_covers_ranges():
    rows = [{"start": "43014001", "end": "43014010", "speaker": "Jesus", "type": "n"},
            {"start": "43014005", "end": "43014007", "speaker": "Jesus", "type": "n"},
            {"start": "43014006", "end": "43014006", "speaker": "Thomas", "type": "n"}]
    assert ds.speakers_at(rows, "43014006") == ["Jesus", "Thomas"]


# --- ACAI ---

def test_load_acai(tmp_path):
    for kind in ("people", "places"):
        (tmp_path / kind / "json").mkdir(parents=True)
    (tmp_path / "people" / "json" / "a.json").write_text(json.dumps(
        {"id": "p-1", "localizations": {"eng": {"preferred_label": "Pilate"}}, "references": ["43018038", "bad"]}))
    (tmp_path / "places" / "json" / "b.json").write_text(json.dumps({"id": "pl-1", "references": ["43018028"]}))
    out = ds.load_acai(tmp_path)
    assert out["people"] == {"43018038": [{"id": "p-1", "label": "Pilate"}]}
    assert out["places"] == {"43018028": [{"id": "pl-1", "label": "pl-1"}]}


# --- TVTMS ---

TVTMS = """﻿# header
#DataStart(Expanded)
SourceType\tSourceRef\tStandardRef\tAction\tNoteMarker
# a comment
'test line
Hebrew\tPsa.3:1\tPsa.3:Title\tMerged\t
Hebrew\tPsa.3:2\tPsa.3:1\tRenumber\t
Eng-KJV+Hebrew\t2Ch.2:6\t2Ch.2:7\tRenumber\t
Hebrew\t\tPsa.9:9\tKeep\t
#DataEnd(Expanded)
Hebrew\tIgnored.1:1\tX\tKeep\t
"""


def test_load_tvtms(tmp_path):
    f = tmp_path / "t.txt"
    f.write_text(TVTMS, encoding="utf-8")
    rows = ds.load_tvtms(f)
    assert len(rows) == 3
    assert ds.tvtms_standard_refs(rows, "Hebrew", "Psa.3:1") == ["Psa.3:Title"]
    assert ds.tvtms_standard_refs(rows, "Eng-KJV", "2Ch.2:6") == ["2Ch.2:7"]
    assert ds.tvtms_standard_refs(rows, "Hebrew", "Psa.99:1") == []


def test_load_tvtms_errors(tmp_path):
    f = tmp_path / "t.txt"
    f.write_text("nothing here")
    with pytest.raises(ValueError, match="not found"):
        ds.load_tvtms(f)
    f.write_text("#DataStart(Expanded)\nA\tB\n#DataEnd(Expanded)\n")
    with pytest.raises(ValueError, match="columns"):
        ds.load_tvtms(f)


# --- anchors ---

def _anchor(**kw):
    a = {"id": "a1", "claim": "c", "kind": "ancient_author",
         "reference": {"work": "w", "location": "l", "edition": "e", "url": "https://x"},
         "check_quote": "a short quote", "verified_on": "2026-10-07", "date_range": None, "reason": "relative dating"}
    a.update(kw)
    return a


def test_check_anchors_valid():
    assert ds.check_anchors({"anchors": [_anchor()]}) == []
    ok = _anchor(date_range={"from": 14, "to": 37, "era": "CE", "basis": "reign"}, reason=None)
    assert ds.check_anchors({"anchors": [ok]}) == []


@pytest.mark.parametrize("data", [None, {}, {"anchors": "x"}, []])
def test_check_anchors_bad_container(data):
    assert ds.check_anchors(data)


@pytest.mark.parametrize("change,fragment", [
    ({"id": ""}, "id"),
    ({"kind": "rumour"}, "kind"),
    ({"reference": {"work": "w"}}, "reference"),
    ({"check_quote": " ".join(["w"] * 41)}, "check_quote"),
    ({"check_quote": ""}, "check_quote"),
    ({"verified_on": "yesterday"}, "verified_on"),
    ({"reason": None}, "reason"),
    ({"date_range": {"from": 40, "to": 30, "era": "CE", "basis": "b"}}, "date_range"),
    ({"date_range": {"from": 1, "to": 2, "era": "AD", "basis": "b"}}, "date_range"),
    ({"date_range": {"from": 1, "to": 2, "era": "CE", "basis": ""}}, "date_range"),
])
def test_check_anchors_problems(change, fragment):
    errs = ds.check_anchors({"anchors": [_anchor(**change)]})
    assert errs and any(fragment in e for e in errs)


def test_check_anchors_duplicate_id():
    errs = ds.check_anchors({"anchors": [_anchor(), _anchor()]})
    assert any("duplicate" in e for e in errs)


def test_anchors_file_is_valid_and_quotes_are_short():
    anchors = ds.load_anchors()
    assert anchors
    for a in anchors:
        assert len(a["check_quote"].split()) <= 40
        # no year may be written without a source: a null range always has a reason
        assert a["date_range"] is not None or a["reason"]


def test_load_anchors_raises_on_invalid(tmp_path):
    f = tmp_path / "a.yml"
    f.write_text("anchors: [{id: x}]")
    with pytest.raises(ValueError):
        ds.load_anchors(f)


# --- sources registry ---

REGISTRY = yaml.safe_load((ROOT / "data" / "sources.yml").read_text(encoding="utf-8"))["sources"]
LOCK = json.loads((ROOT / "data" / "sources.lock.json").read_text(encoding="utf-8"))
SOURCES_MD = (ROOT / "data" / "SOURCES.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("sid", sorted(REGISTRY))
def test_every_source_has_license_and_usage(sid):
    src = REGISTRY[sid]
    assert src.get("license") and src.get("usage") and "name" in src
    assert "attribution" in src  # explicit null for public domain
    if "BY" in src["license"] and src["license"] != "CC0-1.0":
        assert src["attribution"], f"{sid}: a CC BY license needs an attribution string"


@pytest.mark.parametrize("sid", sorted(REGISTRY))
def test_every_source_is_documented_in_sources_md(sid):
    repo = REGISTRY[sid].get("repo")
    needle = "/".join(repo.split("/")[-2:]) if repo and "github.com" in repo else sid
    assert needle in SOURCES_MD or f"`{sid}`" in SOURCES_MD


def test_fetchable_sources_are_pinned_and_have_license_checks():
    for sid, src in fetch_sources.fetchable(REGISTRY).items():
        assert sid in LOCK and len(LOCK[sid]["commit"]) == 40
        assert src["dir"].startswith("tmp/") and src["license_file"] and src["license_markers"]


def test_sources_md_states_the_theographic_license():
    assert "CC BY-SA 4.0" in SOURCES_MD and REGISTRY["theographic"]["license"] == "CC-BY-SA-4.0"


# --- fetch_sources.check_license ---

def _src(markers=("CC BY 4.0",)):
    return {"dir": "tmp/x", "license_file": "LICENSE", "license_markers": list(markers)}


def test_check_license_ok(tmp_path):
    (tmp_path / "tmp" / "x").mkdir(parents=True)
    (tmp_path / "tmp" / "x" / "LICENSE").write_text("licensed under CC BY 4.0")
    assert fetch_sources.check_license(_src(), tmp_path) == []


def test_check_license_missing_marker_and_file(tmp_path):
    assert "not found" in fetch_sources.check_license(_src(), tmp_path)[0]
    (tmp_path / "tmp" / "x").mkdir(parents=True)
    (tmp_path / "tmp" / "x" / "LICENSE").write_text("now proprietary")
    assert "missing" in fetch_sources.check_license(_src(), tmp_path)[0]


def test_check_license_detects_license_change_for_every_marker(tmp_path):
    (tmp_path / "tmp" / "x").mkdir(parents=True)
    (tmp_path / "tmp" / "x" / "LICENSE").write_text("MIT License")
    assert len(fetch_sources.check_license(_src(("MIT License", "CC BY 4.0")), tmp_path)) == 1


# --- coverage script ---

def test_parse_fr_reference():
    assert coverage.parse_fr_reference("Jean 14,6") == "JHN.14.6"
    assert coverage.parse_fr_reference("Jean 14,6-7") == "JHN.14.6"
    assert coverage.parse_fr_reference("Inconnu 1,1") is None
    assert coverage.parse_fr_reference("") is None
    assert coverage.parse_fr_reference(None) is None


def test_sample_passages_is_deterministic_and_keeps_fixed():
    pool = [f"JHN.1.{i}" for i in range(1, 60)]
    a, b = coverage.sample_passages(pool), coverage.sample_passages(list(reversed(pool)))
    assert a == b and len(a) == 20 and a[:4] == coverage.FIXED
    assert len(set(a)) == 20


def test_sample_passages_small_pool_and_fixed_not_repeated():
    out = coverage.sample_passages(["JHN.14.6", "MAT.5.18"])
    assert out == coverage.FIXED + ["MAT.5.18"]


def test_measure_and_render():
    th = {"events": {"43014006": [{"year": 30, "precision": "day", "places": ["Jerusalem"]}]}, "places": {}}
    rows = coverage.measure(["JHN.14.6", "MAT.5.18"], th, {}, [], {"people": {}, "places": {}})
    assert rows[0]["theo_dates"] == ["30 (day)"] and rows[1]["theo_dates"] == []
    text = coverage.render(rows, {"acai": {"commit": "a" * 40}})
    assert "1/2" in text and "0/2" in text and "`aaaaaaaaaa`" in text


# --- smoke tests on the real data (skipped when not fetched) ---

needs = lambda p: pytest.mark.skipif(not (ROOT / p).exists(), reason=f"{p} not fetched")  # noqa: E731


@needs("tmp/theographic/json/events.json")
def test_real_theographic_pentecost_year():
    out = ds.load_theographic()
    assert any(e["year"] == 30 for e in out["events"][ds.verse_key("ACT.2.1")])


@needs("tmp/speaker-quotations/tsv/Clear-Aligned-Projections.tsv")
def test_real_speaker_john_14_6():
    assert "Jesus" in " ".join(ds.speakers_at(ds.load_speakers(), ds.verse_key("JHN.14.6")))


@needs("tmp/openbible-geocoding/data/ancient.jsonl")
def test_real_openbible_has_entries():
    assert len(ds.load_openbible()) > 1000


@needs("tmp/stepbible/Versification")
def test_real_tvtms_psalm_title():
    path = next((ROOT / "tmp" / "stepbible" / "Versification").glob("TVTMS*.txt"))
    rows = ds.load_tvtms(path)
    assert ds.tvtms_standard_refs(rows, "Hebrew", "Psa.3:1") == ["Psa.3:Title"]


@needs("tmp/acai/people/json")
def test_real_acai_has_people():
    assert len(ds.load_acai()["people"]) > 1000
